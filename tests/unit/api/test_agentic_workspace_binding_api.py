from __future__ import annotations

from io import BytesIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.provider_api import handle_provider_api
from core.api.session_api import RequestSession
from core.authorization.errors import AuthorizationError
from core.providers.service import (
    builtin_provider_registry,
    configure_workspace_provider,
    register_builtin_providers,
)
from core.providers.store import ProviderCollections, ProviderDocumentStore
from tests.support.collections import FakeCollection


class AgenticWorkspaceBindingApiTest(unittest.TestCase):
    def make_state(self):
        provider_store = ProviderDocumentStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
            )
        )
        register_builtin_providers(provider_store)
        return SimpleNamespace(
            provider_store=provider_store,
            workspace_store=SimpleNamespace(),
            observability_store=None,
        )

    def test_workspace_admin_can_narrow_agentic_binding_through_settings_contract(self) -> None:
        state = self.make_state()
        registry = builtin_provider_registry()
        state.provider_registry = registry
        configure_workspace_provider(
            state.provider_store,
            workspace_id="default",
            provider_id="codex",
            registry=registry,
        )
        binding = state.provider_store.list_workspace_agentic_profile_bindings("default")[0]

        with patch("core.api.provider_api.require_provider_selection_authority", return_value=None):
            status, payload = self.invoke(
                "/api/providers/agentic/workspace-bindings",
                method="POST",
                body={
                    "definition_id": binding.definition_id,
                    "definition_revision": binding.definition_revision,
                    "binding_id": binding.binding_id,
                    "expected_revision": binding.revision,
                    "credential_binding_id": None,
                    "enabled": True,
                    "is_default": True,
                    "actor_policy": {
                        "allow_workspace_admins": True,
                        "allowed_user_ids": [],
                        "allowed_workspace_role_ids": ["member"],
                        "allowed_agent_type_ids": [],
                    },
                    "policy_patch": {
                        "tool_access_enabled": False,
                        "allowed_remote_data_classes": [],
                        "max_estimated_cost_microusd": None,
                    },
                    "confirm_fake_data_only_workspace": False,
                },
                state=state,
            )

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["binding_revision"], binding.revision + 1)
        saved = state.provider_store.get_workspace_agentic_profile_binding(binding.binding_id)
        self.assertEqual(saved.workspace_policy_ceiling.tool_handle_mode, "none")
        self.assertNotIn("secret_ref", json.dumps(payload, default=str))

    def test_agentic_binding_mutation_requires_workspace_authority(self) -> None:
        with patch(
            "core.api.provider_api.require_provider_selection_authority",
            side_effect=AuthorizationError("provider_selection_forbidden"),
        ):
            status, payload = self.invoke(
                "/api/providers/agentic/workspace-bindings",
                method="POST",
                body={"definition_id": "definition", "definition_revision": "1"},
            )
        self.assertEqual(status, "403 Forbidden")
        self.assertEqual(payload["error"], "provider_selection_forbidden")

    def test_raw_agentic_catalogs_require_workspace_authority(self) -> None:
        for path in (
            "/api/providers/agentic/profile-definitions",
            "/api/providers/agentic/certificates",
        ):
            with self.subTest(path=path), patch(
                "core.api.provider_api.require_provider_selection_authority",
                side_effect=AuthorizationError("provider_selection_forbidden"),
            ):
                status, payload = self.invoke(path)
            self.assertEqual(status, "403 Forbidden")
            self.assertEqual(payload["error"], "provider_selection_forbidden")

    def invoke(self, path: str, *, method: str = "GET", body: dict | None = None, state=None):
        state = state or self.make_state()
        context = RequestSession(
            user=SimpleNamespace(user_id="user-1", platform_role="admin"),
            session=SimpleNamespace(session_id="session-1"),
            workspace_id="default",
        )
        body_bytes = json.dumps(body or {}).encode("utf-8") if body is not None else b""
        environ = {
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "REQUEST_METHOD": method,
            "wsgi.input": BytesIO(body_bytes),
            "CONTENT_LENGTH": str(len(body_bytes)),
            "CONTENT_TYPE": "application/json",
        }
        captured = {}

        def start_response(status, headers):
            captured["status"] = status

        with patch("core.api.provider_api.require_session", return_value=context):
            response = handle_provider_api(state, environ, start_response)
        assert response is not None
        return captured["status"], json.loads(b"".join(response).decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
