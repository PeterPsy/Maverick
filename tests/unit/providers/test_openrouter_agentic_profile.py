from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from unittest import mock
import unittest

from core.api.platform_state import bootstrap_platform_state
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.providers.openrouter_agentic_certification import (
    OPENROUTER_CERTIFICATION_VALIDITY_DAYS,
)
from core.providers.openrouter_agentic_profile import (
    OPENROUTER_AGENTIC_PROFILE_ID,
    OPENROUTER_AGENTIC_PREVIOUS_PROFILE_REVISIONS,
    OPENROUTER_AGENTIC_PROFILE_REVISION,
    ensure_openrouter_agentic_preview_profile,
)
from core.providers.agentic_models import AgenticProfileDefinitionStatus
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 17, tzinfo=UTC)


class OpenRouterAgenticProfileTest(unittest.TestCase):
    def test_bootstrap_publishes_exact_expiring_unbound_preview(self) -> None:
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
            OPENROUTER_AGENTIC_PROFILE_ID,
            OPENROUTER_AGENTIC_PROFILE_REVISION,
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
        self.assertEqual(profile.adapter_version_constraint, "==3")
        self.assertEqual(profile.model_provider_id, "openrouter")
        self.assertEqual(profile.model_id, "deepseek/deepseek-v4-flash")
        self.assertEqual(profile.provider_protocol, "openrouter-chat-completions")
        routing = profile.routing_constraint
        self.assertEqual(routing.allowed_upstream_ids, ("deepinfra/fp8",))
        self.assertFalse(routing.allow_fallbacks)
        self.assertTrue(routing.require_parameters)
        self.assertEqual(routing.data_collection_policy, "deny")
        self.assertTrue(routing.require_zdr)
        self.assertEqual(routing.allowed_quantizations, ("fp8",))
        self.assertEqual(certificate.certified_upstream_ids, ("deepinfra/fp8",))
        self.assertEqual(
            certificate.expires_at,
            NOW + timedelta(days=OPENROUTER_CERTIFICATION_VALIDITY_DAYS),
        )
        self.assertEqual(
            certificate.adapter_artifact_digest,
            runtime_adapter_artifact_digest(adapter),
        )
        self.assertEqual(certificate.suite_version, "2")
        self.assertFalse(
            any(
                binding.definition_id == profile.definition_id
                for binding in state.provider_store.list_workspace_agentic_profile_bindings("default")
            )
        )

        previous_revision = OPENROUTER_AGENTIC_PREVIOUS_PROFILE_REVISIONS[-1]
        state.provider_store.save_agentic_profile_definition_status(
            AgenticProfileDefinitionStatus(
                definition_id=OPENROUTER_AGENTIC_PROFILE_ID,
                definition_revision=previous_revision,
                rollout_status="preview",
                revision=0,
                updated_at=NOW,
            ),
            expected_revision=None,
        )
        ensure_openrouter_agentic_preview_profile(
            state.provider_store,
            adapter=adapter,
            now=NOW + timedelta(seconds=1),
        )
        previous = state.provider_store.get_agentic_profile_definition_status(
            OPENROUTER_AGENTIC_PROFILE_ID,
            previous_revision,
        )
        self.assertEqual(previous.rollout_status, "suspended")
        self.assertEqual(previous.revision, 1)


if __name__ == "__main__":
    unittest.main()
