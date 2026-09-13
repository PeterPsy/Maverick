"""Native continuation accepts only authentic compatible connection history."""

from contextlib import closing
from dataclasses import replace
from datetime import timedelta
import os
import sqlite3
import unittest
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.providers.agentic_profiles import CODEX_PROFILE_REVISION
from core.providers.certificate_service import (
    build_capability_evidence,
    publish_capability_certificate,
)
from core.providers.native_agent_certificates import (
    connection_certificate_for_projection,
    native_connection_identity_digest,
    native_installation_for_adapter,
    validate_native_connection_certificate_for_continuation_source,
)
from core.providers.native_runtime_certificates import ensure_native_runtime_certificate
from core.providers.errors import CapabilityCertificateError
from core.recovery.continuation_admission import assess_runtime_session_admission
from core.recovery.continuation_fork import admit_runtime_session
from core.runtime.execution_binding import canonical_digest
from core.runtime.errors import RuntimeProfileUpgradeRequiredError
from tests.support.continuation import NOW, RuntimeContinuationFixture


class NativeContinuationIdentityTest(RuntimeContinuationFixture, unittest.TestCase):
    def _install_historical_projection(self):
        store = self.state.provider_store
        adapter = self.state.provider_registry.get_agentic_runtime_adapter("codex")
        installation = native_installation_for_adapter(adapter)
        codex_binding = next(
            binding
            for binding in store.list_workspace_agentic_profile_bindings("default")
            if binding.enabled
            and store.get_agentic_profile_definition(
                binding.definition_id,
                binding.definition_revision,
            ).runtime_engine_id
            == "codex"
        )
        definition = store.get_agentic_profile_definition(
            codex_binding.definition_id,
            codex_binding.definition_revision,
        )
        projection = store.get_capability_certificate(
            definition.capability_certificate_id
        )
        current_root = connection_certificate_for_projection(store, projection)
        historical_root_id = "native-connection:codex:codex:historical-test"
        historical_artifact_digest = "2" * 64
        references = tuple(
            (
                model_provider_id,
                historical_root_id
                if model_provider_id == projection.model_provider_id
                else certificate_id,
            )
            for model_provider_id, certificate_id in (
                installation.certificate.connection_certificate_ids
            )
        )
        historical_installation = replace(
            installation,
            certificate=replace(
                installation.certificate,
                connection_certificate_ids=references,
            ),
        )
        historical_identity = native_connection_identity_digest(
            historical_installation,
            model_provider_id=projection.model_provider_id,
            artifact_digest=historical_artifact_digest,
        )
        historical_test_run_id = "packaged:historical-continuation-test"
        evidence = build_capability_evidence(
            suite_id=current_root.suite_id,
            suite_version=current_root.suite_version,
            test_run_id=historical_test_run_id,
            adapter_artifact_digest=historical_artifact_digest,
            result_summary_digest=canonical_digest(
                {"native_connection_identity_digest": historical_identity}
            ),
            evidence_refs=current_root.evidence_refs,
            recorded_at=NOW,
        )
        historical_root = replace(
            current_root,
            certificate_id=historical_root_id,
            adapter_artifact_digest=historical_artifact_digest,
            native_connection_identity_digest=historical_identity,
            legacy_projection_certificate_ids=(),
            test_run_id=historical_test_run_id,
            evidence_digest=evidence.evidence_digest,
            issued_at=NOW,
        )
        historical_root = publish_capability_certificate(
            store,
            certificate=historical_root,
            evidence=evidence,
        )
        historical_projection = publish_capability_certificate(
            store,
            certificate=replace(
                projection,
                certificate_id="historical-model-projection",
                adapter_artifact_digest=historical_artifact_digest,
                native_connection_certificate_id=historical_root.certificate_id,
                native_connection_identity_digest=historical_identity,
                test_run_id=historical_test_run_id,
                evidence_digest=evidence.evidence_digest,
                issued_at=NOW,
            ),
            evidence=evidence,
        )

        with patch.object(
            historical_installation.inspector,
            "artifact",
            return_value=historical_installation.runtime_artifact,
        ):
            ensure_native_runtime_certificate(
                store,
                historical_root,
                historical_installation,
            )

        return historical_projection, historical_root, installation, codex_binding

    def test_previous_artifact_with_same_connection_contract_is_valid_history(self):
        historical_projection, historical_root, installation, _codex_binding = (
            self._install_historical_projection()
        )

        with patch.object(
            installation.inspector,
            "artifact",
            return_value=installation.runtime_artifact,
        ):
            validated = (
                validate_native_connection_certificate_for_continuation_source(
                    self.state.provider_store,
                    historical_projection,
                    installation=installation,
                    now=NOW,
                )
            )

        self.assertEqual(validated, historical_root)
        incompatible_installation = replace(
            installation,
            effects=replace(
                installation.effects,
                sandbox_policy_revision="incompatible-sandbox-policy",
            ),
        )
        with self.assertRaisesRegex(
            CapabilityCertificateError,
            "native_agent_connection_identity_mismatch",
        ):
            validate_native_connection_certificate_for_continuation_source(
                self.state.provider_store,
                historical_projection,
                installation=incompatible_installation,
                now=NOW,
            )

    def test_authentic_previous_connection_can_enter_audited_continuation(self):
        historical_projection, _historical_root, installation, codex = (
            self._install_historical_projection()
        )
        store = self.state.provider_store
        source = self._source_session(
            "authentic-native-history",
            target_workspace_binding_id=codex.binding_id,
            source_certificate=historical_projection,
        )

        with patch.object(
            installation.inspector,
            "artifact",
            return_value=installation.runtime_artifact,
        ):
            assessment = assess_runtime_session_admission(
                store,
                self.state.runtime_store,
                self.state.provider_registry,
                session=source,
                target_session_id="authentic-native-successor",
                now=NOW,
            )

            continuation = admit_runtime_session(
                self.state,
                session=source,
                now=NOW,
            )

        self.assertEqual(assessment.status, "compatible_upgrade")
        self.assertEqual(assessment.detail_code, "adapter_artifact_mismatch")
        self.assertEqual(continuation.status, "forked")
        self.assertEqual(
            continuation.session.predecessor_session_id,
            source.session_id,
        )

    def test_backend_bootstrap_upgrades_chat_after_certified_codex_rollout(self):
        historical_projection, _historical_root, installation, codex = (
            self._install_historical_projection()
        )
        source = self._source_session(
            "automatic-native-history",
            target_workspace_binding_id=codex.binding_id,
            source_certificate=historical_projection,
        )
        codex_home = (
            self.root
            / "workspaces"
            / "default"
            / "runtime"
            / "sessions"
            / source.session_id
            / "codex-home"
        )
        rollout = codex_home / "sessions" / "rollout.jsonl"
        rollout.parent.mkdir(parents=True)
        rollout.write_text('{"event":"preserved"}\n', encoding="utf-8")
        with closing(sqlite3.connect(codex_home / "state_5.sqlite")) as connection:
            connection.execute("CREATE TABLE provider_state (value TEXT)")
            connection.execute("INSERT INTO provider_state VALUES ('preserved')")
            connection.commit()

        with (
            patch.dict(
                os.environ,
                {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
                clear=False,
            ),
            patch.object(
                installation.inspector,
                "artifact",
                return_value=installation.runtime_artifact,
            ),
        ):
            restarted = bootstrap_platform_state(
                start_path=self.root,
                now=NOW + timedelta(seconds=1),
                install_builtin_apps=False,
            )

        thread = restarted.runtime_store.get_thread(source.session_id)
        self.assertNotEqual(thread.runtime_session_id, source.session_id)
        successor = restarted.runtime_store.get_session(thread.runtime_session_id)
        self.assertEqual(successor.predecessor_session_id, source.session_id)
        self.assertEqual(
            successor.execution_binding.profile_definition_revision.split(".", 1)[0],
            CODEX_PROFILE_REVISION,
        )
        snapshots = list((self.root / "data" / "recovery-snapshots").iterdir())
        self.assertEqual(len(snapshots), 1)

        with patch.dict(
            os.environ,
            {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
            clear=False,
        ):
            converged = bootstrap_platform_state(
                start_path=self.root,
                now=NOW + timedelta(seconds=2),
                install_builtin_apps=False,
            )

        self.assertEqual(
            converged.runtime_store.get_thread(source.session_id).runtime_session_id,
            successor.session_id,
        )
        self.assertEqual(
            len(list((self.root / "data" / "recovery-snapshots").iterdir())),
            1,
        )

    def test_changed_codex_artifact_cannot_borrow_current_connection_authority(self):
        store = self.state.provider_store
        codex = next(
            binding for binding in store.list_workspace_agentic_profile_bindings("default")
            if binding.enabled and store.get_agentic_profile_definition(
                binding.definition_id, binding.definition_revision,
            ).runtime_engine_id == "codex"
        )
        definition = store.get_agentic_profile_definition(codex.definition_id, codex.definition_revision)
        certificate = store.get_capability_certificate(definition.capability_certificate_id)
        evidence = store.get_capability_evidence(certificate.evidence_digest)
        for label, options in (("artifact", {}), ("model", {"source_model_id": "different-model"}),
                               ("routing", {"routing_mismatch": True})):
            with self.subTest(label=label):
                source = self._source_session(
                    f"native-source-{label}", target_workspace_binding_id=codex.binding_id, **options,
                )
                provider_state = self.state.runtime_store.get_provider_state(source.session_id)
                assessment = assess_runtime_session_admission(
                    store, self.state.runtime_store, self.state.provider_registry,
                    session=source, target_session_id=f"native-target-{label}", now=NOW,
                )
                self.assertEqual(assessment.status, "upgrade_required")
                self.assertEqual(assessment.detail_code, "native_agent_connection_identity_mismatch")
                with self.assertRaises(RuntimeProfileUpgradeRequiredError):
                    admit_runtime_session(self.state, session=source, now=NOW)
                self.assertEqual(self.state.runtime_store.get_session(source.session_id), source)
                self.assertEqual(self.state.runtime_store.get_provider_state(source.session_id), provider_state)
                self.assertIsNone(self.state.runtime_store.get_continuation_handoff_by_predecessor(
                    workspace_id="default", predecessor_session_id=source.session_id,
                ))
        self.assertEqual(store.get_workspace_agentic_profile_binding(codex.binding_id), codex)
        self.assertEqual(store.get_capability_certificate(certificate.certificate_id), certificate)
        self.assertEqual(store.get_capability_evidence(evidence.evidence_digest), evidence)


if __name__ == "__main__":
    unittest.main()
