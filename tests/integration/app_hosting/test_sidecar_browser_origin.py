"""Production-path integration tests for isolated sidecar browser origins."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from core.api.asgi_application import PlatformAsgiHost
from core.api.sidecar_browser import BROWSER_BOOTSTRAP_PATH
from core.api.sidecar_proxy import stop_app_sidecars
from core.shared.entrypoints import EntrypointShutdownController
from tests.integration.app_hosting.sidecar_browser_origin_support import SidecarBrowserOriginTestSupport


class SidecarBrowserOriginIntegrationTests(SidecarBrowserOriginTestSupport, unittest.TestCase):
    def test_post_bootstrap_cookie_csrf_headers_isolation_and_unbuffered_sse(self) -> None:
        asyncio.run(self._assert_browser_origin_contract())

    async def _assert_browser_origin_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(Path(temp_dir))
            state = self._state_with_sidecar(repo_root)
            shutdown = EntrypointShutdownController()
            self.addCleanup(shutdown.begin_shutdown)
            app = PlatformAsgiHost(state, shutdown_controller=shutdown)
            platform_origin = "http://maverick.localhost:8000"
            platform_cookie = await self._login(app, host="maverick.localhost:8000")

            bare_local_status, bare_local_payload, _headers = await self._launch(
                app,
                platform_cookie=platform_cookie,
                host="localhost:8000",
                origin="http://localhost:8000",
            )
            self.assertEqual(bare_local_status, 503)
            self.assertIn("SameSite=Strict", bare_local_payload["detail"])

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
                    host="maverick.localhost:8000",
                    origin=platform_origin,
                )
            self.assertEqual(hosted_status, 503)
            self.assertIn("require", hosted_payload["detail"].lower())

            launch_status, launch, launch_headers = await self._launch(
                app,
                platform_cookie=platform_cookie,
                host="maverick.localhost:8000",
                origin=platform_origin,
            )
            self.assertEqual(launch_status, 200)
            self.assertEqual(launch_headers["cache-control"], "no-store")
            self.assertEqual(launch_headers["referrer-policy"], "no-referrer")
            self.assertTrue(launch["origin"].startswith("http://sc-"))
            self.assertTrue(launch["origin"].endswith(".sidecars.maverick.localhost:8000"))
            self.assertEqual(launch["bootstrap_url"], launch["origin"] + BROWSER_BOOTSTRAP_PATH)
            self.assertNotIn(launch["ticket"], launch["bootstrap_url"])

            sidecar_host = launch["origin"].removeprefix("http://")
            wrong_host = "sc-workspace-b.sidecars.maverick.localhost:8000"
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
                host="maverick.localhost:8000",
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
            same_origin_payload = json.loads(same_origin_body.decode("utf-8"))
            self.assertEqual(same_origin_payload["created"], True)
            self.assertTrue(same_origin_payload["technical_origin_seen"])
            self.assertTrue(same_origin_payload["same_origin_fetch_seen"])

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
                host="maverick.localhost:8000",
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
            platform_cookie = await self._login(app, host="maverick.localhost:8000")
            status, launch, _headers = await self._launch(
                app,
                platform_cookie=platform_cookie,
                host="maverick.localhost:8000",
                origin="http://maverick.localhost:8000",
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
                host="maverick.localhost:8000",
                origin="http://maverick.localhost:8000",
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
                host="maverick.localhost:8000",
                origin="http://maverick.localhost:8000",
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


if __name__ == "__main__":
    unittest.main()
