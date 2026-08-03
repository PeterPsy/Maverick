"""Integration tests for sidecar routes handled by app backends."""

from __future__ import annotations

import asyncio
from io import BytesIO
import json
from pathlib import Path
import tempfile
import textwrap
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.api.sidecar_core_routes import _send_core_sidecar_asgi_response
from core.apps.contracts import (
    build_app_contract,
    build_app_entrypoints,
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
from core.apps.service import install_store_app, register_app_source_from_contract
from core.shared.entrypoints import EntrypointShutdownController


class SidecarCoreRouteIntegrationTests(unittest.TestCase):
    def test_wp0_characterizes_handled_by_core_sse_as_one_buffered_response(self) -> None:
        messages: list[dict] = []

        async def send(message: dict) -> None:
            messages.append(message)

        asyncio.run(
            _send_core_sidecar_asgi_response(
                send,
                {
                    "status_code": 200,
                    "body": "event: message\ndata: one\n\nevent: message\ndata: two\n\n",
                },
            )
        )

        start = messages[0]
        bodies = [message for message in messages if message["type"] == "http.response.body"]
        self.assertEqual(dict(start["headers"])[b"content-type"], b"text/plain; charset=utf-8")
        self.assertIn(b"content-length", dict(start["headers"]))
        self.assertEqual(len(bodies), 1)
        self.assertFalse(bodies[0]["more_body"])

    def test_handled_by_core_route_invokes_app_backend_without_sidecar_passthrough(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo_root = self._repo_root(temp)
            state = bootstrap_platform_state(start_path=repo_root)
            self._install_app(repo_root, state)
            shutdown = EntrypointShutdownController()
            self.addCleanup(shutdown.begin_shutdown)
            app = PlatformHost(state, start_path=repo_root, shutdown_controller=shutdown)
            cookie = self._login(app)

            status, body, _headers = self._invoke(
                app,
                path="/api/apps/sidecar-core-demo/sidecars/opendesign/api/provider/chat",
                method="POST",
                body={"apiKey": "provider-secret", "prompt": "dashboard"},
                cookie=cookie,
            )

        payload = json.loads(body.decode("utf-8"))
        sidecar_log = repo_root / "workspaces" / "default" / "logs" / "apps" / "sidecar-core-demo" / "sidecar.log"
        self.assertEqual(status, 200)
        self.assertEqual(payload["surface"], "sidecar_core_handler")
        self.assertEqual(payload["route_path"], "/api/provider/chat")
        self.assertEqual(payload["body"]["prompt"], "dashboard")
        self.assertFalse(payload["sidecar_reached"])
        self.assertNotIn("authorization", payload["headers"])
        self.assertNotIn("cookie", payload["headers"])
        self.assertFalse(sidecar_log.exists())

    def _repo_root(self, temp_dir: str) -> Path:
        repo_root = Path(temp_dir) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def _install_app(self, repo_root: Path, state) -> None:
        app_root = repo_root / "apps" / "sidecar-core-demo"
        (app_root / "service").mkdir(parents=True)
        (app_root / "backend").mkdir(parents=True)
        (app_root / "service" / "server.py").write_text(_SIDECAR_SERVER, encoding="utf-8")
        (app_root / "backend" / "app_backend.py").write_text(_BACKEND, encoding="utf-8")
        parsed = build_parsed_app_contract(
            app_id="sidecar-core-demo",
            name="Sidecar Core Demo",
            version="0.1.0",
            description="Sidecar core route integration app.",
            publisher="maverick",
            contract=build_app_contract(
                entrypoints=build_app_entrypoints(backend="backend/app_backend.py"),
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
                                route_policy=build_http_sidecar_route_policy(
                                    handled_by_core=[build_http_sidecar_route_rule(path_prefix="/api/provider")],
                                ),
                            ),
                            logs=build_http_sidecar_logs(
                                stdout="logs/apps/sidecar-core-demo/sidecar.log",
                                stderr="logs/apps/sidecar-core-demo/sidecar.log",
                            ),
                        )
                    ]
                ),
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
            body={"username": "admin", "password": "maverick"},
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

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
            "HTTP_HOST": "testserver",
            "SERVER_NAME": "testserver",
        }
        if cookie is not None:
            environ["HTTP_COOKIE"] = cookie
            environ["HTTP_ORIGIN"] = "http://testserver"

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        result = b"".join(app(environ, start_response))
        return int(headers["__status__"].split()[0]), result, headers


_SIDECAR_SERVER = textwrap.dedent(
    """
    from __future__ import annotations

    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import json
    import os


    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/ready"):
                self._json({"status": "ready"})
                return
            if self.path.startswith("/api/provider"):
                self._json({"sidecar_reached": True})
                return
            self._json({"path": self.path}, status=404)

        def log_message(self, format, *args):
            return

        def _json(self, payload, status=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


    ThreadingHTTPServer((os.environ["OD_BIND_HOST"], int(os.environ["OD_PORT"])), Handler).serve_forever()
    """
)


_BACKEND = textwrap.dedent(
    """
    from __future__ import annotations

    import json
    import sys


    payload = json.loads(sys.stdin.read() or "{}")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
    print(json.dumps({
        "status_code": 200,
        "json": {
            "surface": payload.get("surface"),
            "route_path": payload.get("route_path"),
            "method": payload.get("method"),
            "body": body,
            "headers": headers,
            "sidecar_reached": False,
        },
    }))
    """
)


if __name__ == "__main__":
    unittest.main()
