from __future__ import annotations

from dataclasses import replace
from io import BytesIO
import json
import os
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.api.runtime_websocket import stream_runtime_session_events
from core.providers.provider_credentials import bind_provider_credential
from core.providers.service import builtin_provider_registry
from core.secrets.service import build_secret_ref, create_platform_secret
from tests.support.repo import make_temp_repo_root


class ChatPlainHostedRuntimeTest(unittest.IsolatedAsyncioTestCase):
    def make_state(self, *, bind_groq: bool = True):
        state = bootstrap_platform_state(start_path=make_temp_repo_root(self))
        groq = builtin_provider_registry().get_provider_definition("groq")
        state.provider_store.save_provider_definition(replace(groq, status="active"))
        if bind_groq:
            secret = create_platform_secret(
                state.secret_store,
                label="Groq chat test",
                raw_value="super-secret-token",
                alias="groq-chat-hosted",
                kind="api_key",
            )
            bind_provider_credential(
                state.provider_store,
                provider_id="groq",
                workspace_id="default",
                secret_ref=build_secret_ref(alias=secret.alias or "groq-chat-hosted"),
            )
        return state

    def invoke(self, state, *, path: str, method: str = "GET", body: dict | None = None, cookie: str = "") -> tuple[int, dict, dict[str, str]]:
        app = PlatformHost(state, start_path=state.repository_root)
        payload = json.dumps(body).encode("utf-8") if body is not None else b""
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "wsgi.input": BytesIO(payload),
        }
        if cookie:
            environ["HTTP_COOKIE"] = cookie

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        body_bytes = b"".join(app(environ, start_response))
        return int(headers["__status__"].split()[0]), json.loads(body_bytes.decode("utf-8")), headers

    def login_cookie(self, state) -> str:
        status, _payload, headers = self.invoke(
            state,
            path="/api/auth/login",
            method="POST",
            body={
                "username": os.environ.get("MAVERICK_ADMIN_USERNAME", "admin"),
                "password": os.environ.get("MAVERICK_ADMIN_PASSWORD", "maverick"),
            },
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    async def collect_websocket_frames(self, state, *, session_id: str, cookie: str) -> list[dict]:
        sent: list[dict] = []
        received = [{"type": "websocket.connect"}, {"type": "websocket.disconnect"}]

        async def receive() -> dict:
            return received.pop(0)

        async def send(message: dict) -> None:
            sent.append(message)

        await stream_runtime_session_events(
            state=state,
            scope={
                "type": "websocket",
                "path": f"/ws/runtime/sessions/{session_id}",
                "query_string": b"",
                "headers": [(b"cookie", cookie.encode("latin1"))],
            },
            receive=receive,
            send=send,
        )
        return [json.loads(item["text"]) for item in sent if item.get("type") == "websocket.send"]

    async def test_chat_plain_hosted_turn_reaches_websocket_transcript_events_without_codex(self) -> None:
        state = self.make_state()
        cookie = self.login_cookie(state)

        with (
            patch.dict(os.environ, {"MAVERICK_HOSTED_TEXT_FAKE_CHUNKS": '["Hosted ", "answer"]'}, clear=False),
            patch("core.runtime.turn_submission_service_output.schedule_runtime_thread_title_generation"),
            patch(
                "core.runtime.turn_submission_service_submit.resolve_runtime_backend_for_session",
                side_effect=AssertionError("plain hosted chat must not resolve Codex runtime"),
            ),
        ):
            status, payload, _headers = self.invoke(
                state,
                path="/api/runtime/sessions",
                method="POST",
                cookie=cookie,
                body={
                    "agent_id": "chat",
                    "source_app_id": "chat",
                    "runtime_mode": "plain_hosted_chat",
                    "routing_profile": "fast_model",
                    "input_text": "Hello hosted",
                    "client_message_id": "client-plain",
                    "async": False,
                },
            )

        self.assertEqual(status, 201)
        self.assertEqual(payload["session"]["runtime_mode"], "plain_hosted_chat")
        self.assertEqual(payload["session"]["provider_id"], "groq")
        self.assertEqual(payload["turn"]["status"], "completed")
        self.assertEqual(payload["turn"]["runtime_mode"], "plain_hosted_chat")
        event_types = [event["event_type"] for event in payload["events"]]
        self.assertIn("runtime.output.final", event_types)
        self.assertIn("runtime.turn.completed", event_types)
        self.assertNotIn("super-secret-token", json.dumps(payload))

        frames = await self.collect_websocket_frames(state, session_id=payload["session"]["session_id"], cookie=cookie)
        snapshot = frames[0]
        self.assertEqual(snapshot["type"], "runtime.snapshot")
        snapshot_events = snapshot["events"]
        self.assertEqual(snapshot["session"]["runtime_mode"], "plain_hosted_chat")
        self.assertEqual(snapshot["session"]["provider_id"], "groq")
        self.assertIn("runtime.output.delta", [event["event_type"] for event in snapshot_events])
        final_event = next(event for event in snapshot_events if event["event_type"] == "runtime.output.final")
        self.assertEqual(final_event["payload"]["complete_text"], "Hosted answer")
        self.assertNotIn("super-secret-token", json.dumps(snapshot))

    async def test_chat_plain_hosted_missing_credentials_returns_failed_turn_reason_without_codex(self) -> None:
        state = self.make_state(bind_groq=False)
        cookie = self.login_cookie(state)

        with patch(
            "core.runtime.turn_submission_service_submit.resolve_runtime_backend_for_session",
            side_effect=AssertionError("plain hosted chat must not resolve Codex runtime"),
        ):
            status, payload, _headers = self.invoke(
                state,
                path="/api/runtime/sessions",
                method="POST",
                cookie=cookie,
                body={
                    "agent_id": "chat",
                    "source_app_id": "chat",
                    "runtime_mode": "plain_hosted_chat",
                    "routing_profile": "fast_model",
                    "input_text": "Hello hosted",
                    "async": False,
                },
            )

        self.assertEqual(status, 201)
        self.assertEqual(payload["session"]["provider_id"], "hosted-text-runtime")
        self.assertEqual(payload["turn"]["status"], "failed")
        self.assertEqual(payload["turn"]["failure_reason"], "no_fast_model_available")
        self.assertIn("runtime.turn.failed", [event["event_type"] for event in payload["events"]])
        self.assertNotIn("super-secret-token", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
