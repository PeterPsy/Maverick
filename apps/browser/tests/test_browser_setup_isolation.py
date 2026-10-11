"""Browser setup assets through the real Core ASGI app-frame authorization."""

import asyncio
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from urllib.parse import urlsplit

from core.api.app_frame_browser import APP_FRAME_BOOTSTRAP_PATH, APP_FRAME_LAUNCH_PATH
from core.api.asgi_application import PlatformAsgiHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.contracts import (
    build_app_contract, build_app_entrypoints, build_parsed_app_contract,
    write_app_contract_file,
)
from core.apps.service import install_store_app, register_app_source_from_contract
from tests.integration.app_hosting.sidecar_browser_origin_support import SidecarBrowserOriginTestSupport


class BrowserSetupIsolationTests(SidecarBrowserOriginTestSupport, unittest.TestCase):
    def test_built_companion_and_connector_require_the_authenticated_isolated_origin(self):
        asyncio.run(self._assert_setup_routes())

    async def _assert_setup_routes(self):
        built = Path(__file__).resolve().parents[1] / "frontend/dist"
        with tempfile.TemporaryDirectory() as temporary:
            repo = self._repo_root(Path(temporary))
            state = bootstrap_platform_state(start_path=repo)
            source = repo / "apps/browser"
            shutil.copytree(built, source / "frontend/dist")
            write_app_contract_file(source, build_parsed_app_contract(
                app_id="browser", name="Browser", version="1.0.0",
                description="Browser setup frontend isolation acceptance.", publisher="maverick",
                contract=build_app_contract(entrypoints=build_app_entrypoints(frontend="frontend/dist")),
            ))
            record = register_app_source_from_contract(state.app_store, source_kind="platform", source_path=str(source))
            install_store_app(state.app_store, source_id=record.source_id, workspace_id="default",
                              start_path=repo, observability_store=state.observability_store)
            app = PlatformAsgiHost(state)
            host = "maverick.localhost:8000"
            cookie = await self._login(app, host=host)
            paths = ["/apps/browser/", "/apps/browser/maverick-browser-companion.zip"]
            for path in paths:
                status, body, _headers = await self._invoke(app, host=host, path=path, headers={"cookie": cookie})
                self.assertEqual(status, 403)
                self.assertIn(b"app_frame_isolation_required", body)
            status, body, _headers = await self._invoke(app, host=host, path=APP_FRAME_LAUNCH_PATH,
                method="POST", body=json.dumps({"app_id": "browser", "path": "/apps/browser/?connector=1"}).encode(),
                headers={"cookie": cookie, "origin": f"http://{host}", "content-type": "application/json"})
            self.assertEqual(status, 200)
            launch = json.loads(body)
            frame_host = urlsplit(launch["origin"]).netloc
            status, _body, headers = await self._invoke(app, host=frame_host, path=APP_FRAME_BOOTSTRAP_PATH,
                method="POST", body=f"ticket={launch['ticket']}".encode(),
                headers={"content-type": "application/x-www-form-urlencoded"})
            self.assertEqual(status, 303)
            self.assertEqual(headers["location"], "/apps/browser/?connector=1")
            self.assertIn("HttpOnly", headers["set-cookie"])
            self.assertIn("SameSite=Strict", headers["set-cookie"])
            frame_cookie = headers["set-cookie"].split(";", 1)[0]
            for path in paths:
                status, _body, _headers = await self._invoke(app, host=frame_host, path=path)
                self.assertEqual(status, 401)
                status, body, headers = await self._invoke(app, host=frame_host, path=path,
                    headers={"cookie": frame_cookie}, scope_extra={"query_string": b"connector=1"})
                self.assertEqual(status, 200)
                if path.endswith(".zip"):
                    self.assertEqual(body, (built / "maverick-browser-companion.zip").read_bytes())
                    self.assertIn("application/zip", headers["content-type"])
                else:
                    self.assertIn(b"__MAVERICK_PLATFORM_ORIGIN__", body)
                    self.assertIn(f'http://{host}/apps/browser/assets/'.encode(), body)


if __name__ == "__main__":
    unittest.main()
