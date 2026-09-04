"""Integration coverage for parent-bound cross-owner widget origins."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit

from core.api.app_frame_browser import APP_FRAME_BOOTSTRAP_PATH
from core.api.asgi_application import PlatformAsgiHost
from core.api.widget_browser_launch import WIDGET_BROWSER_LAUNCH_PATH
from tests.integration.app_hosting import test_app_frame_browser_origin as app_frame_fixtures
from tests.integration.app_hosting.sidecar_browser_origin_support import SidecarBrowserOriginTestSupport


class NestedWidgetBrowserOriginIntegrationTests(SidecarBrowserOriginTestSupport, unittest.TestCase):
    def test_nested_cross_owner_widget_uses_a_parent_bound_origin(self) -> None:
        asyncio.run(self._assert_nested_cross_owner_widget_launch())

    async def _assert_nested_cross_owner_widget_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(Path(temp_dir))
            state = app_frame_fixtures.AppFrameBrowserOriginIntegrationTests._state_with_frontend(
                repo_root,
                include_other_app=True,
            )
            app = PlatformAsgiHost(state)
            platform_host = "maverick.localhost:8000"
            platform_origin = f"http://{platform_host}"
            platform_cookie = await self._login(app, host=platform_host)
            parent = await app_frame_fixtures.AppFrameBrowserOriginIntegrationTests._bootstrap_app_frame(
                self,
                app,
                app_id="frame-demo",
                launch_path="/apps/frame-demo/",
                platform_host=platform_host,
                platform_origin=platform_origin,
                platform_cookie=platform_cookie,
            )

            context_status, context_body, _context_headers = await self._invoke(
                app,
                host=parent["host"],
                path="/api/apps/widgets/context",
                method="POST",
                body=json.dumps(
                    {
                        "host_app_id": "frame-host",
                        "owner_app_id": "other-demo",
                        "widget_id": "other-widget",
                        "message_id": "message-1",
                        "content": {"kind": "frame.demo", "payload": {"id": "demo"}},
                    }
                ).encode(),
                headers={
                    "content-type": "application/json",
                    "cookie": parent["cookie"],
                    "origin": parent["origin"],
                    "sec-fetch-site": "same-origin",
                },
            )
            self.assertEqual(context_status, 200)
            context_token = json.loads(context_body)["context_token"]
            request = {
                "context_token": context_token,
                "frontend_path": "/api/apps/widgets/other-demo/other-widget/frontend/",
                "owner_app_id": "other-demo",
                "widget_id": "other-widget",
            }

            direct_status, direct_body, _direct_headers = await self._invoke(
                app,
                host=platform_host,
                path=WIDGET_BROWSER_LAUNCH_PATH,
                method="POST",
                body=json.dumps(request).encode(),
                headers={
                    "content-type": "application/json",
                    "cookie": platform_cookie,
                    "origin": platform_origin,
                },
            )
            self.assertEqual(direct_status, 403)
            self.assertEqual(json.loads(direct_body), {"error": "nested_widget_parent_required"})

            tampered_status, tampered_body, _tampered_headers = await self._invoke(
                app,
                host=parent["host"],
                path=WIDGET_BROWSER_LAUNCH_PATH,
                method="POST",
                body=json.dumps({**request, "context_token": f"{context_token}x"}).encode(),
                headers=self._parent_headers(parent),
            )
            self.assertEqual(tampered_status, 403)
            self.assertEqual(json.loads(tampered_body), {"error": "widget_context_mismatch"})

            wrong_path_status, wrong_path_body, _wrong_path_headers = await self._invoke(
                app,
                host=parent["host"],
                path=WIDGET_BROWSER_LAUNCH_PATH,
                method="POST",
                body=json.dumps({
                    **request,
                    "frontend_path": "/api/apps/widgets/frame-demo/frame-widget/frontend/",
                }).encode(),
                headers=self._parent_headers(parent),
            )
            self.assertEqual(wrong_path_status, 404)
            self.assertEqual(json.loads(wrong_path_body), {"error": "widget_frame_unavailable"})

            undeclared_subpath_status, undeclared_subpath_body, _undeclared_subpath_headers = await self._invoke(
                app,
                host=parent["host"],
                path=WIDGET_BROWSER_LAUNCH_PATH,
                method="POST",
                body=json.dumps({
                    **request,
                    "frontend_path": f"{request['frontend_path']}undeclared",
                }).encode(),
                headers=self._parent_headers(parent),
            )
            self.assertEqual(undeclared_subpath_status, 404)
            self.assertEqual(
                json.loads(undeclared_subpath_body),
                {"error": "widget_frame_unavailable"},
            )

            wrong_parent_launch = await self._issue_launch(app, parent, request)
            nested_origin = wrong_parent_launch["origin"]
            nested_host = nested_origin.removeprefix("http://")
            self.assertNotEqual(nested_origin, parent["origin"])
            self.assertNotEqual(nested_origin, platform_origin)
            self.assertEqual(wrong_parent_launch["parent_origin"], parent["origin"])
            self.assertEqual(wrong_parent_launch["owner_app_id"], "other-demo")
            self.assertEqual(wrong_parent_launch["host_app_id"], "frame-host")
            self.assertEqual(wrong_parent_launch["widget_id"], "other-widget")
            self.assertEqual(
                wrong_parent_launch["bootstrap_url"],
                f"{nested_origin}{APP_FRAME_BOOTSTRAP_PATH}",
            )
            self.assertEqual(wrong_parent_launch["bootstrap_transport"], "cors")
            self.assertTrue(
                wrong_parent_launch["frontend_url"].startswith(
                    f"{nested_origin}/api/apps/widgets/other-demo/other-widget/frontend/#context="
                )
            )

            wrong_parent_status, _wrong_parent_body, wrong_parent_headers = await self._invoke(
                app,
                host=nested_host,
                path=APP_FRAME_BOOTSTRAP_PATH,
                method="POST",
                body=f"ticket={wrong_parent_launch['ticket']}".encode(),
                headers={
                    "content-type": "application/x-www-form-urlencoded",
                    "origin": "https://attacker.example",
                },
            )
            self.assertEqual(wrong_parent_status, 410)
            self.assertNotIn("access-control-allow-origin", wrong_parent_headers)

            spent_status, _spent_body, _spent_headers = await self._invoke(
                app,
                host=nested_host,
                path=APP_FRAME_BOOTSTRAP_PATH,
                method="POST",
                body=f"ticket={wrong_parent_launch['ticket']}".encode(),
                headers={
                    "content-type": "application/x-www-form-urlencoded",
                    "origin": parent["origin"],
                },
            )
            self.assertEqual(spent_status, 410)

            launch = await self._issue_launch(app, parent, request)
            bootstrap_status, _bootstrap_body, bootstrap_headers = await self._invoke(
                app,
                host=launch["origin"].removeprefix("http://"),
                path=APP_FRAME_BOOTSTRAP_PATH,
                method="POST",
                body=f"ticket={launch['ticket']}".encode(),
                headers={
                    "content-type": "application/x-www-form-urlencoded",
                    "origin": parent["origin"],
                },
            )
            self.assertEqual(bootstrap_status, 204)
            self.assertNotIn("location", bootstrap_headers)
            self.assertEqual(bootstrap_headers["access-control-allow-origin"], parent["origin"])
            self.assertEqual(bootstrap_headers["access-control-allow-credentials"], "true")
            self.assertEqual(bootstrap_headers["vary"], "Origin")
            nested_cookie = bootstrap_headers["set-cookie"].split(";", 1)[0]
            nested_csp = bootstrap_headers["content-security-policy"]
            self.assertIn(
                f"frame-ancestors 'self' {platform_origin} {parent['origin']}",
                nested_csp,
            )

            widget_status, widget_body, widget_headers = await self._invoke(
                app,
                host=launch["origin"].removeprefix("http://"),
                path=urlsplit(launch["frontend_url"]).path,
                headers={"cookie": nested_cookie},
            )
            self.assertEqual(widget_status, 200)
            self.assertIn(b"other-widget", widget_body)
            self.assertIn(b"maverick.app-frame.loaded", widget_body)
            self.assertIn(parent["origin"].encode(), widget_body)
            self.assertEqual(widget_headers["content-security-policy"], nested_csp)

            foreign_status, foreign_body, _foreign_headers = await self._invoke(
                app,
                host=launch["origin"].removeprefix("http://"),
                path="/apps/frame-demo/",
                headers={"cookie": nested_cookie},
            )
            self.assertEqual(foreign_status, 403)
            self.assertEqual(json.loads(foreign_body), {"error": "app_frame_owner_mismatch"})

    async def _issue_launch(self, app, parent: dict[str, str], request: dict[str, str]) -> dict:
        status, body, headers = await self._invoke(
            app,
            host=parent["host"],
            path=WIDGET_BROWSER_LAUNCH_PATH,
            method="POST",
            body=json.dumps(request).encode(),
            headers=self._parent_headers(parent),
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers["cache-control"], "private, no-store")
        return json.loads(body)

    @staticmethod
    def _parent_headers(parent: dict[str, str]) -> dict[str, str]:
        return {
            "content-type": "application/json",
            "cookie": parent["cookie"],
            "origin": parent["origin"],
            "sec-fetch-site": "same-origin",
        }


if __name__ == "__main__":
    unittest.main()
