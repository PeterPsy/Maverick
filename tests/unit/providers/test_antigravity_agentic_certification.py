"""Connection-scoped certification and activation for Antigravity."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.providers.antigravity_agentic_certification import (
    ANTIGRAVITY_CERTIFICATION_SUITE_ID,
    ANTIGRAVITY_CERTIFICATION_SUITE_VERSION,
    publish_antigravity_connection_certificate,
)
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.providers.certification_pipeline import (
    execute_certification_suite,
    sign_certification_run,
)
from core.providers.errors import ProviderCapabilityError
from core.providers.native_agent_builtins import (
    ANTIGRAVITY_NATIVE_CONNECTION_CERTIFICATE_ID,
)
from core.providers.native_agent_reconciliation import (
    refresh_antigravity_native_catalog,
)
from core.providers.native_agent_status import native_agent_status_items
from core.providers.service import (
    activate_native_agent_provider,
    builtin_provider_registry,
    effective_provider_registry,
)
from tests.support.certification_evidence import (
    fixture_step_process,
    with_fixture_behavior,
)
from tests.support.maverick_agent_onboarding import provider_store
from tests.support.native_agent_catalog import antigravity_snapshot


ROOT = Path(__file__).resolve().parents[3]
SOURCE_COMMIT = "7" * 40


class AntigravityAgenticCertificationTest(unittest.TestCase):
    def setUp(self):
        self.store = provider_store()
        with patch(
            "core.providers.native_agent_reconciliation.discover_codex_native_catalog",
            return_value=None,
        ), patch(
            "core.providers.native_agent_reconciliation.discover_antigravity_native_catalog",
            return_value=None,
        ):
            self.registry = effective_provider_registry(
                self.store,
                registry=builtin_provider_registry(),
            )
        self.controller = self.registry.get_native_agent_controller(
            "antigravity-cli"
        )
        self.snapshot = antigravity_snapshot(
            "gemini-3.6-flash-high",
            "claude-sonnet-4-6",
        )

    def signed_run(self):
        with patch(
            "core.providers.certification_pipeline._require_clean_checkout"
        ), patch(
            "core.providers.certification_pipeline._git_commit",
            return_value=SOURCE_COMMIT,
        ), patch(
            "core.providers.certification_pipeline.subprocess.run",
            side_effect=fixture_step_process,
        ):
            run = execute_certification_suite(
                cwd=ROOT,
                suite_id=ANTIGRAVITY_CERTIFICATION_SUITE_ID,
                suite_version=ANTIGRAVITY_CERTIFICATION_SUITE_VERSION,
                adapter_artifact_digest=runtime_adapter_artifact_digest(
                    self.controller
                ),
                evidence_refs=("platform-evidence:test-antigravity-native",),
                started_at=datetime(2026, 9, 9, tzinfo=UTC),
            )
            run = with_fixture_behavior(run)
        private_key = Ed25519PrivateKey.generate()
        signed = sign_certification_run(
            run,
            signer_key_id="test-trusted-key",
            private_key=private_key,
            cwd=ROOT,
        )
        return signed, {"test-trusted-key": private_key.public_key()}

    def publish_root(self):
        signed, trusted = self.signed_run()
        installation = self.controller.installation
        with patch(
            "core.providers.certification_pipeline._git_commit",
            return_value=SOURCE_COMMIT,
        ), patch.object(
            installation.inspector,
            "artifact",
            return_value=installation.runtime_artifact,
        ):
            return publish_antigravity_connection_certificate(
                self.store,
                adapter=self.controller,
                signed_run=signed,
                trusted_keys=trusted,
            )

    def refresh(self, snapshot=None):
        with patch(
            "core.providers.native_agent_reconciliation.discover_antigravity_native_catalog",
            return_value=snapshot or self.snapshot,
        ), patch.object(
            self.controller.installation.inspector,
            "artifact",
            return_value=self.controller.installation.runtime_artifact,
        ):
            return refresh_antigravity_native_catalog(
                self.registry,
                store=self.store,
                force=True,
            )

    def test_candidate_declares_authority_pointer_but_missing_root_stays_disabled(self):
        installation = self.controller.installation

        self.assertTrue(installation.certification_configured)
        self.assertEqual(
            dict(installation.certificate.connection_certificate_ids),
            {"google": ANTIGRAVITY_NATIVE_CONNECTION_CERTIFICATE_ID},
        )
        self.refresh()
        self.assertFalse(
            any(
                profile.runtime_engine_id == "antigravity-cli"
                for profile in self.store.list_agentic_profile_definitions()
            )
        )
        with self.assertRaises(ProviderCapabilityError):
            activate_native_agent_provider(
                self.store,
                provider_id="antigravity-cli",
                registry=self.registry,
            )
        status = next(
            item
            for item in native_agent_status_items(
                self.registry,
                store=self.store,
            )
            if item["runtime_engine_id"] == "antigravity-cli"
        )
        self.assertFalse(status["selectable"])

    def test_trusted_root_projects_catalog_then_allows_explicit_activation(self):
        root = self.publish_root()
        self.assertEqual(root.certificate_scope, "native_connection")
        self.assertEqual(
            root.certificate_id,
            ANTIGRAVITY_NATIVE_CONNECTION_CERTIFICATE_ID,
        )
        self.assertEqual(len(root.certification_target_digest), 64)

        self.refresh()
        profiles = [
            profile
            for profile in self.store.list_agentic_profile_definitions()
            if profile.runtime_engine_id == "antigravity-cli"
        ]
        self.assertEqual(len(profiles), 2)
        for profile in profiles:
            projection = self.store.get_capability_certificate(
                profile.capability_certificate_id
            )
            self.assertEqual(
                projection.native_connection_certificate_id,
                root.certificate_id,
            )
            self.assertEqual(
                projection.native_model_catalog_digest,
                profile.native_model_catalog_digest,
            )
        self.assertEqual(
            self.registry.get_provider_definition("antigravity-cli").status,
            "disabled",
        )
        direct = self.registry.register_provider_definition(
            replace(
                self.registry.get_provider_definition("antigravity-cli"),
                status="active",
            )
        )
        self.assertEqual(direct.status, "disabled")

        with patch(
            "core.providers.native_agent_reconciliation.discover_antigravity_native_catalog",
            return_value=self.snapshot,
        ), patch(
            "core.providers.native_agent_reconciliation.discover_codex_native_catalog",
            return_value=None,
        ), patch.object(
            self.controller.installation.inspector,
            "artifact",
            return_value=self.controller.installation.runtime_artifact,
        ):
            activated = activate_native_agent_provider(
                self.store,
                provider_id="antigravity-cli",
                registry=self.registry,
        )
        self.assertEqual(activated.definition.status, "active")
        self.assertEqual(activated.profile_count, 2)

        with patch(
            "core.providers.native_agent_reconciliation."
            "discover_antigravity_native_catalog",
            return_value=None,
        ):
            self.assertFalse(
                refresh_antigravity_native_catalog(
                    self.registry,
                    store=self.store,
                    force=True,
                )
            )
        self.assertEqual(
            self.registry.get_provider_definition(
                "antigravity-cli"
            ).status,
            "disabled",
        )
        self.assertEqual(
            self.store.get_provider_definition("antigravity-cli").status,
            "disabled",
        )

        with patch(
            "core.providers.native_agent_reconciliation."
            "discover_antigravity_native_catalog",
            return_value=self.snapshot,
        ), patch(
            "core.providers.native_agent_reconciliation.discover_codex_native_catalog",
            return_value=None,
        ), patch.object(
            self.controller.installation.inspector,
            "artifact",
            return_value=self.controller.installation.runtime_artifact,
        ):
            activated = activate_native_agent_provider(
                self.store,
                provider_id="antigravity-cli",
                registry=self.registry,
            )
        self.assertEqual(activated.definition.status, "active")

        removed = next(
            profile
            for profile in profiles
            if profile.model_id == "claude-sonnet-4-6"
        )
        self.refresh(antigravity_snapshot("gemini-3.6-flash-high"))
        removed_status = self.store.get_agentic_profile_definition_status(
            removed.definition_id,
            removed.revision,
        )
        self.assertEqual(removed_status.rollout_status, "preview")

        with patch(
            "core.providers.native_agent_reconciliation.discover_antigravity_native_catalog",
            return_value=antigravity_snapshot("gemini-3.6-flash-high"),
        ), patch(
            "core.providers.native_agent_reconciliation.discover_codex_native_catalog",
            return_value=None,
        ), patch.object(
            self.controller.installation.inspector,
            "artifact",
            return_value=self.controller.installation.runtime_artifact,
        ):
            activated = activate_native_agent_provider(
                self.store,
                provider_id="antigravity-cli",
                registry=self.registry,
            )
        self.assertEqual(activated.profile_count, 1)

        current = next(
            profile
            for profile in profiles
            if profile.model_id == "gemini-3.6-flash-high"
        )
        self.refresh(
            antigravity_snapshot(
                "gemini-3.6-flash-high",
                revision="provider-revision-2",
            )
        )
        current_status = self.store.get_agentic_profile_definition_status(
            current.definition_id,
            current.revision,
        )
        self.assertEqual(current_status.rollout_status, "suspended")


if __name__ == "__main__":
    unittest.main()
