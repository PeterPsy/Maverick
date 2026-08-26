from __future__ import annotations

from datetime import UTC, datetime
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.providers.agentic_models import (
    WorkspaceAgenticProfileBinding,
    default_actor_selection_policy,
)
from core.providers.google_agentic_profile import (
    GOOGLE_AGENTIC_PROFILE_ID,
    GOOGLE_AGENTIC_PROFILE_REVISION,
)
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class RuntimeRemoteDataDeclarationApiTest(AppReferenceApiTestSupport, unittest.TestCase):
    def test_remote_agentic_session_is_rejected_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state, app, cookie = self._platform(temp_dir)
            binding = self._remote_binding(state)
            before = state.runtime_store.list_all_sessions()

            with patch.object(
                state.runtime_store,
                "claim_client_message_id",
                wraps=state.runtime_store.claim_client_message_id,
            ) as claim_client_message:
                status, payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    body={
                        "agent_id": "chat",
                        "source_app_id": "chat",
                        "runtime_mode": "agentic",
                        "workspace_profile_binding_id": binding.binding_id,
                        "input_text": "must never persist",
                        "client_message_id": "remote-client-message",
                    },
                    cookie=cookie,
                )

            self.assertEqual(status, 409)
            self.assertEqual(payload["error"], "hosted_agent_runtime_disabled")
            self.assertEqual(state.runtime_store.list_all_sessions(), before)
            claim_client_message.assert_not_called()

    def test_client_fake_declaration_is_not_synthesized_or_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state, app, cookie = self._platform(temp_dir)
            binding = self._remote_binding(state)

            status, payload, _headers = self._invoke(
                app,
                path="/api/runtime/sessions",
                method="POST",
                body={
                    "agent_id": "chat",
                    "source_app_id": "chat",
                    "runtime_mode": "agentic",
                    "workspace_profile_binding_id": binding.binding_id,
                    "declared_remote_data_class": "workspace_internal_fake",
                },
                cookie=cookie,
            )

            self.assertEqual(status, 409)
            self.assertEqual(payload["error"], "remote_data_declaration_not_accepted")
            self.assertEqual(state.runtime_store.list_all_sessions(), [])

    def test_plain_hosted_session_rejects_agentic_remote_data_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            status, payload, _headers = self._invoke(
                app,
                path="/api/runtime/sessions",
                method="POST",
                body={
                    "agent_id": "chat",
                    "source_app_id": "chat",
                    "runtime_mode": "plain_hosted_chat",
                    "declared_remote_data_class": "workspace_internal_fake",
                },
                cookie=cookie,
            )

            self.assertEqual(status, 409)
            self.assertEqual(payload["error"], "remote_data_declaration_not_accepted")

    def _platform(self, temp_dir: str):
        repo_root = self._repo_root(temp_dir)
        with patch.dict(
            "os.environ",
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        return state, app, self._login(app)

    @staticmethod
    def _remote_binding(state):
        definition = state.provider_store.get_agentic_profile_definition(
            GOOGLE_AGENTIC_PROFILE_ID,
            GOOGLE_AGENTIC_PROFILE_REVISION,
        )
        now = datetime.now(UTC)
        return state.provider_store.save_workspace_agentic_profile_binding(
            WorkspaceAgenticProfileBinding(
                binding_id="binding-google-contained-api",
                workspace_id="default",
                definition_id=definition.definition_id,
                definition_revision=definition.revision,
                credential_binding_id=None,
                enabled=True,
                is_default=False,
                actor_policy=default_actor_selection_policy(),
                workspace_policy_ceiling=definition.policy_ceiling,
                egress_policy_id=definition.egress_policy_id,
                egress_policy_revision=definition.egress_policy_revision,
                revision=0,
                created_at=now,
                updated_at=now,
            ),
            expected_revision=None,
        )


if __name__ == "__main__":
    unittest.main()
