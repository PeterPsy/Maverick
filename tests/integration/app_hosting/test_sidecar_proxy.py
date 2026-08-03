"""Integration tests for governed app-owned HTTP sidecar proxying."""

from __future__ import annotations

import asyncio
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.api.asgi_application import PlatformAsgiHost
from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.api.sidecar_proxy import (
    _sidecar_env,
    request_authorized_sidecar_buffered,
    resolve_authorized_sidecar,
)
from core.apps.contracts import (
    build_app_contract,
    build_app_services,
    build_http_sidecar_logs,
    build_http_sidecar_proxy,
    build_http_sidecar_route_policy,
    build_http_sidecar_route_rule,
    build_http_sidecar_spec,
    build_parsed_app_contract,
    write_app_contract_file,
)
from core.apps.models import HttpSidecarBindSpec, HttpSidecarHealthSpec
from core.apps.errors import AppHostingError
from core.apps.service import install_store_app, register_app_source_from_contract
from core.shared.entrypoints import EntrypointShutdownController
from tests.integration.app_hosting.sidecar_proxy_support import TEST_SIDECAR_SERVER


class AppSidecarProxyIntegrationTests(unittest.TestCase):
    def test_internal_buffered_request_keeps_technical_authority_in_core_and_bounds_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo_root = self._repo_root(temp)
            state = bootstrap_platform_state(start_path=repo_root)
            self._install_sidecar_app(repo_root, state)
            shutdown = EntrypointShutdownController()
            self.addCleanup(shutdown.begin_shutdown)
            user = state.identity_store.get_user_by_username("admin")
            target, error = resolve_authorized_sidecar(
                state,
                workspace_id="default",
                app_id="sidecar-demo",
                sidecar_id="opendesign",
                user=user,
                start_path=repo_root,
            )
            self.assertIsNone(error)
            self.assertIsNotNone(target)

            response = request_authorized_sidecar_buffered(
                target,
                method="GET",
                path="/api/version",
                query_string="",
                headers={
                    "authorization": "Bearer app-controlled",
                    "cookie": "maverick=must-not-cross",
                    "x-test": "safe",
                },
                body=b"",
                max_response_body_bytes=4096,
                timeout_seconds=5,
                start_path=repo_root,
                shutdown_controller=shutdown,
            )
            with self.assertRaisesRegex(AppHostingError, "exceeded"):
                request_authorized_sidecar_buffered(
                    target,
                    method="GET",
                    path="/api/version",
                    query_string="",
                    headers={},
                    body=b"",
                    max_response_body_bytes=4,
                    timeout_seconds=5,
                    start_path=repo_root,
                    shutdown_controller=shutdown,
                )

        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["technical_token_seen"])
        self.assertFalse(payload["cookie_seen"])
        self.assertEqual(payload["safe_header"], "safe")
        self.assertNotIn("set-cookie", response.headers)

    def test_sidecar_environment_is_allowlisted_and_does_not_inherit_host_state(self) -> None:
        sidecar = build_http_sidecar_spec(
            service_id="opendesign",
            runtime="python",
            working_directory="service",
            command=["python3", "server.py"],
            env={"OD_PORT": "${service.port}"},
            bind=HttpSidecarBindSpec(host="127.0.0.1", port="auto"),
            health=HttpSidecarHealthSpec(path="/api/ready", timeout_ms=5000),
        )
        sentinel = "MAVERICK_WP0_HOST_ENV_SENTINEL"

        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {
                sentinel: "must-not-cross",
                "HOME": "/operator-home",
                "OPENAI_API_KEY": "must-not-cross",
                "PYTHONPATH": "/operator-pythonpath",
            },
        ):
            root = self._repo_root(temp)
            env = _sidecar_env(
                workspace_id="default",
                app_id="sidecar-demo",
                data_root=str(root / "data"),
                source_root=root / "source",
                workspace_root=root / "workspace",
                port=12345,
                token="technical-token",
                sidecar=sidecar,
                start_path=root,
            )

        self.assertNotIn(sentinel, env)
        self.assertNotIn("HOME", env)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("/operator-pythonpath", env.get("PYTHONPATH", ""))
        self.assertEqual(env["PATH"], "/usr/local/bin:/usr/bin:/bin")
        self.assertEqual(env["MAVERICK_WORKSPACE_ID"], "default")

    def test_sidecar_proxy_starts_process_injects_token_and_blocks_sandbox_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo_root = self._repo_root(temp)
            state = bootstrap_platform_state(start_path=repo_root)
            self._install_sidecar_app(repo_root, state)
            shutdown = EntrypointShutdownController()
            self.addCleanup(shutdown.begin_shutdown)
            app = PlatformHost(state, start_path=repo_root, shutdown_controller=shutdown)
            cookie = self._login(app)

            status, body, _headers = self._invoke(
                app,
                path="/api/apps/sidecar-demo/sidecars/opendesign/api/version",
                cookie=cookie,
            )
            blocked_status, blocked_body, _blocked_headers = self._invoke(
                app,
                path="/api/apps/sidecar-demo/sidecars/opendesign/api/import/folder",
                cookie=cookie,
            )

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["service"], "opendesign-test")
        self.assertTrue(payload["technical_token_seen"])
        self.assertEqual(blocked_status, 403)
        self.assertIn(b"sidecar_route_blocked", blocked_body)

    def test_asgi_sidecar_proxy_streams_sse_before_response_completes(self) -> None:
        asyncio.run(self._assert_asgi_sidecar_proxy_streams_sse_before_response_completes())

    def test_asgi_sidecar_proxy_streams_request_body_outside_json_limit(self) -> None:
        asyncio.run(self._assert_asgi_sidecar_proxy_streams_request_body_outside_json_limit())

    def test_asgi_sidecar_proxy_reencodes_unknown_length_request_body_as_chunked(self) -> None:
        asyncio.run(self._assert_asgi_sidecar_proxy_reencodes_unknown_length_request_body_as_chunked())

    async def _assert_asgi_sidecar_proxy_streams_sse_before_response_completes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo_root = self._repo_root(temp)
            state = bootstrap_platform_state(start_path=repo_root)
            self._install_sidecar_app(repo_root, state)
            shutdown = EntrypointShutdownController()
            self.addCleanup(shutdown.begin_shutdown)
            app = PlatformAsgiHost(state, shutdown_controller=shutdown)
            cookie = await self._login_asgi(app)
            messages: list[dict] = []
            queue: asyncio.Queue[dict] = asyncio.Queue()

            task = asyncio.create_task(
                self._invoke_asgi_streaming(
                    app,
                    path="/api/apps/sidecar-demo/sidecars/opendesign/api/events",
                    cookie=cookie,
                    messages=messages,
                    queue=queue,
                )
            )
            start_message = await asyncio.wait_for(queue.get(), timeout=3)
            first_body = await self._next_asgi_body(queue)

            self.assertEqual(start_message["type"], "http.response.start")
            self.assertEqual(start_message["status"], 200)
            self.assertEqual(dict(start_message["headers"])[b"content-type"], b"text/event-stream")
            self.assertIn(b"data: one", first_body["body"])
            self.assertNotIn(b"Bearer", first_body["body"])
            self.assertFalse(task.done())
            await asyncio.wait_for(task, timeout=3)
            response_body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
            self.assertIn(b"data: two", response_body)

    async def _assert_asgi_sidecar_proxy_streams_request_body_outside_json_limit(self) -> None:
        previous_limit = os.environ.get("MAVERICK_MAX_JSON_BODY_BYTES")
        try:
            with tempfile.TemporaryDirectory() as temp:
                repo_root = self._repo_root(temp)
                state = bootstrap_platform_state(start_path=repo_root)
                self._install_sidecar_app(repo_root, state)
                shutdown = EntrypointShutdownController()
                self.addCleanup(shutdown.begin_shutdown)
                app = PlatformAsgiHost(state, shutdown_controller=shutdown)
                cookie = await self._login_asgi(app)
                body_chunks = [b"x" * 17, b"y" * 19, b"z" * 28]

                os.environ["MAVERICK_MAX_JSON_BODY_BYTES"] = "16"
                status, body, headers = await self._invoke_asgi(
                    app,
                    path="/api/apps/sidecar-demo/sidecars/opendesign/api/upload",
                    method="POST",
                    body_chunks=body_chunks,
                    cookie=cookie,
                    headers={
                        "content-type": "application/octet-stream",
                        "content-length": str(sum(len(chunk) for chunk in body_chunks)),
                        "origin": "http://testserver",
                    },
                )
        finally:
            if previous_limit is None:
                os.environ.pop("MAVERICK_MAX_JSON_BODY_BYTES", None)
            else:
                os.environ["MAVERICK_MAX_JSON_BODY_BYTES"] = previous_limit

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["bytes_read"], 64)
        self.assertTrue(payload["technical_token_seen"])
        self.assertNotIn("authorization", {name.lower() for name in headers})

    async def _assert_asgi_sidecar_proxy_reencodes_unknown_length_request_body_as_chunked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo_root = self._repo_root(temp)
            state = bootstrap_platform_state(start_path=repo_root)
            self._install_sidecar_app(repo_root, state)
            shutdown = EntrypointShutdownController()
            self.addCleanup(shutdown.begin_shutdown)
            app = PlatformAsgiHost(state, shutdown_controller=shutdown)
            cookie = await self._login_asgi(app)
            status, body, _headers = await self._invoke_asgi(
                app,
                path="/api/apps/sidecar-demo/sidecars/opendesign/api/chunked-upload",
                method="POST",
                body_chunks=[b"abc", b"defgh", b"ijklmno"],
                cookie=cookie,
                headers={
                    "content-type": "application/octet-stream",
                    "origin": "http://testserver",
                },
                auto_content_length=False,
            )

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["bytes_read"], 15)
        self.assertTrue(payload["chunked"])

    def _repo_root(self, temp_dir: str) -> Path:
        repo_root = Path(temp_dir) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def _install_sidecar_app(self, repo_root: Path, state) -> None:
        app_root = repo_root / "apps" / "sidecar-demo"
        service_root = app_root / "service"
        service_root.mkdir(parents=True)
        (service_root / "server.py").write_text(TEST_SIDECAR_SERVER, encoding="utf-8")
        parsed = build_parsed_app_contract(
            app_id="sidecar-demo",
            name="Sidecar Demo",
            version="0.1.0",
            description="Sidecar proxy integration app.",
            publisher="maverick",
            contract=build_app_contract(
                services=build_app_services(
                    http_sidecars=[
                        build_http_sidecar_spec(
                            service_id="opendesign",
                            runtime="python",
                            working_directory="service",
                            command=["python3", "server.py"],
                            env={
                                "OD_BIND_HOST": "127.0.0.1",
                                "OD_PORT": "${service.port}",
                                "OD_API_TOKEN": "${service.token}",
                            },
                            bind=HttpSidecarBindSpec(host="127.0.0.1", port="auto"),
                            health=HttpSidecarHealthSpec(path="/api/ready", timeout_ms=5000),
                            proxy=build_http_sidecar_proxy(
                                mount="/opendesign",
                                streaming=True,
                                sse=True,
                                route_policy=build_http_sidecar_route_policy(
                                    pass_through=[
                                        build_http_sidecar_route_rule(method="GET", path_template="/"),
                                        build_http_sidecar_route_rule(method="GET", path_template="/api/events"),
                                        build_http_sidecar_route_rule(method="GET", path_template="/api/version"),
                                        build_http_sidecar_route_rule(method="POST", path_template="/api/upload"),
                                        build_http_sidecar_route_rule(method="POST", path_template="/api/chunked-upload"),
                                    ],
                                    handled_by_core=[
                                        build_http_sidecar_route_rule(
                                            method="POST",
                                            path_template="/api/provider/{operation}",
                                        ),
                                    ],
                                    blocked=[
                                        build_http_sidecar_route_rule(path_template="/api/import/folder"),
                                    ],
                                ),
                            ),
                            logs=build_http_sidecar_logs(
                                stdout="logs/apps/sidecar-demo/sidecar.log",
                                stderr="logs/apps/sidecar-demo/sidecar.log",
                            ),
                        )
                    ]
                )
            ),
        )
        write_app_contract_file(app_root, parsed)
        source = register_app_source_from_contract(
            state.app_store,
            source_kind="platform",
            source_path=str(app_root),
        )
        install_store_app(
            state.app_store,
            source_id=source.source_id,
            workspace_id="default",
            start_path=repo_root,
            observability_store=state.observability_store,
        )

    def _login(self, app: PlatformHost) -> str:
        status, _body, headers = self._invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={
                "username": "admin",
                "password": "maverick",
            },
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    async def _login_asgi(self, app: PlatformAsgiHost) -> str:
        status, _body, headers = await self._invoke_asgi(
            app,
            path="/api/auth/login",
            method="POST",
            body_chunks=[json.dumps({"username": "admin", "password": "maverick"}).encode("utf-8")],
            headers={"content-type": "application/json"},
        )
        self.assertEqual(status, 200)
        return headers["set-cookie"].split(";", 1)[0]

    def _invoke(
        self,
        app: PlatformHost,
        *,
        path: str,
        method: str = "GET",
        body: dict | None = None,
        cookie: str | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "wsgi.input": BytesIO(payload),
        }
        if cookie is not None:
            environ["HTTP_COOKIE"] = cookie

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        result = b"".join(app(environ, start_response))
        return int(headers["__status__"].split()[0]), result, headers

    async def _invoke_asgi(
        self,
        app: PlatformAsgiHost,
        *,
        path: str,
        method: str = "GET",
        body_chunks: list[bytes] | None = None,
        cookie: str | None = None,
        headers: dict[str, str] | None = None,
        auto_content_length: bool = True,
    ) -> tuple[int, bytes, dict[str, str]]:
        messages: list[dict] = []
        await self._invoke_asgi_streaming(
            app,
            path=path,
            method=method,
            body_chunks=body_chunks,
            cookie=cookie,
            headers=headers,
            auto_content_length=auto_content_length,
            messages=messages,
            queue=None,
        )
        start = next(message for message in messages if message["type"] == "http.response.start")
        body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
        decoded_headers = {
            name.decode("latin1").lower(): value.decode("latin1")
            for name, value in start.get("headers", [])
        }
        return int(start["status"]), body, decoded_headers

    async def _invoke_asgi_streaming(
        self,
        app: PlatformAsgiHost,
        *,
        path: str,
        method: str = "GET",
        body_chunks: list[bytes] | None = None,
        cookie: str | None = None,
        headers: dict[str, str] | None = None,
        auto_content_length: bool = True,
        messages: list[dict],
        queue: asyncio.Queue[dict] | None,
    ) -> None:
        chunks = list(body_chunks or [])
        header_map = {"host": "testserver", **(headers or {})}
        if cookie is not None:
            header_map["cookie"] = cookie
        if auto_content_length and chunks and "content-length" not in {key.lower() for key in header_map}:
            header_map["content-length"] = str(sum(len(chunk) for chunk in chunks))
        raw_headers = [(name.lower().encode("latin1"), value.encode("latin1")) for name, value in header_map.items()]
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "query_string": b"",
            "headers": raw_headers,
        }
        receive_index = 0

        async def receive() -> dict:
            nonlocal receive_index
            if not chunks:
                return {"type": "http.request", "body": b"", "more_body": False}
            chunk = chunks[receive_index]
            receive_index += 1
            return {
                "type": "http.request",
                "body": chunk,
                "more_body": receive_index < len(chunks),
            }

        async def send(message: dict) -> None:
            messages.append(message)
            if queue is not None:
                await queue.put(message)

        await app(scope, receive, send)

    async def _next_asgi_body(self, queue: asyncio.Queue[dict]) -> dict:
        while True:
            message = await asyncio.wait_for(queue.get(), timeout=3)
            if message["type"] == "http.response.body" and message.get("body"):
                return message
