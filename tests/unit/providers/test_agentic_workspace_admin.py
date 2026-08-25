from __future__ import annotations

from datetime import UTC, datetime
import os
from unittest import mock
import unittest

from core.api.platform_state import bootstrap_platform_state
from core.providers.agentic_models import ActorSelectionPolicy
from core.providers.agentic_workspace_admin import (
    configure_workspace_agentic_default,
    save_workspace_agentic_binding,
)
from core.providers.agentic_workspace_policy import actor_selection_allowed
from core.providers.errors import AgenticProfileError
from core.providers.google_agentic_profile import (
    GOOGLE_AGENTIC_PROFILE_ID,
    GOOGLE_AGENTIC_PROFILE_REVISION,
)
from core.providers.provider_credentials import bind_provider_credential
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 16, tzinfo=UTC)


class AgenticWorkspaceAdminTest(unittest.TestCase):
    def setUp(self) -> None:
        root = make_temp_repo_root(self)
        with mock.patch.dict(
            os.environ,
            {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
            clear=False,
        ):
            self.state = bootstrap_platform_state(
                start_path=root,
                now=NOW,
                install_builtin_apps=False,
            )

    def test_remote_model_cannot_be_enabled_by_workspace_input_during_containment(self) -> None:
        credential = bind_provider_credential(
            self.state.provider_store,
            provider_id="google-ai-studio",
            workspace_id="default",
            secret_ref="platform:secrets/google-agentic-test",
            binding_id="google-agentic-test-binding",
            now=NOW,
        )
        actor_policy = ActorSelectionPolicy(
            allow_workspace_admins=True,
            allowed_user_ids=(),
            allowed_workspace_role_ids=("member",),
            allowed_agent_type_ids=(),
        )
        policy_patch = {
            "allowed_remote_data_classes": ["workspace_internal_fake"],
            "tool_access_enabled": False,
            "max_estimated_cost_microusd": 100_000,
        }

        with self.assertRaisesRegex(AgenticProfileError, "hosted_agent_runtime_disabled"):
            save_workspace_agentic_binding(
                self.state.provider_store,
                self.state.provider_registry,
                workspace_id="default",
                definition_id=GOOGLE_AGENTIC_PROFILE_ID,
                definition_revision=GOOGLE_AGENTIC_PROFILE_REVISION,
                credential_binding_id=credential.binding_id,
                enabled=True,
                is_default=False,
                actor_policy=actor_policy,
                policy_patch=policy_patch,
                now=NOW,
            )
        self.assertFalse(
            any(
                binding.enabled
                for binding in self.state.provider_store.list_workspace_agentic_profile_bindings(
                    "default"
                )
                if binding.definition_id == GOOGLE_AGENTIC_PROFILE_ID
            )
        )

    def test_legacy_selection_is_not_written_before_authoritative_publication(self) -> None:
        previous = self.state.provider_store.get_provider_selection("default")

        with mock.patch(
            "core.providers.agentic_workspace_admin.ensure_codex_preview_certificate",
            side_effect=AgenticProfileError("simulated_certificate_failure"),
        ):
            with self.assertRaisesRegex(
                AgenticProfileError,
                "simulated_certificate_failure",
            ):
                configure_workspace_agentic_default(
                    self.state.provider_store,
                    self.state.provider_registry,
                    workspace_id="default",
                    provider_id="codex",
                    model_id="gpt-5.6-sol",
                    model_reasoning_effort="high",
                    now=NOW,
                )

        self.assertEqual(
            self.state.provider_store.get_provider_selection("default"),
            previous,
        )

    def test_workspace_policy_cannot_widen_profile_limits(self) -> None:
        profile = self.state.provider_store.get_agentic_profile_definition(
            GOOGLE_AGENTIC_PROFILE_ID,
            GOOGLE_AGENTIC_PROFILE_REVISION,
        )
        with self.assertRaisesRegex(AgenticProfileError, "workspace_profile_policy_widened"):
            save_workspace_agentic_binding(
                self.state.provider_store,
                self.state.provider_registry,
                workspace_id="default",
                definition_id=profile.definition_id,
                definition_revision=profile.revision,
                credential_binding_id=None,
                enabled=False,
                is_default=False,
                actor_policy=ActorSelectionPolicy(True, (), ("member",), ()),
                policy_patch={"max_output_tokens": profile.policy_ceiling.max_output_tokens + 1},
                now=NOW,
            )

    def test_partial_update_preserves_omitted_workspace_restrictions(self) -> None:
        actor_policy = ActorSelectionPolicy(True, (), ("member",), ())
        created = save_workspace_agentic_binding(
            self.state.provider_store,
            self.state.provider_registry,
            workspace_id="default",
            definition_id=GOOGLE_AGENTIC_PROFILE_ID,
            definition_revision=GOOGLE_AGENTIC_PROFILE_REVISION,
            credential_binding_id=None,
            enabled=False,
            is_default=False,
            actor_policy=actor_policy,
            policy_patch={
                "max_output_tokens": 256,
                "max_steps_per_turn": 2,
                "tool_access_enabled": False,
                "allowed_remote_data_classes": [],
            },
            now=NOW,
        )

        updated = save_workspace_agentic_binding(
            self.state.provider_store,
            self.state.provider_registry,
            workspace_id="default",
            definition_id=GOOGLE_AGENTIC_PROFILE_ID,
            definition_revision=GOOGLE_AGENTIC_PROFILE_REVISION,
            binding_id=created.binding_id,
            expected_revision=created.revision,
            credential_binding_id=None,
            enabled=False,
            is_default=False,
            actor_policy=actor_policy,
            policy_patch={"max_estimated_cost_microusd": 25_000},
            now=NOW,
        )

        self.assertEqual(updated.workspace_policy_ceiling.max_output_tokens, 256)
        self.assertEqual(updated.workspace_policy_ceiling.max_steps_per_turn, 2)
        self.assertEqual(updated.workspace_policy_ceiling.tool_handle_mode, "none")
        self.assertEqual(updated.workspace_policy_ceiling.allowed_remote_data_classes, ())

    def test_agent_type_allowlist_is_additive_to_human_actor_policy(self) -> None:
        binding = save_workspace_agentic_binding(
            self.state.provider_store,
            self.state.provider_registry,
            workspace_id="default",
            definition_id=GOOGLE_AGENTIC_PROFILE_ID,
            definition_revision=GOOGLE_AGENTIC_PROFILE_REVISION,
            credential_binding_id=None,
            enabled=False,
            is_default=False,
            actor_policy=ActorSelectionPolicy(False, (), ("member",), ("safe-agent",)),
            policy_patch={"tool_access_enabled": False},
            now=NOW,
        )
        self.assertFalse(
            actor_selection_allowed(
                binding,
                user_id="member-1",
                platform_role="member",
                workspace_role="member",
                agent_type_id="other-agent",
            )
        )
        self.assertTrue(
            actor_selection_allowed(
                binding,
                user_id="member-1",
                platform_role="member",
                workspace_role="member",
                agent_type_id="safe-agent",
            )
        )

    def test_binding_id_cannot_be_reused_across_workspaces(self) -> None:
        actor_policy = ActorSelectionPolicy(True, (), (), ())
        created = save_workspace_agentic_binding(
            self.state.provider_store,
            self.state.provider_registry,
            workspace_id="workspace-a",
            definition_id=GOOGLE_AGENTIC_PROFILE_ID,
            definition_revision=GOOGLE_AGENTIC_PROFILE_REVISION,
            binding_id="shared-binding-id",
            credential_binding_id=None,
            enabled=False,
            is_default=False,
            actor_policy=actor_policy,
            policy_patch={"tool_access_enabled": False},
            now=NOW,
        )
        self.assertEqual(created.workspace_id, "workspace-a")

        with self.assertRaisesRegex(
            AgenticProfileError,
            "workspace_profile_binding_identity_conflict",
        ):
            save_workspace_agentic_binding(
                self.state.provider_store,
                self.state.provider_registry,
                workspace_id="workspace-b",
                definition_id=GOOGLE_AGENTIC_PROFILE_ID,
                definition_revision=GOOGLE_AGENTIC_PROFILE_REVISION,
                binding_id="shared-binding-id",
                credential_binding_id=None,
                enabled=False,
                is_default=False,
                actor_policy=actor_policy,
                policy_patch={"tool_access_enabled": False},
                now=NOW,
            )


if __name__ == "__main__":
    unittest.main()
