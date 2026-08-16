from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from unittest import mock
import unittest

from core.api.platform_state import bootstrap_platform_state
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.providers.google_agentic_certification import GOOGLE_CERTIFICATION_VALIDITY_DAYS
from core.providers.google_agentic_profile import (
    GOOGLE_AGENTIC_PROFILE_ID,
    GOOGLE_AGENTIC_PROFILE_REVISION,
)
from core.runtime.hosted_agentic_factory import classify_hosted_content_fail_closed
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 16, tzinfo=UTC)


class GoogleAgenticProfileTest(unittest.TestCase):
    def test_bootstrap_publishes_expiring_unbound_fake_data_preview(self) -> None:
        root = make_temp_repo_root(self)
        with mock.patch.dict(
            os.environ,
            {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
            clear=False,
        ):
            state = bootstrap_platform_state(
                start_path=root,
                now=NOW,
                install_builtin_apps=False,
            )

        profile = state.provider_store.get_agentic_profile_definition(
            GOOGLE_AGENTIC_PROFILE_ID,
            GOOGLE_AGENTIC_PROFILE_REVISION,
        )
        status = state.provider_store.get_agentic_profile_definition_status(
            profile.definition_id,
            profile.revision,
        )
        certificate = state.provider_store.get_capability_certificate(
            profile.capability_certificate_id
        )
        adapter = state.provider_registry.get_agentic_runtime_adapter(
            profile.runtime_engine_id
        )

        self.assertEqual(status.rollout_status, "preview")
        self.assertEqual(profile.model_id, "gemini-3.6-flash")
        self.assertEqual(profile.provider_api_version, "v1")
        self.assertEqual(profile.policy_ceiling.allowed_remote_data_classes, ("public", "workspace_internal_fake"))
        self.assertEqual(
            profile.policy_ceiling.allowed_tool_handles,
            ("core-capability:filesystem.read",),
        )
        self.assertEqual(
            certificate.expires_at,
            NOW + timedelta(days=GOOGLE_CERTIFICATION_VALIDITY_DAYS),
        )
        self.assertEqual(
            certificate.adapter_artifact_digest,
            runtime_adapter_artifact_digest(adapter),
        )
        self.assertTrue(certificate.certified_capabilities.provider_private_state)
        self.assertFalse(certificate.certified_capabilities.filesystem_write)
        self.assertFalse(
            any(
                binding.definition_id == profile.definition_id
                for binding in state.provider_store.list_workspace_agentic_profile_bindings("default")
            )
        )

        google = state.provider_registry.get_provider_definition("google-ai-studio")
        model = next(option for option in google.model_options if option.model_id == profile.model_id)
        self.assertEqual(model.metadata["lifecycle"], "stable")
        self.assertEqual(model.metadata["protocol"], "google-interactions")

    def test_default_classifier_never_assumes_user_or_tool_data_is_fake(self) -> None:
        self.assertEqual(
            classify_hosted_content_fail_closed("user_input", "synthetic-looking text").data_class,
            "unclassified",
        )
        self.assertEqual(
            classify_hosted_content_fail_closed("tool_result", {"value": 4}).data_class,
            "unclassified",
        )
        self.assertEqual(
            classify_hosted_content_fail_closed("tool_schema", {}).data_class,
            "public",
        )


if __name__ == "__main__":
    unittest.main()
