from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
import importlib.util
import inspect
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from core.providers.agentic_models import codex_routing_constraint, codex_runtime_policy
from core.providers.certificate_service import (
    revoke_capability_certificate,
    runtime_adapter_artifact_digest,
    validate_certificate_for_binding,
)
from core.providers.errors import CapabilityCertificateConflictError, CapabilityCertificateError
from core.providers.evidence_store import CapabilityEvidenceBlobStore
from core.providers.google_interactions_client import GoogleInteractionsAgenticClient
from core.providers.openrouter_agentic_client import OpenRouterAgenticClient
from core.runtime.authority import resolve_effective_runtime_authority
from core.runtime.execution_binding import build_runtime_execution_binding, canonical_digest
from core.runtime.hosted_agentic_loop import HostedAgenticLoop
from tests.support.agentic_certification import (
    certified_test_provider_store,
    fake_capability_evidence,
)
from tests.support.fake_agentic_adapter import FakeHostedAgenticAdapter


NOW = datetime(2026, 8, 16, tzinfo=UTC)


class CapabilityCertificateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = FakeHostedAgenticAdapter()
        self.evidence = fake_capability_evidence(self.adapter, now=NOW)
        self.binding = self._binding()
        self.store = certified_test_provider_store(
            self.binding,
            self.adapter,
            evidence=self.evidence,
            now=NOW,
        )

    def _binding(self, **updates):
        routing = updates.pop("routing_constraint", codex_routing_constraint())
        return build_runtime_execution_binding(
            session_id="session-certified",
            workspace_id="default",
            profile_definition_id="profile-certified",
            profile_definition_revision="1",
            workspace_binding_id="workspace-certified",
            workspace_binding_revision=0,
            capability_certificate_id="certificate-certified",
            runtime_engine_id=self.adapter.runtime_engine_id,
            adapter_id=self.adapter.adapter_id,
            adapter_version=self.adapter.adapter_version,
            adapter_artifact_digest=runtime_adapter_artifact_digest(self.adapter),
            model_provider_id="fake-provider",
            model_id="fake-model",
            provider_protocol="fake-stream-v1",
            provider_api_version="v1",
            routing_constraint=routing,
            credential_binding_id=None,
            reasoning_effort=updates.pop("reasoning_effort", None),
            certified_reasoning_efforts=updates.pop("certified_reasoning_efforts", ()),
            default_reasoning_effort=updates.pop("default_reasoning_effort", None),
            execution_mode="full-access",
            profile_policy_ceiling=updates.pop("profile_policy", codex_runtime_policy()),
            workspace_policy_ceiling=updates.pop("workspace_policy", codex_runtime_policy()),
            egress_policy_id="fake-egress",
            egress_policy_revision="1",
            certificate_evidence_digest=self.evidence.evidence_digest,
            created_at=NOW,
            **updates,
        )

    def test_exact_certificate_grants_only_policy_intersection(self) -> None:
        live = self.store.get_workspace_agentic_profile_binding(self.binding.workspace_binding_id)
        narrowed_policy = replace(
            live.workspace_policy_ceiling,
            allowed_surface_kinds=("mcp",),
            allow_filesystem_write=False,
            allow_shell=False,
        )
        self.store.save_workspace_agentic_profile_binding(
            replace(live, workspace_policy_ceiling=narrowed_policy, revision=1, updated_at=NOW),
            expected_revision=0,
        )

        authority = resolve_effective_runtime_authority(
            self.store,
            binding=self.binding,
            adapter=self.adapter,
            turn_id="turn-certified",
            currently_authorized_tool_handles=("mcp:read", "cli:write"),
            now=NOW,
        )

        self.assertTrue(authority.allowed_capabilities.mcp)
        self.assertFalse(authority.allowed_capabilities.cli)
        self.assertFalse(authority.allowed_capabilities.filesystem_write)
        self.assertFalse(authority.allowed_capabilities.shell)
        self.assertEqual(authority.authority_digest, canonical_digest(authority))

    def test_live_egress_policy_drift_blocks_existing_binding(self) -> None:
        live = self.store.get_workspace_agentic_profile_binding(
            self.binding.workspace_binding_id
        )
        self.store.save_workspace_agentic_profile_binding(
            replace(
                live,
                egress_policy_revision="2",
                revision=live.revision + 1,
                updated_at=NOW,
            ),
            expected_revision=live.revision,
        )

        with self.assertRaisesRegex(
            CapabilityCertificateError,
            "egress_policy_drift_unresolved",
        ):
            resolve_effective_runtime_authority(
                self.store,
                binding=self.binding,
                adapter=self.adapter,
                turn_id="turn-drifted-egress",
                now=NOW,
            )

    def test_revoked_or_expired_certificate_cannot_execute(self) -> None:
        revoked = revoke_capability_certificate(
            self.store,
            certificate_id=self.binding.capability_certificate_id,
            expected_revision=0,
            reason="test_revocation",
            now=NOW,
        )
        self.assertEqual(revoked.revision, 1)
        with self.assertRaisesRegex(CapabilityCertificateError, "certificate_revoked"):
            validate_certificate_for_binding(
                self.store, binding=self.binding, adapter=self.adapter, now=NOW
            )
        with self.assertRaisesRegex(CapabilityCertificateError, "certificate_status_revision_conflict"):
            revoke_capability_certificate(
                self.store,
                certificate_id=self.binding.capability_certificate_id,
                expected_revision=0,
                reason="stale_revoke",
                now=NOW,
            )

        fresh_store = certified_test_provider_store(
            self.binding, self.adapter, evidence=self.evidence, now=NOW
        )
        with self.assertRaisesRegex(CapabilityCertificateError, "certificate_expired"):
            validate_certificate_for_binding(
                fresh_store,
                binding=self.binding,
                adapter=self.adapter,
                now=NOW + timedelta(days=2),
            )

    def test_certificate_identity_is_immutable(self) -> None:
        certificate = self.store.get_capability_certificate(self.binding.capability_certificate_id)
        with self.assertRaisesRegex(CapabilityCertificateConflictError, "certificate_immutable_conflict"):
            self.store.save_capability_certificate(replace(certificate, model_id="other-model"))

    def test_adapter_artifact_and_version_are_verified_live(self) -> None:
        changed_adapter = FakeHostedAgenticAdapter()
        changed_adapter.adapter_version = "2"
        with self.assertRaisesRegex(CapabilityCertificateError, "adapter_version_mismatch"):
            validate_certificate_for_binding(
                self.store,
                binding=self.binding,
                adapter=changed_adapter,
                now=NOW,
            )

        tampered = replace(self.binding, adapter_artifact_digest="0" * 64, binding_digest="")
        tampered = replace(tampered, binding_digest=canonical_digest(tampered))
        with self.assertRaisesRegex(
            CapabilityCertificateError,
            "certificate_adapter_artifact_digest_mismatch",
        ):
            validate_certificate_for_binding(
                self.store,
                binding=tampered,
                adapter=self.adapter,
                now=NOW,
            )

    def test_function_and_module_source_changes_invalidate_artifact_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "digest_component.py"
            source_path.write_text("def operation():\n    return 1\n", encoding="utf-8")
            spec = importlib.util.spec_from_file_location("digest_component", source_path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            self.addCleanup(sys.modules.pop, spec.name, None)
            spec.loader.exec_module(module)

            class FunctionAdapter(FakeHostedAgenticAdapter):
                artifact_components = (module.operation,)

            class ModuleAdapter(FakeHostedAgenticAdapter):
                artifact_components = (module,)

            function_digest = runtime_adapter_artifact_digest(FunctionAdapter())
            module_digest = runtime_adapter_artifact_digest(ModuleAdapter())
            source_path.write_text("def operation():\n    return 2\n", encoding="utf-8")

            self.assertNotEqual(
                runtime_adapter_artifact_digest(FunctionAdapter()),
                function_digest,
            )
            self.assertNotEqual(
                runtime_adapter_artifact_digest(ModuleAdapter()),
                module_digest,
            )

    def test_each_declared_operational_module_affects_artifact_digest(self) -> None:
        loop = object.__new__(HostedAgenticLoop)
        google = object.__new__(GoogleInteractionsAgenticClient)
        openrouter = object.__new__(OpenRouterAgenticClient)
        components = (
            *loop.artifact_components,
            *google.artifact_components,
            *openrouter.artifact_components,
        )
        adapter_type = type(
            "OperationalArtifactAdapter",
            (FakeHostedAgenticAdapter,),
            {"artifact_components": components},
        )
        adapter = adapter_type()
        baseline = runtime_adapter_artifact_digest(adapter)
        source_paths = {
            Path(source).resolve()
            for component in components
            if (source := inspect.getsourcefile(component)) is not None
        }
        original_read_bytes = Path.read_bytes

        self.assertGreater(len(source_paths), 10)
        for source_path in source_paths:
            with self.subTest(source_path=source_path.name):
                def modified_read_bytes(path: Path, *, target=source_path) -> bytes:
                    payload = original_read_bytes(path)
                    return payload + b"\n# simulated source mutation\n" if path.resolve() == target else payload

                with patch.object(Path, "read_bytes", modified_read_bytes):
                    self.assertNotEqual(runtime_adapter_artifact_digest(adapter), baseline)

    def test_effective_upstream_must_be_certified(self) -> None:
        routing = replace(
            codex_routing_constraint(),
            endpoint_id="fake-router",
            allowed_upstream_ids=("upstream-a",),
            data_collection_policy="deny",
        )
        binding = self._binding(routing_constraint=routing)
        store = certified_test_provider_store(
            binding, self.adapter, evidence=self.evidence, now=NOW
        )

        validate_certificate_for_binding(
            store,
            binding=binding,
            adapter=self.adapter,
            observed_upstream_id="upstream-a",
            now=NOW,
        )
        with self.assertRaisesRegex(CapabilityCertificateError, "provider_upstream_not_certified"):
            validate_certificate_for_binding(
                store,
                binding=binding,
                adapter=self.adapter,
                observed_upstream_id="upstream-b",
                now=NOW,
            )

    def test_reasoning_contract_is_immutable_and_verified_live(self) -> None:
        binding = self._binding(
            reasoning_effort="high",
            certified_reasoning_efforts=("low", "high"),
            default_reasoning_effort="high",
        )
        store = certified_test_provider_store(
            binding,
            self.adapter,
            evidence=self.evidence,
            now=NOW,
        )

        certificate = validate_certificate_for_binding(
            store,
            binding=binding,
            adapter=self.adapter,
            now=NOW,
        )
        self.assertEqual(certificate.certified_reasoning_efforts, ("low", "high"))
        self.assertEqual(certificate.default_reasoning_effort, "high")

        drifted = replace(
            binding,
            certified_reasoning_efforts=("minimal", "low", "high"),
            binding_digest="",
        )
        drifted = replace(drifted, binding_digest=canonical_digest(drifted))
        with self.assertRaisesRegex(
            CapabilityCertificateError,
            "certificate_certified_reasoning_efforts_mismatch",
        ):
            validate_certificate_for_binding(
                store,
                binding=drifted,
                adapter=self.adapter,
                now=NOW,
            )

    def test_missing_certificate_and_unavailable_health_fail_closed(self) -> None:
        missing = replace(self.binding, capability_certificate_id="missing", binding_digest="")
        missing = replace(missing, binding_digest=canonical_digest(missing))
        with self.assertRaisesRegex(CapabilityCertificateError, "certificate_missing"):
            validate_certificate_for_binding(
                self.store, binding=missing, adapter=self.adapter, now=NOW
            )
        with self.assertRaisesRegex(CapabilityCertificateError, "runtime_health_unavailable"):
            resolve_effective_runtime_authority(
                self.store,
                binding=self.binding,
                adapter=self.adapter,
                turn_id="turn-unhealthy",
                health_status="unavailable",
                now=NOW,
            )

    def test_evidence_blob_store_is_content_addressed_and_integrity_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CapabilityEvidenceBlobStore(Path(temp_dir))
            evidence_ref = store.put(b"certification evidence")
            self.assertEqual(store.get(evidence_ref), b"certification evidence")
            digest = evidence_ref.rsplit(":", 1)[-1]
            (Path(temp_dir) / digest[:2] / digest).write_bytes(b"tampered")
            with self.assertRaisesRegex(CapabilityCertificateError, "certificate_evidence_blob_corrupt"):
                store.get(evidence_ref)

    def test_legacy_evidence_digest_remains_valid_after_schema_extension(self) -> None:
        legacy_fields = (
            "suite_id",
            "suite_version",
            "test_run_id",
            "adapter_artifact_digest",
            "result_summary_digest",
            "evidence_refs",
            "recorded_at",
        )
        legacy_digest = canonical_digest(
            {field: getattr(self.evidence, field) for field in legacy_fields}
        )
        legacy_evidence = replace(self.evidence, evidence_digest=legacy_digest)
        legacy_binding = replace(
            self.binding,
            certificate_evidence_digest=legacy_digest,
            binding_digest="",
        )
        legacy_binding = replace(
            legacy_binding,
            binding_digest=canonical_digest(legacy_binding),
        )
        legacy_store = certified_test_provider_store(
            legacy_binding,
            self.adapter,
            evidence=legacy_evidence,
            now=NOW,
        )

        validated = validate_certificate_for_binding(
            legacy_store,
            binding=legacy_binding,
            adapter=self.adapter,
            now=NOW,
        )

        self.assertEqual(validated.evidence_digest, legacy_digest)

        tampered_evidence = replace(legacy_evidence, suite_version="tampered")
        tampered_store = certified_test_provider_store(
            legacy_binding,
            self.adapter,
            evidence=tampered_evidence,
            now=NOW,
        )
        with self.assertRaisesRegex(CapabilityCertificateError, "certificate_evidence_corrupt"):
            validate_certificate_for_binding(
                tampered_store,
                binding=legacy_binding,
                adapter=self.adapter,
                now=NOW,
            )


    def test_rehydrated_execution_binding_validates_without_upstream_type_mismatch(self) -> None:
        from core.runtime.execution_binding import execution_binding_from_document

        serialized = asdict(self.binding)
        serialized["routing_constraint_snapshot"]["allowed_upstream_ids"] = list(
            self.binding.routing_constraint_snapshot.allowed_upstream_ids
        )
        self.assertIsInstance(serialized["routing_constraint_snapshot"]["allowed_upstream_ids"], list)

        rehydrated = execution_binding_from_document(serialized)
        self.assertIsInstance(rehydrated.routing_constraint_snapshot.allowed_upstream_ids, tuple)

        validated = validate_certificate_for_binding(
            self.store,
            binding=rehydrated,
            adapter=self.adapter,
            now=NOW,
        )
        self.assertEqual(validated.certificate_id, self.binding.capability_certificate_id)

    def test_rehydrated_legacy_binding_defaults_new_list_capability_fail_closed(self) -> None:
        from core.runtime.execution_binding import execution_binding_from_document

        serialized = asdict(self.binding)
        for field_name in (
            "profile_policy_ceiling_snapshot",
            "workspace_policy_ceiling_snapshot",
        ):
            serialized[field_name].pop("allow_filesystem_list")
        serialized["tool_authority_ceiling_digest"] = canonical_digest(
            serialized["workspace_policy_ceiling_snapshot"]
        )
        serialized["binding_digest"] = canonical_digest(serialized)

        rehydrated = execution_binding_from_document(serialized)

        self.assertFalse(
            rehydrated.profile_policy_ceiling_snapshot.allow_filesystem_list
        )
        self.assertFalse(
            rehydrated.workspace_policy_ceiling_snapshot.allow_filesystem_list
        )
        self.assertEqual(rehydrated.binding_digest, serialized["binding_digest"])

        reserialized = asdict(rehydrated)
        round_tripped = execution_binding_from_document(reserialized)
        self.assertFalse(
            round_tripped.profile_policy_ceiling_snapshot.allow_filesystem_list
        )
        self.assertEqual(round_tripped.binding_digest, serialized["binding_digest"])

        reserialized["workspace_policy_ceiling_snapshot"][
            "allow_filesystem_list"
        ] = True
        with self.assertRaisesRegex(ValueError, "digest"):
            execution_binding_from_document(reserialized)

        serialized["model_id"] = "tampered-model"
        with self.assertRaisesRegex(ValueError, "digest"):
            execution_binding_from_document(serialized)

    def test_rehydrated_legacy_binding_round_trips_reasoning_defaults_fail_closed(self) -> None:
        from core.runtime.execution_binding import execution_binding_from_document

        serialized = asdict(self.binding)
        serialized.pop("certified_reasoning_efforts")
        serialized.pop("default_reasoning_effort")
        serialized["binding_digest"] = canonical_digest(serialized)

        rehydrated = execution_binding_from_document(serialized)
        self.assertEqual(rehydrated.certified_reasoning_efforts, ())
        self.assertIsNone(rehydrated.default_reasoning_effort)

        reserialized = asdict(rehydrated)
        round_tripped = execution_binding_from_document(reserialized)
        self.assertEqual(round_tripped.binding_digest, serialized["binding_digest"])

        reserialized["certified_reasoning_efforts"] = ["high"]
        with self.assertRaisesRegex(ValueError, "digest"):
            execution_binding_from_document(reserialized)

        reserialized["certified_reasoning_efforts"] = []
        reserialized["default_reasoning_effort"] = "high"
        with self.assertRaisesRegex(ValueError, "digest"):
            execution_binding_from_document(reserialized)


if __name__ == "__main__":
    unittest.main()
