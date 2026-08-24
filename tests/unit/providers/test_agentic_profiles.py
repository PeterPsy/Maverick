from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.agentic_models import AgenticProfileDefinitionStatus
from core.providers.agentic_migration import migrate_agentic_runtime_schema
from core.providers.agentic_profiles import (
    _validated_reasoning_effort,
    build_pinned_execution_binding,
    ensure_codex_workspace_profile,
)
from core.providers.errors import (
    AgenticProfileConflictError,
    AgenticProfileError,
    CapabilityCertificateError,
)
from core.providers.certificate_service import validate_certificate_for_binding
from core.providers.certificate_projection import certificate_profile_status
from core.providers.builtin_certification import ensure_codex_preview_certificate
from core.providers.agentic_workspace_policy import egress_policy_for_definition
from core.providers.models import ProviderSelection
from core.providers.service import builtin_provider_registry, resolve_provider_for_runtime_session
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.runtime.errors import RuntimeProviderStateError
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection


NOW = datetime(2026, 8, 16, tzinfo=UTC)


class AgenticProfilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider_collections = ProviderCollections(
            definitions=FakeCollection(),
            bindings=FakeCollection(),
            selections=FakeCollection(),
            agentic_profile_definitions=FakeCollection(),
            agentic_profile_definition_statuses=FakeCollection(),
            workspace_agentic_profile_bindings=FakeCollection(),
            agentic_migrations=FakeCollection(),
        )
        self.provider_store = ProviderDocumentStore(self.provider_collections)
        self.registry = builtin_provider_registry()
        self.codex = self.registry.get_provider_definition("codex")

    def selection(self, *, model_id: str = "gpt-5.6-sol") -> ProviderSelection:
        return ProviderSelection(
            selection_id="default:codex",
            workspace_id="default",
            provider_id="codex",
            binding_id=None,
            selection_scope="workspace_default",
            selection_reason="test",
            created_at=NOW,
            updated_at=NOW,
            model_id=model_id,
            model_reasoning_effort="high",
        )

    def test_definition_is_installation_scoped_and_workspace_state_is_separate(self) -> None:
        profile, binding = ensure_codex_workspace_profile(
            self.provider_store,
            definition=self.codex,
            selection=self.selection(),
            now=NOW,
        )

        self.assertNotIn("workspace_id", asdict(profile))
        self.assertNotIn("credential_binding_id", asdict(profile))
        self.assertEqual(binding.workspace_id, "default")
        self.assertEqual(binding.definition_id, profile.definition_id)

    def test_workspace_binding_compare_and_set_rejects_stale_revision(self) -> None:
        _profile, binding = ensure_codex_workspace_profile(
            self.provider_store,
            definition=self.codex,
            selection=self.selection(),
            now=NOW,
        )
        updated = replace(binding, enabled=False, revision=1)
        self.provider_store.save_workspace_agentic_profile_binding(updated, expected_revision=0)

        with self.assertRaises(AgenticProfileConflictError):
            self.provider_store.save_workspace_agentic_profile_binding(
                replace(updated, enabled=True, revision=1),
                expected_revision=0,
            )

    def test_session_resolution_remains_pinned_after_workspace_default_changes(self) -> None:
        original = self.selection(model_id="gpt-5.6-sol")
        self.provider_store.save_provider_selection(original)
        profile, _ = ensure_codex_workspace_profile(
            self.provider_store,
            definition=self.codex,
            selection=original,
            now=NOW,
        )
        ensure_codex_preview_certificate(
            self.provider_store,
            definition=profile,
            provider_definition=self.codex,
            adapter=self.registry.get_agentic_runtime_adapter("codex"),
        )
        binding = build_pinned_execution_binding(
            self.provider_store,
            self.registry,
            session_id="session-a",
            workspace_id="default",
            execution_mode="full-access",
            now=NOW,
        )
        self.assertEqual(binding.reasoning_effort, binding.default_reasoning_effort)
        self.assertIn(binding.reasoning_effort, binding.certified_reasoning_efforts)
        changed = replace(original, model_id="gpt-5.6-mini", updated_at=replace_time(NOW))
        self.provider_store.save_provider_selection(changed)
        ensure_codex_workspace_profile(
            self.provider_store,
            definition=self.codex,
            selection=changed,
            now=replace_time(NOW),
        )
        session = runtime_session(execution_binding=binding)

        _definition, selection = resolve_provider_for_runtime_session(
            self.provider_store,
            session=session,
            registry=self.registry,
        )

        self.assertEqual(selection.model_id if selection else None, "gpt-5.6-sol")
        self.assertEqual(session.execution_binding.binding_digest, binding.binding_digest)

    def test_definition_egress_metadata_is_not_inferred_from_engine_id(self) -> None:
        profile, _binding = ensure_codex_workspace_profile(
            self.provider_store,
            definition=self.codex,
            selection=self.selection(),
            now=NOW,
        )

        future_local_engine = replace(profile, runtime_engine_id="future-local-runtime")

        self.assertEqual(
            egress_policy_for_definition(future_local_engine),
            ("local-runtime-no-remote-egress", "1"),
        )

    def test_generic_pinning_does_not_auto_issue_codex_certificate(self) -> None:
        ensure_codex_workspace_profile(
            self.provider_store,
            definition=self.codex,
            selection=self.selection(),
            now=NOW,
        )

        with self.assertRaisesRegex(CapabilityCertificateError, "certificate_missing"):
            build_pinned_execution_binding(
                self.provider_store,
                self.registry,
                session_id="session-without-published-certificate",
                workspace_id="default",
                execution_mode="full-access",
                now=NOW,
            )

    def test_remote_reasoning_is_validated_against_the_certificate(self) -> None:
        profile = SimpleNamespace(
            definition_id="profile-google",
            revision="1",
            runtime_engine_id="maverick-tool-loop",
            model_provider_id="google-ai-studio",
            model_id="gemini-3.6-flash",
            provider_protocol="google-interactions",
            provider_api_version="v1",
            adapter_id="maverick-hosted-tool-loop",
            adapter_version_constraint="==3",
            routing_constraint=SimpleNamespace(),
            policy_ceiling=SimpleNamespace(),
            capability_certificate_id="certificate-google",
        )
        binding = SimpleNamespace(
            binding_id="binding-google",
            workspace_id="default",
            credential_binding_id="credential-google",
            workspace_policy_ceiling=SimpleNamespace(),
            egress_policy_id="fake-data-remote-preview",
            egress_policy_revision="1",
            revision=0,
            created_at=NOW,
        )
        adapter = SimpleNamespace(adapter_version="3")
        expected = object()

        with (
            patch(
                "core.providers.agentic_profiles.resolve_workspace_agentic_profile",
                return_value=(profile, binding),
            ),
            patch.object(
                self.registry,
                "get_agentic_runtime_adapter",
                return_value=adapter,
            ),
            patch.object(
                self.provider_store,
                "get_capability_certificate",
                return_value=SimpleNamespace(
                    evidence_digest="evidence-google",
                    certified_reasoning_efforts=("minimal", "low", "medium", "high"),
                    default_reasoning_effort="high",
                ),
            ),
            patch(
                "core.providers.agentic_profiles.runtime_adapter_artifact_digest",
                return_value="adapter-digest",
            ),
            patch(
                "core.providers.agentic_profiles.build_runtime_execution_binding",
                return_value=expected,
            ) as build_binding,
            patch("core.providers.agentic_profiles.validate_certificate_for_binding"),
        ):
            resolved = build_pinned_execution_binding(
                self.provider_store,
                self.registry,
                session_id="session-google",
                workspace_id="default",
                workspace_binding_id="binding-google",
                execution_mode="sandbox",
                reasoning_effort="high",
                now=NOW,
            )

        self.assertIs(resolved, expected)
        self.assertEqual(build_binding.call_args.kwargs["model_provider_id"], "google-ai-studio")
        self.assertEqual(build_binding.call_args.kwargs["reasoning_effort"], "high")
        self.assertEqual(
            build_binding.call_args.kwargs["certified_reasoning_efforts"],
            ("minimal", "low", "medium", "high"),
        )

    def test_reasoning_selection_uses_only_the_immutable_certificate_contract(self) -> None:
        certificate = SimpleNamespace(
            certified_reasoning_efforts=("low", "high"),
            default_reasoning_effort="high",
        )

        self.assertEqual(
            _validated_reasoning_effort(certificate, reasoning_effort=None),
            "high",
        )
        with self.assertRaisesRegex(AgenticProfileError, "profile_reasoning_effort_unsupported"):
            _validated_reasoning_effort(certificate, reasoning_effort="medium")

    def test_migration_is_idempotent_and_preserves_legacy_continuation(self) -> None:
        selection = self.selection()
        self.provider_store.save_provider_selection(selection)
        session_collection = FakeCollection()
        provider_states = FakeCollection()
        runtime_store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=session_collection,
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                provider_states=provider_states,
            )
        )
        legacy = runtime_session(execution_binding=None, provider_thread_id="legacy-thread")
        session_collection.update_one(
            {"session_id": legacy.session_id, "workspace_id": legacy.workspace_id},
            {"$set": asdict(legacy)},
            upsert=True,
        )

        first = migrate_agentic_runtime_schema(
            self.provider_store,
            runtime_store,
            self.registry,
            now=NOW,
        )
        second = migrate_agentic_runtime_schema(
            self.provider_store,
            runtime_store,
            self.registry,
            now=replace_time(NOW),
        )

        migrated = runtime_store.get_session("session-a")
        state = runtime_store.get_provider_state("session-a")
        self.assertTrue(migrated.execution_binding.legacy_inferred)
        self.assertEqual(migrated.execution_binding.reasoning_effort, "high")
        validate_certificate_for_binding(
            self.provider_store,
            binding=migrated.execution_binding,
            adapter=self.registry.get_agentic_runtime_adapter("codex"),
            now=NOW,
        )
        self.assertEqual(state.provider_thread_id, "legacy-thread")
        self.assertEqual(first.summary_digest, second.summary_digest)
        self.assertEqual(len(provider_states.documents), 1)
        with self.assertRaises(RuntimeProviderStateError):
            runtime_store.initialize_provider_state(replace(state, provider_thread_id="other"))

    def test_codex_profile_suspends_previous_revisions(self) -> None:
        selection = self.selection()
        profile, _binding = ensure_codex_workspace_profile(
            self.provider_store,
            definition=self.codex,
            selection=selection,
            now=NOW,
        )
        self.assertEqual(profile.revision, "6")

        for rev in ("1", "2", "3", "4", "5"):
            self.provider_store.save_agentic_profile_definition_status(
                AgenticProfileDefinitionStatus(
                    definition_id=profile.definition_id,
                    definition_revision=rev,
                    rollout_status="preview",
                    revision=0,
                    updated_at=NOW,
                ),
                expected_revision=None,
            )

        ensure_codex_workspace_profile(
            self.provider_store,
            definition=self.codex,
            selection=selection,
            now=replace_time(NOW),
        )

        for rev in ("1", "2", "3", "4", "5"):
            status = self.provider_store.get_agentic_profile_definition_status(
                profile.definition_id,
                rev,
            )
            self.assertIsNotNone(status)
            self.assertEqual(status.rollout_status, "suspended")

    def test_all_builtin_codex_models_have_active_certificates_matching_current_adapter(self) -> None:
        runtime_store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                provider_states=FakeCollection(),
            )
        )
        migrate_agentic_runtime_schema(
            self.provider_store,
            runtime_store,
            self.registry,
            now=NOW,
        )
        codex_adapter = self.registry.get_agentic_runtime_adapter("codex")
        self.assertTrue(len(self.codex.model_options) > 0)
        for model in self.codex.model_options:
            with self.subTest(model_id=model.model_id):
                profile = next(
                    item
                    for item in self.provider_store.list_agentic_profile_definitions()
                    if item.model_id == model.model_id and item.revision == "6"
                )
                self.assertEqual(profile.revision, "6")
                status = self.provider_store.get_agentic_profile_definition_status(
                    profile.definition_id,
                    profile.revision,
                )
                self.assertIsNotNone(status)
                self.assertEqual(status.rollout_status, "preview")
                certificate = self.provider_store.get_capability_certificate(
                    profile.capability_certificate_id
                )
                cert_status = self.provider_store.get_capability_certificate_status(
                    certificate.certificate_id
                )
                effective = certificate_profile_status(
                    certificate,
                    cert_status,
                    definition=profile,
                    adapter=codex_adapter,
                    now=NOW,
                )
                self.assertEqual(
                    effective,
                    "active",
                    f"Model {model.model_id} certificate status must be 'active' but was '{effective}'",
                )



def runtime_session(
    *,
    execution_binding,
    provider_thread_id: str | None = None,
) -> RuntimeSessionRecord:
    return RuntimeSessionRecord(
        session_id="session-a",
        workspace_id="default",
        agent_id="chat",
        status="running",
        requested_mode="full-access",
        effective_mode="full-access",
        workspace_root="/workspace",
        workdir="/workspace",
        runtime_root="/runtime/session-a",
        started_at=NOW,
        updated_at=NOW,
        ended_at=None,
        last_progress_at=NOW,
        execution_binding=execution_binding,
        provider_id="codex",
        provider_thread_id=provider_thread_id,
    )


def replace_time(value: datetime) -> datetime:
    return value.replace(second=value.second + 1)


if __name__ == "__main__":
    unittest.main()
