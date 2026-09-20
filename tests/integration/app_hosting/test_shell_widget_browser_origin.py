"""Shell widgets do not require a launchable full-app frontend."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from core.api.app_frame_browser import APP_FRAME_LAUNCH_PATH
from core.api.asgi_application import PlatformAsgiHost
from core.api.widget_context import sign_widget_context
from tests.integration.app_hosting import test_app_frame_browser_origin as fixtures
from tests.integration.app_hosting.sidecar_browser_origin_support import SidecarBrowserOriginTestSupport


class ShellWidgetBrowserOriginTests(SidecarBrowserOriginTestSupport, unittest.TestCase):
    def test_supporting_widget_launch_bootstrap_and_revocation(self):
        asyncio.run(self._supporting_widget())

    async def _supporting_widget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._repo_root(Path(directory))
            state = fixtures.AppFrameBrowserOriginIntegrationTests._state_with_frontend(root)
            path = root / "apps/frame-demo/app_contract.json"
            contract = json.loads(path.read_text())
            contract["presentation"] = {"frontend_role": "supporting"}
            path.write_text(json.dumps(contract))
            app = PlatformAsgiHost(state)
            host = "maverick.localhost:8000"
            origin = "http://" + host
            cookie = await self._login(app, host=host)
            headers = {"cookie": cookie, "origin": origin, "content-type": "application/json"}
            status, body, _ = await self._invoke(app, host=host, path="/api/apps/widgets/context", method="POST", headers=headers,
                body=json.dumps({"host_app_id": "frame-host", "owner_app_id": "frame-demo", "widget_id": "frame-widget",
                                 "content": {"kind": "frame.demo", "payload": {"app_id": "crm"}}}).encode())
            self.assertEqual(status, 200, body)
            context = json.loads(body)
            widget_path = "/api/apps/widgets/frame-demo/frame-widget/frontend/"
            launch_path = widget_path + "?maverick_theme=dark#context=" + context["context_token"]

            async def launch(value, app_id="frame-demo"):
                return await self._invoke(app, host=host, path=APP_FRAME_LAUNCH_PATH, method="POST", headers=headers,
                    body=json.dumps({"app_id": app_id, "path": value}).encode())

            denied = ["/apps/frame-demo/", widget_path, widget_path + "#context=forged",
                      widget_path.replace("frame-widget", "missing") + "#context=" + context["context_token"],
                      launch_path + "&context=" + context["context_token"]]
            for key, value in (("user_id", "foreign-user"), ("workspace_id", "other"), ("owner_app_id", "foreign"),
                               ("widget_id", "foreign"), ("host_app_id", "foreign"), ("content", {"kind": "wrong.kind"})):
                denied.append(widget_path + "#context=" + sign_widget_context({**context["context"], key: value}))
            for value in denied:
                with self.subTest(path=value[:100]):
                    status, body, _ = await launch(value)
                    self.assertEqual(status, 404, body)
            status, body, _ = await launch(launch_path, "wrong-owner")
            self.assertEqual(status, 404, body)

            frame = await fixtures.AppFrameBrowserOriginIntegrationTests._bootstrap_app_frame(self, app, app_id="frame-demo",
                launch_path=launch_path, platform_host=host, platform_origin=origin, platform_cookie=cookie)
            status, body, _ = await self._invoke(app, host=frame["host"], path=widget_path, headers={"cookie": frame["cookie"]})
            self.assertEqual(status, 200, body)
            self.assertIn(b"frame-widget", body)
            self.assertIn(b"__MAVERICK_APP_FRAME_CONTEXT__", body)
            # Current declaration, not a past ticket, remains authoritative.
            contract["widgets"] = []
            path.write_text(json.dumps(contract))
            status, _body, _ = await self._invoke(app, host=frame["host"], path=widget_path, headers={"cookie": frame["cookie"]})
            self.assertEqual(status, 401)
