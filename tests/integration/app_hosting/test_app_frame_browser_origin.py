"""Integration coverage for per-app isolated browser origins."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from core.api.app_frame_browser import APP_FRAME_BOOTSTRAP_PATH, APP_FRAME_LAUNCH_PATH
from core.api.asgi_application import PlatformAsgiHost
from core.apps.contracts import (
    build_app_contract,
    build_app_entrypoints,
    build_parsed_app_contract,
    write_app_contract_file,
)
from core.apps.service import install_store_app, register_app_source_from_contract
from tests.integration.app_hosting.sidecar_browser_origin_support import SidecarBrowserOriginTestSupport


class AppFrameBrowserOriginIntegrationTests(SidecarBrowserOriginTestSupport, unittest.TestCase):
    def test_launch_bootstrap_authority_and_document_isolation(self) -> None:
        asyncio.run(self._assert_origin_contract())

    async def _assert_origin_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(Path(temp_dir))
            state = self._state_with_frontend(repo_root)
            app = PlatformAsgiHost(state)
            platform_host = "maverick.localhost:8000"
            platform_origin = f"http://{platform_host}"
            platform_cookie = await self._login(app, host=platform_host)

            anonymous_status, _anonymous_body, _anonymous_headers = await self._invoke(
                app,
                host=platform_host,
                path=APP_FRAME_LAUNCH_PATH,
                method="POST",
                body=json.dumps({"app_id": "frame-demo", "path": "/apps/frame-demo/"}).encode(),
                headers={"content-type": "application/json", "origin": platform_origin},
            )
            self.assertEqual(anonymous_status, 401)

            direct_status, direct_body, _direct_headers = await self._invoke(
                app,
                host=platform_host,
                path="/apps/frame-demo/",
                headers={"cookie": platform_cookie},
            )
            self.assertEqual(direct_status, 403)
            self.assertEqual(json.loads(direct_body)["error"], "app_frame_isolation_required")

            callback_status, callback_body, callback_headers = await self._invoke(
                app,
                host=platform_host,
                path="/apps/frame-demo/oauth/callback",
                headers={"cookie": platform_cookie},
            )
            self.assertEqual(callback_status, 200)
            self.assertIn(b"/api/app-frames/browser-launch", callback_body)
            self.assertIn("frame-ancestors 'none'", callback_headers["content-security-policy"])

            launch_status, launch_body, launch_headers = await self._invoke(
                app,
                host=platform_host,
                path=APP_FRAME_LAUNCH_PATH,
                method="POST",
                body=json.dumps({"app_id": "frame-demo", "path": "/apps/frame-demo/route?q=1"}).encode(),
                headers={
                    "content-type": "application/json",
                    "cookie": platform_cookie,
                    "origin": platform_origin,
                },
            )
            launch = json.loads(launch_body)
            self.assertEqual(launch_status, 200)
            self.assertEqual(launch_headers["cache-control"], "no-store")
            self.assertTrue(launch["origin"].startswith("http://af-"))
            self.assertTrue(launch["origin"].endswith(".sidecars.maverick.localhost:8000"))
            self.assertNotEqual(launch["origin"], platform_origin)
            self.assertEqual(launch["bootstrap_url"], launch["origin"] + APP_FRAME_BOOTSTRAP_PATH)
            self.assertNotIn(launch["ticket"], launch["bootstrap_url"])

            isolated_host = launch["origin"].removeprefix("http://")
            bootstrap_status, _bootstrap_body, bootstrap_headers = await self._invoke(
                app,
                host=isolated_host,
                path=APP_FRAME_BOOTSTRAP_PATH,
                method="POST",
                body=f"ticket={launch['ticket']}".encode(),
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            self.assertEqual(bootstrap_status, 303)
            self.assertEqual(bootstrap_headers["location"], "/apps/frame-demo/route?q=1")
            self.assertIn("maverick_app_frame_session=", bootstrap_headers["set-cookie"])
            self.assertIn("HttpOnly", bootstrap_headers["set-cookie"])
            self.assertIn("SameSite=Strict", bootstrap_headers["set-cookie"])
            self.assertNotIn("Domain=", bootstrap_headers["set-cookie"])
            isolated_cookie = bootstrap_headers["set-cookie"].split(";", 1)[0]

            replay_status, _replay_body, _replay_headers = await self._invoke(
                app,
                host=isolated_host,
                path=APP_FRAME_BOOTSTRAP_PATH,
                method="POST",
                body=f"ticket={launch['ticket']}".encode(),
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            self.assertEqual(replay_status, 410)

            html_status, html_body, html_headers = await self._invoke(
                app,
                host=isolated_host,
                path="/apps/frame-demo/route",
                headers={
                    "accept-encoding": "gzip, br",
                    "cookie": isolated_cookie,
                },
            )
            self.assertEqual(html_status, 200)
            self.assertIn(b"frame-demo", html_body)
            self.assertIn(b"__MAVERICK_PLATFORM_ORIGIN__", html_body)
            self.assertIn(b"maverick.shell.layout-changed", html_body)
            self.assertIn(b"--maverick-shell-mobile-content-top-offset", html_body)
            self.assertIn(platform_origin.encode(), html_body)
            self.assertNotIn("content-encoding", html_headers)
            self.assertEqual(html_headers["cache-control"], "private, no-store")
            self.assertEqual(html_headers["cross-origin-resource-policy"], "same-origin")
            self.assertEqual(html_headers["origin-agent-cluster"], "?1")
            self.assertIn(f"frame-ancestors 'self' {platform_origin}", html_headers["content-security-policy"])

            isolated_callback_status, isolated_callback_body, _isolated_callback_headers = await self._invoke(
                app,
                host=isolated_host,
                path="/apps/frame-demo/oauth/callback",
                headers={"cookie": isolated_cookie},
            )
            self.assertEqual(isolated_callback_status, 200)
            self.assertIn(b"frame-demo", isolated_callback_body)
            self.assertNotIn(b"/api/app-frames/browser-launch", isolated_callback_body)

            head_status, head_body, head_headers = await self._invoke(
                app,
                host=isolated_host,
                path="/apps/frame-demo/",
                method="HEAD",
                headers={"cookie": isolated_cookie},
            )
            self.assertEqual(head_status, 200)
            self.assertEqual(head_body, b"")
            self.assertEqual(head_headers["content-length"], "0")

            csrf_status, csrf_body, _csrf_headers = await self._invoke(
                app,
                host=isolated_host,
                path="/api/session/workspace",
                method="POST",
                body=b"{}",
                headers={
                    "content-type": "application/json",
                    "cookie": isolated_cookie,
                    "origin": "https://attacker.example",
                    "sec-fetch-site": "cross-site",
                },
            )
            self.assertEqual(csrf_status, 403)
            self.assertEqual(json.loads(csrf_body)["error"], "csrf_proof_required")

            session_status, session_body, session_headers = await self._invoke(
                app,
                host=isolated_host,
                path="/api/session",
                headers={
                    "cookie": f"{isolated_cookie}; maverick_session=attacker-value; app_cookie=kept",
                },
            )
            self.assertEqual(session_status, 200)
            self.assertEqual(json.loads(session_body)["workspace_id"], "default")
            self.assertEqual(session_headers["cache-control"], "private, no-store")

            foreign_host = "af-000000000000000000000000.sidecars.maverick.localhost:8000"
            foreign_status, _foreign_body, _foreign_headers = await self._invoke(
                app,
                host=foreign_host,
                path="/apps/frame-demo/",
                headers={"cookie": isolated_cookie},
            )
            self.assertEqual(foreign_status, 401)

            logout_status, _logout_body, _logout_headers = await self._invoke(
                app,
                host=platform_host,
                path="/api/auth/logout",
                method="POST",
                headers={"cookie": platform_cookie, "origin": platform_origin},
            )
            self.assertEqual(logout_status, 200)
            stale_status, _stale_body, _stale_headers = await self._invoke(
                app,
                host=isolated_host,
                path="/apps/frame-demo/",
                headers={"cookie": isolated_cookie},
            )
            self.assertEqual(stale_status, 401)

    @staticmethod
    def _state_with_frontend(repo_root: Path):
        from core.api.platform_state import bootstrap_platform_state

        state = bootstrap_platform_state(start_path=repo_root)
        app_root = repo_root / "apps" / "frame-demo"
        frontend_root = app_root / "frontend" / "dist"
        frontend_root.mkdir(parents=True)
        (frontend_root / "index.html").write_text(
            "<!doctype html><html><head><title>frame-demo</title></head><body>frame-demo</body></html>",
            encoding="utf-8",
        )
        parsed = build_parsed_app_contract(
            app_id="frame-demo",
            name="Frame Demo",
            version="1.0.0",
            description="Isolated app-frame integration fixture.",
            publisher="maverick",
            contract=build_app_contract(entrypoints=build_app_entrypoints(frontend="frontend/dist")),
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
