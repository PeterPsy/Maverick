"""Integration tests for governed app-owned HTTP sidecar proxying."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
import textwrap
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
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
from core.apps.service import install_store_app, register_app_source_from_contract
from core.shared.entrypoints import EntrypointShutdownController


class AppSidecarProxyIntegrationTests(unittest.TestCase):
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
                path="/api/apps/design-studio/sidecars/opendesign/api/version",
                cookie=cookie,
            )
            blocked_status, blocked_body, _blocked_headers = self._invoke(
                app,
                path="/api/apps/design-studio/sidecars/opendesign/api/import/folder",
                cookie=cookie,
            )

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["service"], "opendesign-test")
        self.assertTrue(payload["technical_token_seen"])
        self.assertEqual(blocked_status, 403)
        self.assertIn(b"sidecar_route_blocked", blocked_body)

    def _repo_root(self, temp_dir: str) -> Path:
        repo_root = Path(temp_dir) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def _install_sidecar_app(self, repo_root: Path, state) -> None:
        app_root = repo_root / "apps" / "design-studio"
        service_root = app_root / "service"
        service_root.mkdir(parents=True)
        (service_root / "server.py").write_text(_TEST_SIDECAR_SERVER, encoding="utf-8")
        parsed = build_parsed_app_contract(
            app_id="design-studio",
            name="Design Studio",
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
                                "OD_API_TOKEN": "${service_secret:od_api_token}",
                            },
                            bind=HttpSidecarBindSpec(host="127.0.0.1", port="auto"),
                            health=HttpSidecarHealthSpec(path="/api/ready", timeout_ms=5000),
                            proxy=build_http_sidecar_proxy(
                                mount="/opendesign",
                                route_policy=build_http_sidecar_route_policy(
                                    pass_through=[
                                        build_http_sidecar_route_rule(method="GET", path_prefix="/"),
                                    ],
                                    handled_by_core=[
                                        build_http_sidecar_route_rule(path_prefix="/api/provider"),
                                    ],
                                    blocked=[
                                        build_http_sidecar_route_rule(path_prefix="/api/import/folder"),
                                    ],
                                ),
                            ),
                            logs=build_http_sidecar_logs(
                                stdout="logs/apps/design-studio/sidecar.log",
                                stderr="logs/apps/design-studio/sidecar.log",
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


_TEST_SIDECAR_SERVER = textwrap.dedent(
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
            if self.path.startswith("/api/version"):
                expected = "Bearer " + os.environ.get("OD_API_TOKEN", "")
                self._json({
                    "service": "opendesign-test",
                    "technical_token_seen": self.headers.get("Authorization") == expected,
                })
                return
            if self.path.startswith("/api/import/folder"):
                self._json({"blocked": False})
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


    host = os.environ["OD_BIND_HOST"]
    port = int(os.environ["OD_PORT"])
    ThreadingHTTPServer((host, port), Handler).serve_forever()
    """
)
