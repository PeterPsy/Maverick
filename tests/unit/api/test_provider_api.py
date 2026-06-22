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
            )
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

    def invoke(self, path: str, *, query: str = "") -> tuple[str, dict]:
        state = SimpleNamespace(
            provider_store=self.make_provider_store(),
            secret_store=self.make_secret_store(),
        )
        context = RequestSession(
            user=SimpleNamespace(user_id="user-1"),
            session=SimpleNamespace(session_id="session-1"),
            workspace_id="default",
        )
        environ = {
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "REQUEST_METHOD": "GET",
            "wsgi.input": BytesIO(b""),
            "CONTENT_LENGTH": "0",
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
