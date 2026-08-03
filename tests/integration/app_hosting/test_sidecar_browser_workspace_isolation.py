"""Workspace isolation tests for governed sidecar browser origins."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from core.api.asgi_application import PlatformAsgiHost
from core.api.sidecar_browser import BROWSER_BOOTSTRAP_PATH
from core.apps.service import install_store_app, register_app_source_from_contract
from core.shared.entrypoints import EntrypointShutdownController
from tests.integration.app_hosting.sidecar_browser_origin_support import SidecarBrowserOriginTestSupport


class SidecarBrowserWorkspaceIsolationTests(SidecarBrowserOriginTestSupport, unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
