"""Settings can restore a native connection through a human admin session."""

from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.provider_api import handle_provider_api
from core.api.session_api import RequestSession
from core.providers.models import ProviderModelOption
from core.providers.native_agent_catalog import NativeAgentCatalogModel, NativeAgentCatalogSnapshot
from core.providers.native_agent_contract import NativeRuntimeStatus
from core.providers.native_agent_status import native_agent_status_items
from core.providers.service import builtin_provider_registry, register_builtin_providers
from core.providers.store import ProviderCollections, ProviderDocumentStore
from tests.support.collections import FakeCollection


class NativeProviderActivationApiTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        self.store = ProviderDocumentStore(ProviderCollections(
            definitions=FakeCollection(), bindings=FakeCollection(), selections=FakeCollection(),
        ))
        self.registry = builtin_provider_registry(refresh_model_catalog=False)
        register_builtin_providers(self.store, registry=self.registry)
        self.state = SimpleNamespace(
            provider_store=self.store, provider_registry=self.registry, observability_store=None,
        )
        self.snapshot = NativeAgentCatalogSnapshot(
            runtime_engine_id="antigravity-cli", model_provider_id="google",
            catalog_provider_id="antigravity-cli", source_id="test-catalog",
            observed_at=datetime.now(UTC),
            models=(NativeAgentCatalogModel("google", "gemini-3.8-flash-high", None, "provider_alias"),),
            model_options=(ProviderModelOption(
                model_id="gemini-3.8-flash-high", label="Gemini 3.8 Flash",
                description=None, default_reasoning_effort=None,
            ),),
        )
        self.catalog = patch(
            "core.providers.native_agent_reconciliation.discover_antigravity_native_catalog",
            return_value=self.snapshot,
        ).start()
        patch("core.providers.native_agent_reconciliation.discover_codex_native_catalog", return_value=None).start()
        self.health = patch.object(
            self.registry.get_native_agent_installation("antigravity-cli").inspector,
            "inspect", return_value=NativeRuntimeStatus(
                availability="installed", executable_path="/test/agy", runtime_version="test", health="healthy",
                reason_codes=(), update_status="unknown",
            ),
        ).start()

    def invoke(self, body=None, *, role="admin", method="POST", authenticated=True):
        request = json.dumps(body if body is not None else {
            "provider_id": "antigravity-cli", "confirmation": "native-runtime-reviewed",
        }).encode()
        environ = {
            "PATH_INFO": "/api/providers/native/activate", "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(request)), "wsgi.input": BytesIO(request),
        }
        captured = {}
        def start_response(status, _headers):
            captured["status"] = status
        context = RequestSession(
            user=SimpleNamespace(platform_role=role, user_id="human-admin"),
            session=SimpleNamespace(), workspace_id="default",
        )
        if authenticated:
            with patch("core.api.provider_api.require_session", return_value=context):
                result = handle_provider_api(self.state, environ, start_response)
        else:
            # A runtime bearer token is not a browser admin session.
            environ["HTTP_AUTHORIZATION"] = "Bearer runtime-token"
            result = handle_provider_api(self.state, environ, start_response)
        return captured["status"], json.loads(b"".join(result))

    def test_admin_restores_connection_and_leaves_workspace_choices_unchanged(self):
        before = self.store.list_workspace_agentic_profile_bindings("default")
        status, payload = self.invoke()
        self.assertEqual(status, "200 OK", payload)
        self.assertEqual(payload["provider"]["status"], "active")
        self.assertEqual(payload["profile_count"], 1)
        self.assertEqual(self.store.get_provider_definition("antigravity-cli").status, "active")
        native = next(item for item in native_agent_status_items(self.registry)
                      if item["runtime_engine_id"] == "antigravity-cli")
        self.assertTrue(native["selectable"])
        self.assertEqual(self.store.list_workspace_agentic_profile_bindings("default"), before)

    def test_member_cannot_activate(self):
        status, payload = self.invoke(role="member")
        self.assertEqual((status, payload["error"]), ("403 Forbidden", "admin_required"))
        self.catalog.assert_not_called()

    def test_runtime_token_cannot_activate(self):
        status, _payload = self.invoke(authenticated=False)
        self.assertEqual(status, "401 Unauthorized")
        self.catalog.assert_not_called()

    def test_confirmation_is_required(self):
        status, payload = self.invoke({"provider_id": "antigravity-cli"})
        self.assertEqual((status, payload["error"]), ("400 Bad Request", "native_activation_confirmation_required"))
        self.catalog.assert_not_called()

    def test_get_never_activates(self):
        self.assertEqual(self.invoke(method="GET")[0], "405 Method Not Allowed")
        self.catalog.assert_not_called()

    def test_unhealthy_runtime_remains_disabled(self):
        self.health.return_value = replace(self.health.return_value, health="unavailable")
        status, payload = self.invoke()
        self.assertEqual((status, payload["error"]), ("400 Bad Request", "native_runtime_unavailable"))
        self.assertEqual(self.store.get_provider_definition("antigravity-cli").status, "disabled")

    def test_missing_catalog_remains_disabled(self):
        self.catalog.return_value = None
        status, payload = self.invoke()
        self.assertEqual((status, payload["error"]), ("400 Bad Request", "native_agent_model_projection_missing"))
        self.assertEqual(self.store.get_provider_definition("antigravity-cli").status, "disabled")


if __name__ == "__main__":
    unittest.main()
