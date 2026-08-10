from __future__ import annotations

import asyncio
from io import BytesIO
import json
from pathlib import Path
import os
import tempfile
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from core.api.asgi_application import LazyAsgiApplication, PlatformAsgiHost, _forward_wsgi_response_body, _is_app_backend_request, app
from core.api.app_events import APP_EVENTS_WS_PATH
from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.shared.entrypoints import EntrypointShutdownController


REPO_ROOT = Path(__file__).resolve().parents[3]


class AsgiApplicationTests(unittest.TestCase):
    def test_module_app_is_lazy_to_avoid_import_time_bootstrap(self) -> None:
        self.assertIsInstance(app, LazyAsgiApplication)
        self.assertIsNone(app._app)

    def test_http_host_runs_outside_event_loop(self) -> None:
        source = (REPO_ROOT / "core/api/asgi_application.py").read_text(encoding="utf-8")

        self.assertIn("asyncio.to_thread", source)
        self.assertIn("ThreadPoolExecutor", source)
        self.assertIn("run_in_executor", source)
        self.assertIn("maverick-app-backend", source)
        self.assertIn("_run_wsgi_http", source)
        self.assertIn("self.http_host", source)

    def test_app_backend_request_detection_is_limited_to_backend_posts(self) -> None:
        self.assertTrue(_is_app_backend_request({"path": "/api/apps/example/backend", "method": "POST"}))
        self.assertTrue(_is_app_backend_request({"path": "/api/apps/example-fork/backend", "method": "post"}))
        self.assertTrue(_is_app_backend_request({"path": "/api/apps/example/media", "method": "GET"}))
        self.assertTrue(_is_app_backend_request({"path": "/api/apps/example/media", "method": "HEAD"}))
        self.assertFalse(_is_app_backend_request({"path": "/api/apps/example/backend", "method": "GET"}))
        self.assertFalse(_is_app_backend_request({"path": "/api/apps/example/frontend/", "method": "POST"}))
        self.assertFalse(_is_app_backend_request({"path": "/api/session", "method": "POST"}))

    def test_lifespan_shutdown_marks_entrypoint_shutdown_controller(self) -> None:
        controller = EntrypointShutdownController()
        host = PlatformAsgiHost(
            state=SimpleNamespace(repository_root=REPO_ROOT),
            shutdown_controller=controller,
        )
        messages = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
        sent: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            return messages.pop(0)

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        asyncio.run(host({"type": "lifespan"}, receive, send))

        self.assertEqual(
            sent,
            [
                {"type": "lifespan.startup.complete"},
                {"type": "lifespan.shutdown.complete"},
            ],
        )
        self.assertTrue(controller.is_shutting_down())

    def test_request_disconnect_controller_is_distinct_from_host_shutdown(self) -> None:
        host = EntrypointShutdownController()
        request = EntrypointShutdownController(parent=host, interruption_reason="client disconnect")

        request.begin_shutdown()

        self.assertTrue(request.is_shutting_down())
        self.assertEqual(request.interruption_reason(), "client disconnect")
        self.assertFalse(host.is_shutting_down())

    def test_http_request_body_uses_configured_size_limit_before_wsgi_dispatch(self) -> None:
        host = PlatformAsgiHost(state=SimpleNamespace(repository_root=REPO_ROOT))
        sent: list[dict[str, object]] = []
        messages = [
            {"type": "http.request", "body": b"abcdef", "more_body": False},
        ]

        async def receive() -> dict[str, object]:
            return messages.pop(0)

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        with patch.dict("os.environ", {"MAVERICK_MAX_JSON_BODY_BYTES": "5"}):
            asyncio.run(
                host(
                    {"type": "http", "path": "/api/session", "method": "POST", "headers": []},
                    receive,
                    send,
                )
            )

        self.assertEqual(sent[0]["type"], "http.response.start")
        self.assertEqual(sent[0]["status"], 413)
        self.assertIn(b"request_body_too_large", sent[1]["body"])

    def test_health_response_bypasses_wsgi_worker_pool(self) -> None:
        host = PlatformAsgiHost(state=SimpleNamespace(repository_root=REPO_ROOT))
        sent: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            raise AssertionError("health should not read a request body")

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        with patch("core.api.asgi_application.asyncio.to_thread", side_effect=AssertionError("worker pool used")):
            asyncio.run(
                host(
                    {"type": "http", "path": "/health", "method": "GET", "headers": []},
                    receive,
                    send,
                )
            )

        self.assertEqual(sent[0]["type"], "http.response.start")
        self.assertEqual(sent[0]["status"], 200)
        self.assertEqual(json.loads(sent[1]["body"].decode("utf-8")), {"status": "ok", "service": "maverick-core"})

    def test_streaming_app_response_closes_blocked_iterator_on_client_disconnect(self) -> None:
        class BlockingIterator:
            def __init__(self) -> None:
                self.started = Event()
                self.released = Event()
                self.closed = False

            def __iter__(self):
                return self

            def __next__(self) -> bytes:
                self.started.set()
                self.released.wait(timeout=2)
                raise StopIteration

            def close(self) -> None:
                self.closed = True
                self.released.set()

        iterator = BlockingIterator()
        sent: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            while not iterator.started.is_set():
                await asyncio.sleep(0)
            return {"type": "http.disconnect"}

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        controller = SimpleNamespace(begin_shutdown=iterator.close)
        disconnected = asyncio.run(
            _forward_wsgi_response_body(
                iterator,
                receive=receive,
                send=send,
                executor=None,
                request_shutdown_controller=controller,  # type: ignore[arg-type]
            )
        )

        self.assertTrue(disconnected)
        self.assertTrue(iterator.closed)
        self.assertEqual(sent, [])

    def test_app_events_websocket_rejects_anonymous_handshake(self) -> None:
        host = PlatformAsgiHost(state=SimpleNamespace(repository_root=REPO_ROOT))
        sent: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            return {"type": "websocket.connect"}

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        asyncio.run(host({"type": "websocket", "path": APP_EVENTS_WS_PATH, "headers": []}, receive, send))

        self.assertEqual(sent, [{"type": "websocket.close", "code": 4401}])

    def test_app_events_websocket_filters_events_to_session_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo_root = Path(temp) / "maverick"
            for name in ("core", "apps", "workspaces", "scripts"):
                (repo_root / name).mkdir(parents=True, exist_ok=True)
            (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
            (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
                clear=False,
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            cookie = self._login_cookie(state)
            host = PlatformAsgiHost(state=state)
            sent: list[dict[str, object]] = []
            receive_queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()

            async def receive() -> dict[str, object]:
                return await receive_queue.get()

            async def send(message: dict[str, object]) -> None:
                sent.append(message)

            async def run_case() -> None:
                await receive_queue.put({"type": "websocket.connect"})
                stream = asyncio.create_task(
                    host(
                        {
                            "type": "websocket",
                            "path": APP_EVENTS_WS_PATH,
                            "headers": [(b"cookie", cookie.encode("latin1"))],
                        },
                        receive,
                        send,
                    )
                )
                while not any(message.get("type") == "websocket.accept" for message in sent):
                    await asyncio.sleep(0)
                state.app_event_bus.publish({"type": "maverick.app.data-changed", "workspace_id": "other", "owner_app_id": "sample", "resource": "records"})
                state.app_event_bus.publish({"type": "maverick.app.data-changed", "workspace_id": "default", "owner_app_id": "sample", "resource": "records"})
                while not any(message.get("type") == "websocket.send" for message in sent):
                    await asyncio.sleep(0)
                await receive_queue.put({"type": "websocket.disconnect"})
                await stream

            asyncio.run(run_case())

        frames = [json.loads(str(item["text"])) for item in sent if item.get("type") == "websocket.send"]
        self.assertEqual([frame["workspace_id"] for frame in frames], ["default"])

    def _login_cookie(self, state) -> str:
        app_host = PlatformHost(state, start_path=state.repository_root)
        payload = json.dumps({"username": "admin", "password": "maverick"}).encode("utf-8")
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": "/api/auth/login",
            "REQUEST_METHOD": "POST",
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "wsgi.input": BytesIO(payload),
        }

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        b"".join(app_host(environ, start_response))
        self.assertEqual(headers["__status__"].split()[0], "200")
        return headers["Set-Cookie"].split(";", 1)[0]


if __name__ == "__main__":
    unittest.main()
