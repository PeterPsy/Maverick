"""Provider API read-only surface tests."""

from __future__ import annotations

from io import BytesIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.provider_api import handle_provider_api
from core.api.session_api import RequestSession
from core.providers.service import register_builtin_providers
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.runtime.service import create_runtime_session
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.secrets.service import build_secret_ref, create_platform_secret
from core.secrets.store import SecretCollections, SecretDocumentStore
from tests.support.collections import FakeCollection


class ProviderApiTest(unittest.TestCase):
    def make_provider_store(self) -> ProviderDocumentStore:
        store = ProviderDocumentStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
            )
        )
        register_builtin_providers(store)
        return store

    def make_secret_store(self) -> SecretDocumentStore:
        return SecretDocumentStore(
            SecretCollections(
                secrets=FakeCollection(),
                values=FakeCollection(),
                bindings=FakeCollection(),
                grants=FakeCollection(),
            ),
            key_loader=lambda: b"0" * 32,
        )

    def make_runtime_store(self) -> RuntimeDocumentStore:
        return RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
            )
        )

    def make_state(self):
        return SimpleNamespace(
            provider_store=self.make_provider_store(),
            secret_store=self.make_secret_store(),
            runtime_store=self.make_runtime_store(),
            observability_store=None,
        )

    def test_provider_list_exposes_role_and_capabilities(self) -> None:
        status, payload = self.invoke("/api/providers")

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["items"][0]["provider_id"], "codex")
        self.assertEqual(payload["items"][0]["provider_role"], "runtime_engine")
        self.assertIn("capabilities", payload["items"][0])
        self.assertNotIn("secret_ref", str(payload))

    def test_provider_route_returns_redaction_safe_decision(self) -> None:
        status, payload = self.invoke("/api/providers/route", query="profile=fast_model&request_id=req-api")

        self.assertEqual(status, "200 OK")
        decision = payload["decision"]
        self.assertEqual(decision["request_id"], "req-api")
        self.assertEqual(decision["candidate_provider_ids"], ["groq"])
        self.assertIn("provider_disabled:groq", decision["reason_codes"])
        self.assertNotIn("secret_ref", str(payload))

    def test_operator_can_activate_hosted_provider_and_route_preview_uses_it(self) -> None:
        state = self.make_state()
        secret = create_platform_secret(
            state.secret_store,
            label="Groq API",
            raw_value="super-secret-token",
            alias="groq-api",
            kind="api_key",
        )

        status, payload = self.invoke(
            "/api/providers/hosted/active",
            method="POST",
            body={
                "provider_id": "groq",
                "secret_ref": build_secret_ref(alias=secret.alias or "groq-api"),
            },
            state=state,
        )
        route_status, route_payload = self.invoke(
            "/api/providers/route",
            query="profile=fast_model&request_id=req-api-active",
            state=state,
        )

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["provider"]["provider_id"], "groq")
        self.assertEqual(payload["provider"]["status"], "active")
        self.assertEqual(payload["credential_binding"]["provider_id"], "groq")
        self.assertEqual(payload["preflight"]["selected_provider_id"], "groq")
        self.assertEqual(route_status, "200 OK")
        self.assertEqual(route_payload["decision"]["selected_provider_id"], "groq")
        self.assertNotIn("super-secret-token", json.dumps(payload))
        self.assertNotIn("secret_ref", json.dumps(payload))

    def test_runtime_status_exposes_runtime_mode(self) -> None:
        state = self.make_state()
        create_runtime_session(
            state.runtime_store,
            session_id="sess-plain",
            workspace_id="default",
            agent_id="chat",
            runtime_mode="plain_hosted_chat",
        )

        status, payload = self.invoke("/api/runtime/status", state=state)

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["sessions"][0]["runtime_mode"], "plain_hosted_chat")

    def invoke(
        self,
        path: str,
        *,
        query: str = "",
        method: str = "GET",
        body: dict | None = None,
        state=None,
    ) -> tuple[str, dict]:
        state = state or self.make_state()
        context = RequestSession(
            user=SimpleNamespace(user_id="user-1", platform_role="admin"),
            session=SimpleNamespace(session_id="session-1"),
            workspace_id="default",
        )
        body_bytes = json.dumps(body or {}).encode("utf-8") if body is not None else b""
        environ = {
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "REQUEST_METHOD": method,
            "wsgi.input": BytesIO(body_bytes),
            "CONTENT_LENGTH": str(len(body_bytes)),
            "CONTENT_TYPE": "application/json",
        }
        captured: dict[str, object] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = headers

        with patch("core.api.provider_api.require_session", return_value=context):
            body = handle_provider_api(state, environ, start_response)

        assert body is not None
        return str(captured["status"]), json.loads(b"".join(body).decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
