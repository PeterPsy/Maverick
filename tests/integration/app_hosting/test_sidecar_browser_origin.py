"""Production-path integration tests for isolated sidecar browser origins."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from core.api.asgi_application import PlatformAsgiHost
from core.api.sidecar_browser import BROWSER_BOOTSTRAP_PATH, _resource_session_cookie, _session_cookie
from core.apps.sidecar_browser_sessions import SIDECAR_BROWSER_RESOURCE_COOKIE_NAME
from core.shared.entrypoints import EntrypointShutdownController
from tests.integration.app_hosting.sidecar_browser_origin_support import SidecarBrowserOriginTestSupport
from tests.integration.app_hosting.sidecar_origin_recovery_cases import SidecarOriginRecoveryCases
class SidecarBrowserOriginIntegrationTests(SidecarOriginRecoveryCases, SidecarBrowserOriginTestSupport, unittest.TestCase):
    def test_sandbox_resource_cookie_is_separate_and_scoped(self) -> None:
        strict = _session_cookie("strict-token", secure=True)
        stable = _session_cookie("stable-token", secure=True, stable=True)
        resource = _resource_session_cookie("resource-token")

        self.assertIn("SameSite=Strict", strict)
        self.assertIn("Max-Age=3600", stable)
        self.assertIn(f"{SIDECAR_BROWSER_RESOURCE_COOKIE_NAME}=", resource)
        self.assertIn("SameSite=None", resource)
        self.assertIn("Secure", resource)
        self.assertNotIn("Partitioned", resource)
        self.assertIn("Max-Age=3600", resource)

    def test_post_bootstrap_cookie_csrf_headers_isolation_and_unbuffered_sse(self) -> None:
        asyncio.run(self._assert_browser_origin_contract())

    def test_nested_app_frame_bootstrap_binds_the_exact_parent(self) -> None:
        asyncio.run(self._assert_nested_app_frame_bootstrap())


    async def _assert_browser_origin_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(Path(temp_dir))
            state = self._state_with_sidecar(
                repo_root,
                style_origins=["https://fonts.googleapis.com"],
                font_origins=["https://fonts.gstatic.com"],
            )
            shutdown = EntrypointShutdownController()
            self.addCleanup(shutdown.begin_shutdown)
            app = PlatformAsgiHost(state, shutdown_controller=shutdown)
            platform_origin = "http://loopino.localhost:8000"
            platform_cookie = await self._login(app, host="loopino.localhost:8000")

            bare_local_status, bare_local_payload, _headers = await self._launch(
                app,
                platform_cookie=platform_cookie,
                host="localhost:8000",
                origin="http://localhost:8000",
            )
            self.assertEqual(bare_local_status, 503)
            self.assertEqual(bare_local_payload["error"], "sidecar_origin_unavailable")
            self.assertEqual(bare_local_payload["phase"], "sidecar")
            self.assertNotIn("detail", bare_local_payload)

            unavailable_status, unavailable_payload, _headers = await self._launch(
                app,
                platform_cookie=platform_cookie,
                host="loopino.example",
                origin="http://loopino.example",
            )
            self.assertEqual(unavailable_status, 503)
            self.assertEqual(unavailable_payload["error"], "sidecar_origin_unavailable")

            with patch.dict(
                os.environ,
                {
                    "LOOPINO_SIDECAR_ORIGIN_MODE": "hosted",
                    "LOOPINO_SIDECAR_INSTALLATION_DOMAIN": "",
                    "LOOPINO_SIDECAR_PLATFORM_ORIGIN": "",
                },
                clear=False,
            ):
                hosted_status, hosted_payload, _headers = await self._launch(
                    app,
                    platform_cookie=platform_cookie,
                    host="loopino.localhost:8000",
                    origin=platform_origin,
                )
            self.assertEqual(hosted_status, 503)
            self.assertEqual(hosted_payload["error"], "sidecar_origin_unavailable")
            self.assertEqual(hosted_payload["phase"], "sidecar")
            self.assertNotIn("detail", hosted_payload)

            launch_status, launch, launch_headers = await self._launch(
                app,
                platform_cookie=platform_cookie,
                host="loopino.localhost:8000",
                origin=platform_origin,
            )
            self.assertEqual(launch_status, 200)
            self.assertEqual(launch_headers["cache-control"], "no-store")
            self.assertEqual(launch_headers["referrer-policy"], "no-referrer")
            self.assertTrue(launch["origin"].startswith("http://sc-"))
            self.assertTrue(launch["origin"].endswith(".sidecars.loopino.localhost:8000"))
            self.assertEqual(launch["bootstrap_url"], launch["origin"] + BROWSER_BOOTSTRAP_PATH)
            self.assertEqual(launch["bootstrap_transport"], "form")
            self.assertEqual(launch["parent_origin"], "")
            self.assertEqual(launch["target_url"], launch["origin"] + "/api/projects")
            self.assertNotIn(launch["ticket"], launch["bootstrap_url"])
            self.assertNotIn(launch["confirmation_token"], launch["bootstrap_url"])

            confirmation_status, confirmation, confirmation_headers = await self._launch_status(
                app,
                platform_cookie=platform_cookie,
                host="loopino.localhost:8000",
                origin=platform_origin,
                launch=launch,
            )
            self.assertEqual(confirmation_status, 200)
            self.assertEqual(confirmation, {"status": "pending"})
            self.assertEqual(confirmation_headers["cache-control"], "no-store")

            sidecar_host = launch["origin"].removeprefix("http://")
            wrong_host = "sc-workspace-b.sidecars.loopino.localhost:8000"
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
                host="loopino.localhost:8000",
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
            self.assertIn("loopino_sidecar_session=", bootstrap_headers["set-cookie"])
            self.assertIn(f"{SIDECAR_BROWSER_RESOURCE_COOKIE_NAME}=", bootstrap_headers["set-cookie"])
            self.assertIn("HttpOnly", bootstrap_headers["set-cookie"])
            self.assertIn("SameSite=Strict", bootstrap_headers["set-cookie"])
            self.assertIn("SameSite=None", bootstrap_headers["set-cookie"])
            self.assertIn("Secure", bootstrap_headers["set-cookie"])
            self.assertNotIn("Partitioned", bootstrap_headers["set-cookie"])
            self.assertNotIn("Domain=", bootstrap_headers["set-cookie"])
            self.assertNotIn(ticket, bootstrap_headers["set-cookie"])
            sidecar_cookie = bootstrap_headers["set-cookie"].split(";", 1)[0]
            resource_cookie = next(
                line.split(";", 1)[0]
                for line in bootstrap_headers["set-cookie"].splitlines()
                if line.startswith(f"{SIDECAR_BROWSER_RESOURCE_COOKIE_NAME}=")
            )

            confirmation_status, confirmation, _headers = await self._launch_status(
                app,
                platform_cookie=platform_cookie,
                host="loopino.localhost:8000",
                origin=platform_origin,
                launch=launch,
            )
            self.assertEqual(confirmation_status, 200)
            self.assertEqual(confirmation, {"status": "ready"})

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
            self.assertIn("style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;", csp)
            self.assertIn("font-src 'self' data: https://fonts.gstatic.com;", csp)
            self.assertIn("script-src 'self' 'unsafe-inline';", csp)
            self.assertIn(f"frame-ancestors 'self' {platform_origin}", csp)
            self.assertNotIn("frame-ancestors *", csp)
            self.assertEqual(projects_headers["cross-origin-resource-policy"], "same-origin")

            sandboxed_asset_status, sandboxed_asset_body, sandboxed_asset_headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/_sandbox/preview.png",
                headers={"cookie": resource_cookie},
            )
            self.assertEqual(sandboxed_asset_status, 200)
            self.assertEqual(sandboxed_asset_body, b"sandboxed-preview-image")
            self.assertEqual(
                sandboxed_asset_headers["cross-origin-resource-policy"],
                "cross-origin",
            )
            self.assertEqual(sandboxed_asset_headers["cache-control"], "no-store")

            resource_scope_status, _resource_scope_body, _resource_scope_headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/projects",
                headers={"cookie": resource_cookie},
            )
            self.assertEqual(resource_scope_status, 403)

            exact_asset_status, _exact_asset_body, exact_asset_headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/asset-cache",
                headers={"cookie": resource_cookie},
            )
            self.assertEqual(exact_asset_status, 200)
            self.assertEqual(exact_asset_headers["cross-origin-resource-policy"], "cross-origin")

            resource_method_status, _resource_method_body, _resource_method_headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/asset-cache",
                method="POST",
                headers={"cookie": resource_cookie},
            )
            self.assertEqual(resource_method_status, 403)

            collision_status, _collision_body, collision_headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/asset-cache-extra",
                headers={"cookie": sidecar_cookie},
            )
            self.assertEqual(collision_status, 200)
            self.assertEqual(collision_headers["cross-origin-resource-policy"], "same-origin")

            asset_status, asset_body, asset_headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/_next/static/chunks/app-deadbeef.js",
                headers={"cookie": sidecar_cookie},
            )
            self.assertEqual(asset_status, 200)
            self.assertIn(b"__sidecarAsset", asset_body)
            self.assertEqual(
                asset_headers["cache-control"],
                "private, max-age=31536000, immutable",
            )

            missing_asset_status, _missing_asset_body, missing_asset_headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/_next/static/chunks/missing-deadbeef.js",
                headers={"cookie": sidecar_cookie},
            )
            self.assertEqual(missing_asset_status, 404)
            self.assertEqual(missing_asset_headers["cache-control"], "no-store")

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
            self.assertNotIn(launch["confirmation_token"], serialized_audits)
            self.assertTrue(any(record.action == "sidecar.browser_ticket.issue" for record in audits))
            self.assertTrue(any(record.action == "sidecar.browser_session.bootstrap" for record in audits))
            proxy_audits = [record for record in audits if record.action == "sidecar.browser_request.proxy"]
            self.assertTrue(any(record.status == "succeeded" for record in proxy_audits))
            self.assertTrue(any(record.status == "failed" for record in proxy_audits))

            logout_status, _logout_body, _logout_headers = await self._invoke(
                app,
                host="loopino.localhost:8000",
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


if __name__ == "__main__":
    unittest.main()
