"""Shared ASGI harness for isolated sidecar-browser origin tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import textwrap

from core.api.asgi_application import PlatformAsgiHost
from core.api.sidecar_browser import BROWSER_LAUNCH_PATH
from core.apps.contracts import (
    build_app_contract,
    build_app_services,
    build_http_sidecar_browser_origin,
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


class SidecarBrowserOriginTestSupport:
    """Reusable helpers; concrete unittest classes supply assertion methods."""

    async def _login(self, app: PlatformAsgiHost, *, host: str) -> str:
        status, _body, headers = await self._invoke(
            app,
            host=host,
            path="/api/auth/login",
            method="POST",
            body=json.dumps({"username": "admin", "password": "maverick"}).encode("utf-8"),
            headers={"content-type": "application/json"},
        )
        self.assertEqual(status, 200)
        return headers["set-cookie"].split(";", 1)[0]

    async def _launch(
        self,
        app: PlatformAsgiHost,
        *,
        platform_cookie: str,
        host: str,
        origin: str,
    ) -> tuple[int, dict, dict[str, str]]:
        status, body, headers = await self._invoke(
            app,
            host=host,
            path=BROWSER_LAUNCH_PATH,
            method="POST",
            body=json.dumps(
                {"app_id": "sidecar-browser-demo", "sidecar_id": "web", "path": "/api/projects"}
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "cookie": platform_cookie,
                "origin": origin,
            },
        )
        return status, json.loads(body.decode("utf-8")), headers

    async def _invoke(
        self,
        app: PlatformAsgiHost,
        *,
        host: str,
        path: str,
        method: str = "GET",
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        raw_path: bytes | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        messages: list[dict] = []
        await self._invoke_streaming(
            app,
            host=host,
            path=path,
            method=method,
            body=body,
            headers=headers,
            raw_path=raw_path,
            messages=messages,
            queue=None,
        )
        start = next(message for message in messages if message["type"] == "http.response.start")
        response_body = b"".join(
            message.get("body", b"") for message in messages if message["type"] == "http.response.body"
        )
        response_headers = {
            name.decode("latin1").lower(): value.decode("latin1") for name, value in start.get("headers", [])
        }
        return int(start["status"]), response_body, response_headers

    async def _invoke_streaming(
        self,
        app: PlatformAsgiHost,
        *,
        host: str,
        path: str,
        method: str = "GET",
        body: bytes = b"",
        headers: dict[str, str] | None,
        raw_path: bytes | None = None,
        messages: list[dict],
        queue: asyncio.Queue[dict] | None,
    ) -> None:
        header_map = {"host": host, **(headers or {})}
        if body:
            header_map["content-length"] = str(len(body))
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "query_string": b"",
            "headers": [
                (name.lower().encode("latin1"), value.encode("latin1")) for name, value in header_map.items()
            ],
        }
        if raw_path is not None:
            scope["raw_path"] = raw_path
        delivered = False

        async def receive() -> dict:
            nonlocal delivered
            if delivered:
                return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message: dict) -> None:
            messages.append(message)
            if queue is not None:
                await queue.put(message)

        await app(scope, receive, send)

    async def _next_body(self, queue: asyncio.Queue[dict]) -> dict:
        while True:
            message = await asyncio.wait_for(queue.get(), timeout=3)
            if message["type"] == "http.response.body" and message.get("body"):
                return message

    @staticmethod
    def _repo_root(temp_root: Path) -> Path:
        repo_root = temp_root / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    @staticmethod
    def _state_with_sidecar(repo_root: Path):
        from core.api.platform_state import bootstrap_platform_state

        state = bootstrap_platform_state(start_path=repo_root)
        app_root = repo_root / "apps" / "sidecar-browser-demo"
        service_root = app_root / "service"
        service_root.mkdir(parents=True)
        (service_root / "server.py").write_text(BROWSER_SIDECAR_SERVER, encoding="utf-8")
        parsed = build_parsed_app_contract(
            app_id="sidecar-browser-demo",
            name="Sidecar Browser Demo",
            version="0.1.0",
            description="Isolated browser origin integration fixture.",
            publisher="maverick",
            contract=build_app_contract(
                services=build_app_services(
                    http_sidecars=[
                        build_http_sidecar_spec(
                            service_id="web",
                            runtime="python",
                            working_directory="service",
                            command=["python3", "server.py"],
                            env={
                                "SIDECAR_PORT": "${service.port}",
                                "SIDECAR_TOKEN": "${service.token}",
                            },
                            browser_origin=build_http_sidecar_browser_origin(),
                            bind=HttpSidecarBindSpec(host="127.0.0.1", port="auto"),
                            health=HttpSidecarHealthSpec(path="/api/ready", timeout_ms=5000),
                            proxy=build_http_sidecar_proxy(
                                mount="/web",
                                streaming=True,
                                sse=True,
                                route_policy=build_http_sidecar_route_policy(
                                    pass_through=[
                                        build_http_sidecar_route_rule(method="GET", path_template="/api/projects"),
                                        build_http_sidecar_route_rule(method="POST", path_template="/api/projects"),
                                        build_http_sidecar_route_rule(method="GET", path_template="/api/events"),
                                    ],
                                    blocked=[
                                        build_http_sidecar_route_rule(path_template="/api/import/folder"),
                                    ],
                                ),
                            ),
                            logs=build_http_sidecar_logs(
                                stdout="logs/apps/sidecar-browser-demo/sidecar.log",
                                stderr="logs/apps/sidecar-browser-demo/sidecar.log",
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
        return state


BROWSER_SIDECAR_SERVER = textwrap.dedent(
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import json
    import os
    import time

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/ready":
                self._json({"status": "ready"})
                return
            if self.path == "/api/projects":
                self._json({
                    "surface": "sidecar",
                    "cookie_seen": bool(self.headers.get("Cookie")),
                    "technical_token_seen": self.headers.get("Authorization") == "Bearer " + os.environ["SIDECAR_TOKEN"],
                }, extra_headers=[
                    ("Set-Cookie", "daemon_cookie=must-not-cross; Path=/"),
                    ("Location", "https://evil.example/escape"),
                ])
                return
            if self.path == "/api/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b"data: one\\n\\n")
                self.wfile.flush()
                time.sleep(0.35)
                self.wfile.write(b"data: two\\n\\n")
                self.wfile.flush()
                return
            self._json({"error": "not_found"}, status=404)

        def do_POST(self):
            if self.path == "/api/projects":
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                self._json({"created": True, "cookie_seen": bool(self.headers.get("Cookie"))})
                return
            self._json({"error": "not_found"}, status=404)

        def _json(self, payload, status=200, extra_headers=()):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for name, value in extra_headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    ThreadingHTTPServer(("127.0.0.1", int(os.environ["SIDECAR_PORT"])), Handler).serve_forever()
    """
)
