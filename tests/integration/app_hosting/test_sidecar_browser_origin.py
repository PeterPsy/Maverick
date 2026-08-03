"""Production-path integration tests for isolated sidecar browser origins."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import textwrap
import time
import unittest
from unittest.mock import patch

from core.api.asgi_application import PlatformAsgiHost
from core.api.sidecar_browser import BROWSER_BOOTSTRAP_PATH, BROWSER_LAUNCH_PATH
from core.api.sidecar_proxy import stop_app_sidecars
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
from core.shared.entrypoints import EntrypointShutdownController


class SidecarBrowserOriginIntegrationTests(unittest.TestCase):
    def test_post_bootstrap_cookie_csrf_headers_isolation_and_unbuffered_sse(self) -> None:
        asyncio.run(self._assert_browser_origin_contract())

    async def _assert_browser_origin_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(Path(temp_dir))
            state = self._state_with_sidecar(repo_root)
            shutdown = EntrypointShutdownController()
            self.addCleanup(shutdown.begin_shutdown)
            app = PlatformAsgiHost(state, shutdown_controller=shutdown)
            platform_origin = "http://localhost:8000"
            platform_cookie = await self._login(app, host="localhost:8000")

            unavailable_status, unavailable_payload, _headers = await self._launch(
                app,
                platform_cookie=platform_cookie,
                host="maverick.example",
                origin="http://maverick.example",
            )
            self.assertEqual(unavailable_status, 503)
            self.assertEqual(unavailable_payload["error"], "sidecar_origin_unavailable")

            with patch.dict(
                os.environ,
                {
                    "MAVERICK_SIDECAR_ORIGIN_MODE": "hosted",
                    "MAVERICK_SIDECAR_INSTALLATION_DOMAIN": "",
                    "MAVERICK_SIDECAR_PLATFORM_ORIGIN": "",
                },
                clear=False,
            ):
                hosted_status, hosted_payload, _headers = await self._launch(
                    app,
                    platform_cookie=platform_cookie,
                    host="localhost:8000",
                    origin=platform_origin,
                )
            self.assertEqual(hosted_status, 503)
            self.assertIn("require", hosted_payload["detail"].lower())

            launch_status, launch, launch_headers = await self._launch(
                app,
                platform_cookie=platform_cookie,
                host="localhost:8000",
                origin=platform_origin,
            )
            self.assertEqual(launch_status, 200)
            self.assertEqual(launch_headers["cache-control"], "no-store")
            self.assertEqual(launch_headers["referrer-policy"], "no-referrer")
            self.assertTrue(launch["origin"].startswith("http://sc-"))
            self.assertTrue(launch["origin"].endswith(".sidecars.localhost:8000"))
            self.assertEqual(launch["bootstrap_url"], launch["origin"] + BROWSER_BOOTSTRAP_PATH)
            self.assertNotIn(launch["ticket"], launch["bootstrap_url"])

            sidecar_host = launch["origin"].removeprefix("http://")
            wrong_host = "sc-workspace-b.sidecars.localhost:8000"
            wrong_status, _wrong_body, _wrong_headers = await self._invoke(
                app,
                host=wrong_host,
                path=BROWSER_BOOTSTRAP_PATH,
                method="POST",
                body=f"ticket={launch['ticket']}".encode("utf-8"),
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            self.assertEqual(wrong_status, 410)

            launch_status, launch, _headers = await self._launch(
                app,
                platform_cookie=platform_cookie,
                host="localhost:8000",
                origin=platform_origin,
            )
            self.assertEqual(launch_status, 200)
            ticket = launch["ticket"]
            sidecar_host = launch["origin"].removeprefix("http://")
            bootstrap_status, _bootstrap_body, bootstrap_headers = await self._invoke(
                app,
                host=sidecar_host,
                path=BROWSER_BOOTSTRAP_PATH,
                method="POST",
                body=f"ticket={ticket}".encode("utf-8"),
                headers={
                    "content-type": "application/x-www-form-urlencoded",
                    "cookie": f"{platform_cookie}; unrelated=must-not-cross",
                },
            )
            self.assertEqual(bootstrap_status, 303)
            self.assertEqual(bootstrap_headers["location"], "/api/projects")
            self.assertNotIn(ticket, bootstrap_headers["location"])
            self.assertIn("maverick_sidecar_session=", bootstrap_headers["set-cookie"])
            self.assertIn("HttpOnly", bootstrap_headers["set-cookie"])
            self.assertIn("SameSite=Strict", bootstrap_headers["set-cookie"])
            self.assertNotIn("Domain=", bootstrap_headers["set-cookie"])
            self.assertNotIn(ticket, bootstrap_headers["set-cookie"])
            sidecar_cookie = bootstrap_headers["set-cookie"].split(";", 1)[0]

            replay_status, _replay_body, _replay_headers = await self._invoke(
                app,
                host=sidecar_host,
                path=BROWSER_BOOTSTRAP_PATH,
                method="POST",
                body=f"ticket={ticket}".encode("utf-8"),
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            self.assertEqual(replay_status, 410)

            projects_status, projects_body, projects_headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/projects",
                headers={"cookie": f"{sidecar_cookie}; {platform_cookie}; injected=must-not-cross"},
            )
            projects = json.loads(projects_body.decode("utf-8"))
            self.assertEqual(projects_status, 200)
            self.assertEqual(projects["surface"], "sidecar")
            self.assertFalse(projects["cookie_seen"])
            self.assertTrue(projects["technical_token_seen"])
            self.assertNotIn("set-cookie", projects_headers)
            self.assertNotIn("location", projects_headers)
            self.assertEqual(projects_headers["referrer-policy"], "no-referrer")
            self.assertEqual(projects_headers["cache-control"], "no-store")
            csp = projects_headers["content-security-policy"]
            self.assertIn("connect-src 'self'", csp)
            self.assertIn(f"frame-ancestors {platform_origin}", csp)
            self.assertNotIn("frame-ancestors *", csp)

            core_status, _core_body, core_headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/status",
                headers={"cookie": sidecar_cookie},
            )
            self.assertEqual(core_status, 404)
            self.assertEqual(core_headers["referrer-policy"], "no-referrer")

            prefix_collision_status, _body, _headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/projects/project-a/terminals",
                headers={"cookie": sidecar_cookie},
            )
            encoded_slash_status, _body, _headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/projects/project-a/terminals",
                raw_path=b"/api/projects/project-a%2fterminals",
                headers={"cookie": sidecar_cookie},
            )
            double_encoded_status, _body, _headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/projects/%2fstatus",
                raw_path=b"/api/projects/%252fstatus",
                headers={"cookie": sidecar_cookie},
            )
            traversal_status, _body, _headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/projects/../status",
                raw_path=b"/api/projects/%2e%2e/status",
                headers={"cookie": sidecar_cookie},
            )
            self.assertEqual(prefix_collision_status, 404)
            self.assertEqual(encoded_slash_status, 400)
            self.assertEqual(double_encoded_status, 400)
            self.assertEqual(traversal_status, 400)

            duplicate_cookie_status, _body, _headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/projects",
                headers={"cookie": f"{sidecar_cookie}; {sidecar_cookie}"},
            )
            self.assertEqual(duplicate_cookie_status, 401)

            missing_origin_status, _body, _headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/projects",
                method="POST",
                body=b"{}",
                headers={"content-type": "application/json", "cookie": sidecar_cookie},
            )
            cross_origin_status, _body, _headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/projects",
                method="POST",
                body=b"{}",
                headers={
                    "content-type": "application/json",
                    "cookie": sidecar_cookie,
                    "origin": "http://evil.example",
                    "sec-fetch-site": "cross-site",
                },
            )
            same_origin_status, same_origin_body, _headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/projects",
                method="POST",
                body=b"{}",
                headers={
                    "content-type": "application/json",
                    "cookie": sidecar_cookie,
                    "origin": launch["origin"],
                    "sec-fetch-site": "same-origin",
                },
            )
            self.assertEqual(missing_origin_status, 403)
            self.assertEqual(cross_origin_status, 403)
            self.assertEqual(same_origin_status, 200)
            self.assertEqual(json.loads(same_origin_body.decode("utf-8"))["created"], True)

            messages: list[dict] = []
            queue: asyncio.Queue[dict] = asyncio.Queue()
            stream_task = asyncio.create_task(
                self._invoke_streaming(
                    app,
                    host=sidecar_host,
                    path="/api/events",
                    headers={"cookie": sidecar_cookie},
                    messages=messages,
                    queue=queue,
                )
            )
            start_message = await asyncio.wait_for(queue.get(), timeout=3)
            first_body = await self._next_body(queue)
            self.assertEqual(start_message["status"], 200)
            self.assertIn(b"data: one", first_body["body"])
            self.assertFalse(stream_task.done())
            await asyncio.wait_for(stream_task, timeout=3)
            stream_body = b"".join(
                message.get("body", b"") for message in messages if message["type"] == "http.response.body"
            )
            self.assertIn(b"data: two", stream_body)

            audits = state.observability_store.list_audit(source_domain="apps.sidecars.browser")
            serialized_audits = json.dumps([record.payload for record in audits])
            self.assertNotIn(ticket, serialized_audits)
            self.assertTrue(any(record.action == "sidecar.browser_ticket.issue" for record in audits))
            self.assertTrue(any(record.action == "sidecar.browser_session.bootstrap" for record in audits))
            proxy_audits = [record for record in audits if record.action == "sidecar.browser_request.proxy"]
            self.assertTrue(any(record.status == "succeeded" for record in proxy_audits))
            self.assertTrue(any(record.status == "failed" for record in proxy_audits))

            logout_status, _logout_body, _logout_headers = await self._invoke(
                app,
                host="localhost:8000",
                path="/api/auth/logout",
                method="POST",
                body=b"{}",
                headers={
                    "content-type": "application/json",
                    "cookie": platform_cookie,
                    "origin": platform_origin,
                },
            )
            self.assertEqual(logout_status, 200)
            after_logout_status, _body, _headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/projects",
                headers={"cookie": sidecar_cookie},
            )
            self.assertEqual(after_logout_status, 401)

    def test_ticket_expiry_and_sidecar_restart_revoke_session(self) -> None:
        asyncio.run(self._assert_expiry_and_restart_revocation())

    async def _assert_expiry_and_restart_revocation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(Path(temp_dir))
            state = self._state_with_sidecar(repo_root)
            shutdown = EntrypointShutdownController()
            self.addCleanup(shutdown.begin_shutdown)
            app = PlatformAsgiHost(state, shutdown_controller=shutdown)
            platform_cookie = await self._login(app, host="localhost:8000")
            status, launch, _headers = await self._launch(
                app,
                platform_cookie=platform_cookie,
                host="localhost:8000",
                origin="http://localhost:8000",
            )
            self.assertEqual(status, 200)
            sidecar_host = launch["origin"].removeprefix("http://")
            now = time.monotonic()
            state.sidecar_browser_sessions._clock = lambda: now + 31
            expired_status, _body, _headers = await self._invoke(
                app,
                host=sidecar_host,
                path=BROWSER_BOOTSTRAP_PATH,
                method="POST",
                body=f"ticket={launch['ticket']}".encode("utf-8"),
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            self.assertEqual(expired_status, 410)

            state.sidecar_browser_sessions._clock = time.monotonic
            status, launch, _headers = await self._launch(
                app,
                platform_cookie=platform_cookie,
                host="localhost:8000",
                origin="http://localhost:8000",
            )
            self.assertEqual(status, 200)
            sidecar_host = launch["origin"].removeprefix("http://")
            bootstrap_status, _body, bootstrap_headers = await self._invoke(
                app,
                host=sidecar_host,
                path=BROWSER_BOOTSTRAP_PATH,
                method="POST",
                body=f"ticket={launch['ticket']}".encode("utf-8"),
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            self.assertEqual(bootstrap_status, 303)
            sidecar_cookie = bootstrap_headers["set-cookie"].split(";", 1)[0]
            before_restart_status, _body, _headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/projects",
                headers={"cookie": sidecar_cookie},
            )
            self.assertEqual(before_restart_status, 200)

            binding = state.app_store.get_workspace_app_binding(
                workspace_id="default",
                app_id="sidecar-browser-demo",
            )
            state.app_store.save_workspace_app_binding(replace(binding, active_version="0.1.1"))
            generation_changed_status, _body, _headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/projects",
                headers={"cookie": sidecar_cookie},
            )
            self.assertEqual(generation_changed_status, 401)

            state.app_store.save_workspace_app_binding(binding)
            status, launch, _headers = await self._launch(
                app,
                platform_cookie=platform_cookie,
                host="localhost:8000",
                origin="http://localhost:8000",
            )
            self.assertEqual(status, 200)
            bootstrap_status, _body, bootstrap_headers = await self._invoke(
                app,
                host=sidecar_host,
                path=BROWSER_BOOTSTRAP_PATH,
                method="POST",
                body=f"ticket={launch['ticket']}".encode("utf-8"),
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            self.assertEqual(bootstrap_status, 303)
            sidecar_cookie = bootstrap_headers["set-cookie"].split(";", 1)[0]

            stop_app_sidecars(workspace_id="default", app_id="sidecar-browser-demo")
            after_restart_status, _body, _headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/projects",
                headers={"cookie": sidecar_cookie},
            )
            self.assertEqual(after_restart_status, 401)

    def test_workspace_switch_revokes_a_and_b_origins_remain_isolated(self) -> None:
        asyncio.run(self._assert_workspace_isolation())

    async def _assert_workspace_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(Path(temp_dir))
            state = self._state_with_sidecar(repo_root)
            shutdown = EntrypointShutdownController()
            self.addCleanup(shutdown.begin_shutdown)
            app = PlatformAsgiHost(state, shutdown_controller=shutdown)
            platform_origin = "http://localhost:8000"
            platform_cookie = await self._login(app, host="localhost:8000")

            status, launch_a, _headers = await self._launch(
                app,
                platform_cookie=platform_cookie,
                host="localhost:8000",
                origin=platform_origin,
            )
            self.assertEqual(status, 200)
            host_a = launch_a["origin"].removeprefix("http://")
            bootstrap_status, _body, headers = await self._invoke(
                app,
                host=host_a,
                path=BROWSER_BOOTSTRAP_PATH,
                method="POST",
                body=f"ticket={launch_a['ticket']}".encode("utf-8"),
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            self.assertEqual(bootstrap_status, 303)
            cookie_a = headers["set-cookie"].split(";", 1)[0]

            create_status, create_body, _headers = await self._invoke(
                app,
                host="localhost:8000",
                path="/api/workspaces",
                method="POST",
                body=json.dumps({"name": "Workspace B"}).encode("utf-8"),
                headers={
                    "content-type": "application/json",
                    "cookie": platform_cookie,
                    "origin": platform_origin,
                },
            )
            self.assertEqual(create_status, 201)
            workspace_b = json.loads(create_body.decode("utf-8"))["workspace_id"]
            source = register_app_source_from_contract(
                state.app_store,
                source_kind="platform",
                source_path=str(repo_root / "apps" / "sidecar-browser-demo"),
            )
            install_store_app(
                state.app_store,
                source_id=source.source_id,
                workspace_id=workspace_b,
                start_path=repo_root,
                observability_store=state.observability_store,
            )
            switch_status, _body, _headers = await self._invoke(
                app,
                host="localhost:8000",
                path="/api/workspaces/active",
                method="POST",
                body=json.dumps({"workspace_id": workspace_b}).encode("utf-8"),
                headers={
                    "content-type": "application/json",
                    "cookie": platform_cookie,
                    "origin": platform_origin,
                },
            )
            self.assertEqual(switch_status, 200)
            revoked_a_status, _body, _headers = await self._invoke(
                app,
                host=host_a,
                path="/api/projects",
                headers={"cookie": cookie_a},
            )
            self.assertEqual(revoked_a_status, 401)

            status, launch_b, _headers = await self._launch(
                app,
                platform_cookie=platform_cookie,
                host="localhost:8000",
                origin=platform_origin,
            )
            self.assertEqual(status, 200)
            host_b = launch_b["origin"].removeprefix("http://")
            self.assertNotEqual(host_a, host_b)
            bootstrap_status, _body, headers = await self._invoke(
                app,
                host=host_b,
                path=BROWSER_BOOTSTRAP_PATH,
                method="POST",
                body=f"ticket={launch_b['ticket']}".encode("utf-8"),
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            self.assertEqual(bootstrap_status, 303)
            cookie_b = headers["set-cookie"].split(";", 1)[0]
            cross_host_status, _body, _headers = await self._invoke(
                app,
                host=host_a,
                path="/api/projects",
                headers={"cookie": cookie_b},
            )
            own_host_status, _body, _headers = await self._invoke(
                app,
                host=host_b,
                path="/api/projects",
                headers={"cookie": cookie_b},
            )
            self.assertEqual(cross_host_status, 401)
            self.assertEqual(own_host_status, 200)

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

    def _repo_root(self, temp_root: Path) -> Path:
        repo_root = temp_root / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def _state_with_sidecar(self, repo_root: Path):
        from core.api.platform_state import bootstrap_platform_state

        state = bootstrap_platform_state(start_path=repo_root)
        app_root = repo_root / "apps" / "sidecar-browser-demo"
        service_root = app_root / "service"
        service_root.mkdir(parents=True)
        (service_root / "server.py").write_text(_BROWSER_SIDECAR_SERVER, encoding="utf-8")
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


_BROWSER_SIDECAR_SERVER = textwrap.dedent(
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


if __name__ == "__main__":
    unittest.main()
