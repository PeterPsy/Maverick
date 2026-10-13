"""Real ASGI background delegation preserves app and platform authority."""

import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from core.api.app_frame_background import GRANT_PATH, REQUEST_PATH
from core.api.asgi_application import PlatformAsgiHost
from tests.integration.app_hosting.sidecar_browser_origin_support import SidecarBrowserOriginTestSupport
from tests.integration.app_hosting import test_app_frame_browser_origin as frame_fixtures


class AppBackgroundIntegrationTests(SidecarBrowserOriginTestSupport, unittest.TestCase):
    _bootstrap_app_frame = frame_fixtures.AppFrameBrowserOriginIntegrationTests._bootstrap_app_frame

    def test_background_transport_requires_exact_client_action_and_current_login(self):
        asyncio.run(self.assert_transport())

    async def assert_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._repo_root(Path(directory))
            state = frame_fixtures.AppFrameBrowserOriginIntegrationTests._state_with_frontend(root, include_backend=True)
            app = PlatformAsgiHost(state)
            platform_host = "maverick.localhost:8000"
            platform_origin = "http://" + platform_host
            cookie = await self._login(app, host=platform_host)
            frame = await self._bootstrap_app_frame(app, app_id="frame-demo", launch_path="/apps/frame-demo/", platform_host=platform_host, platform_origin=platform_origin, platform_cookie=cookie)
            client_origin = "chrome-extension://" + "a" * 32
            issue_body = json.dumps({"client_origin": client_origin, "actions": ["read"]}).encode()
            issue_headers = {"cookie": frame["cookie"], "content-type": "application/json", "origin": frame["origin"], "sec-fetch-site": "same-origin"}
            denied, _, _ = await self._invoke(app, host=frame["host"], path=GRANT_PATH, method="POST", body=issue_body, headers={**issue_headers, "origin": client_origin})
            self.assertEqual(denied, 403)
            status, body, headers = await self._invoke(app, host=frame["host"], path=GRANT_PATH, method="POST", body=issue_body, headers=issue_headers)
            self.assertEqual(status, 201, body)
            token = json.loads(body)["token"]
            self.assertEqual(headers["cache-control"], "no-store")
            request_headers = {"authorization": "Bearer " + token, "origin": client_origin, "content-type": "application/json"}
            for client, action, expected in [(client_origin, "read", 200), (client_origin, "write", 403), ("chrome-extension://" + "b" * 32, "read", 403), (platform_origin, "read", 403)]:
                status, body, headers = await self._invoke(app, host=frame["host"], path=REQUEST_PATH, method="POST", body=json.dumps({"action": action}).encode(), headers={**request_headers, "origin": client})
                self.assertEqual(status, expected, body)
                if expected == 200:
                    result = json.loads(body)
                    self.assertEqual(result["app_id"], "frame-demo")
                    self.assertEqual(result["workspace_id"], "default")
                    self.assertNotIn("authorization", result["headers"])
                    self.assertNotIn("set-cookie", headers)
            foreign, _, _ = await self._invoke(app, host="af-" + "0" * 24 + ".sidecars.maverick.localhost:8000", path=REQUEST_PATH, method="POST", body=b'{"action":"read"}', headers=request_headers)
            self.assertEqual(foreign, 403)
            status, body, _ = await self._invoke(app, host=frame["host"], path=GRANT_PATH, method="POST", body=issue_body, headers=issue_headers)
            self.assertEqual(status, 201, body)
            other_token = json.loads(body)["token"]
            other_headers = {**request_headers, "authorization": "Bearer " + other_token}
            status, _, _ = await self._invoke(app, host=frame["host"], path=REQUEST_PATH, method="DELETE", headers=other_headers)
            self.assertEqual(status, 200)
            status, _, _ = await self._invoke(app, host=frame["host"], path=REQUEST_PATH, method="POST", body=b'{"action":"read"}', headers=other_headers)
            self.assertEqual(status, 403)
            # Closing/expiring the setup document does not remove this scoped
            # authority. Logout still revokes it on the very next request.
            state.sidecar_browser_sessions._sessions.clear()
            status, body, _ = await self._invoke(app, host=frame["host"], path=REQUEST_PATH, method="POST", body=b'{"action":"read"}', headers=request_headers)
            self.assertEqual(status, 200, body)
            logout, _, _ = await self._invoke(app, host=platform_host, path="/api/auth/logout", method="POST", headers={"cookie": cookie, "origin": platform_origin})
            self.assertEqual(logout, 200)
            status, _, _ = await self._invoke(app, host=frame["host"], path=REQUEST_PATH, method="POST", body=b'{"action":"read"}', headers=request_headers)
            self.assertEqual(status, 403)
