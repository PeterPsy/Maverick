from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from types import SimpleNamespace
from unittest import mock
import unittest

from core.api.platform_state import bootstrap_platform_state
from core.providers.agentic_models import AgenticProfileDefinitionStatus
from core.providers.google_agentic_profile import (
    GOOGLE_AGENTIC_PREVIOUS_PROFILE_REVISION,
    GOOGLE_AGENTIC_PROFILE_ID,
    GOOGLE_AGENTIC_PROFILE_REVISION,
    GOOGLE_DEFAULT_REASONING_EFFORT,
    GOOGLE_REASONING_EFFORTS,
    ensure_google_agentic_preview_profile,
)
from core.providers.google_interactions_client import GOOGLE_AGENTIC_MODEL_REVISION
from core.providers.maverick_agent_builtins import (
    GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
    GOOGLE_INTERACTIONS_PROVIDER_CONFIG,
)
from core.runtime.full_workspace_contract import (
    FULL_WORKSPACE_CONTRACT_REVISION,
    FULL_WORKSPACE_CORE_TOOL_HANDLES,
    MAVERICK_AGENT_EXECUTION_FAMILY,
)
from core.runtime.hosted_harness_recipes import GOOGLE_GOVERNED_WORKSPACE_RECIPE
from core.runtime.hosted_agentic_factory import classify_hosted_content_fail_closed
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 16, tzinfo=UTC)


class GoogleAgenticProfileTest(unittest.TestCase):
    def test_bootstrap_publishes_direct_unbound_full_workspace_preview(self) -> None:
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
        adapter = state.provider_registry.get_agentic_runtime_adapter(
            profile.runtime_engine_id
        )
        production_classification = adapter.loop.request_builder.classifier(
            SimpleNamespace(
                session=SimpleNamespace(session_id="production-session"),
                correlation_id="production-turn",
            ),
            "user_input",
            "ordinary production prompt",
        )

        self.assertEqual(status.rollout_status, "preview")
        self.assertEqual(profile.revision, "70")
        self.assertEqual(profile.adapter_version_constraint, "==59")
        self.assertEqual(profile.model_id, "gemini-3.6-flash")
        self.assertEqual(profile.model_revision, GOOGLE_AGENTIC_MODEL_REVISION)
        self.assertEqual(profile.model_revision_policy, "exact")
        self.assertEqual(profile.provider_api_version, "v1")
        self.assertEqual(profile.reasoning_efforts, GOOGLE_REASONING_EFFORTS)
        self.assertEqual(
            profile.default_reasoning_effort,
            GOOGLE_DEFAULT_REASONING_EFFORT,
        )
        self.assertTrue(profile.capabilities.tool_orchestration)
        self.assertTrue(profile.capabilities.cli)
        self.assertTrue(profile.capabilities.mcp)
        self.assertTrue(profile.capabilities.filesystem_write)
        self.assertEqual(
            (
                profile.provider_config_id,
                profile.provider_config_revision,
                profile.provider_config_digest,
            ),
            (
                GOOGLE_INTERACTIONS_PROVIDER_CONFIG.config_id,
                GOOGLE_INTERACTIONS_PROVIDER_CONFIG.revision,
                GOOGLE_INTERACTIONS_PROVIDER_CONFIG.digest,
            ),
        )
        self.assertEqual(
            (profile.protocol_adapter_id, profile.protocol_adapter_version),
            (
                GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER.protocol_adapter_id,
                GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER.protocol_adapter_version,
            ),
        )
        self.assertEqual(profile.policy_ceiling.allowed_remote_data_classes, ("public",))
        self.assertEqual(production_classification.data_class, "unclassified")
        self.assertIsNone(production_classification.classification_revision)
        self.assertEqual(profile.egress_policy_id, "remote-agentic-contained")
        self.assertEqual(profile.egress_policy_revision, "2")
        self.assertEqual(
            profile.full_workspace_contract_revision,
            FULL_WORKSPACE_CONTRACT_REVISION,
        )
        self.assertEqual(profile.execution_family, MAVERICK_AGENT_EXECUTION_FAMILY)
        self.assertEqual(
            profile.harness_recipe_id,
            GOOGLE_GOVERNED_WORKSPACE_RECIPE.recipe_id,
        )
        self.assertEqual(
            profile.harness_recipe_digest,
            GOOGLE_GOVERNED_WORKSPACE_RECIPE.recipe_digest,
        )
        self.assertEqual(
            profile.context_policy,
            GOOGLE_GOVERNED_WORKSPACE_RECIPE.context_policy,
        )
        self.assertEqual(
            profile.policy_ceiling.allowed_tool_handles,
            FULL_WORKSPACE_CORE_TOOL_HANDLES,
        )
        self.assertFalse(
            any(
                binding.definition_id == profile.definition_id
                for binding in state.provider_store.list_workspace_agentic_profile_bindings(
                    "default"
                )
            )
        )

        google = state.provider_registry.get_provider_definition("google-ai-studio")
        model = next(
            option for option in google.model_options if option.model_id == profile.model_id
        )
        self.assertEqual(model.metadata["lifecycle"], "stable")
        self.assertEqual(model.metadata["protocol"], "google-interactions")

        state.provider_store.save_agentic_profile_definition_status(
            AgenticProfileDefinitionStatus(
                definition_id=GOOGLE_AGENTIC_PROFILE_ID,
                definition_revision=GOOGLE_AGENTIC_PREVIOUS_PROFILE_REVISION,
                rollout_status="preview",
                revision=0,
                updated_at=NOW,
            ),
            expected_revision=None,
        )
        ensure_google_agentic_preview_profile(
            state.provider_store,
            adapter=adapter,
            now=NOW + timedelta(seconds=1),
        )
        previous = state.provider_store.get_agentic_profile_definition_status(
            GOOGLE_AGENTIC_PROFILE_ID,
            GOOGLE_AGENTIC_PREVIOUS_PROFILE_REVISION,
        )
        self.assertEqual(previous.rollout_status, "suspended")
        self.assertEqual(previous.revision, 1)

    def test_explicit_fail_closed_classifier_never_assumes_data_is_fake(self) -> None:
        self.assertEqual(
            classify_hosted_content_fail_closed(
                None,
                "user_input",
                "synthetic-looking text",
            ).data_class,
            "unclassified",
        )
        self.assertEqual(
            classify_hosted_content_fail_closed(
                None,
                "tool_result",
                {"value": 4},
            ).data_class,
            "unclassified",
        )
        self.assertEqual(
            classify_hosted_content_fail_closed(None, "tool_schema", {}).data_class,
            "unclassified",
        )

    def test_classifier_ignores_persisted_legacy_declaration(self) -> None:
        context = SimpleNamespace(
            session=SimpleNamespace(declared_remote_data_class="legacy-non-authoritative")
        )
        self.assertEqual(
            classify_hosted_content_fail_closed(
                context,
                "user_input",
                "fixture",
            ).data_class,
            "unclassified",
        )
        self.assertEqual(
            classify_hosted_content_fail_closed(
                context,
                "tool_result",
                {"fixture": True},
            ).data_class,
            "unclassified",
        )


if __name__ == "__main__":
    unittest.main()
