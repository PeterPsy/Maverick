"""Integration proof for managed exact TLS on generic sidecar origins."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.api.app_frame_browser import APP_FRAME_LAUNCH_PATH
from core.api.asgi_application import PlatformAsgiHost
from core.shared.browser_origin_tls import BrowserOriginTlsError
from core.shared.entrypoints import EntrypointShutdownController
from tests.integration.app_hosting.sidecar_browser_origin_support import (
    SidecarBrowserOriginTestSupport,
)


class ManagedBrowserOriginTlsIntegrationTests(
    SidecarBrowserOriginTestSupport,
    unittest.TestCase,
):
    def test_sidecar_certificate_is_ready_before_ticket_issuance(self) -> None:
        asyncio.run(self._assert_sidecar_certificate_gate())

    def test_app_frame_certificate_is_ready_before_ticket_issuance(self) -> None:
        asyncio.run(self._assert_app_frame_certificate_gate())

    async def _assert_app_frame_certificate_gate(self) -> None:
        from tests.integration.app_hosting.test_app_frame_browser_origin import (
            AppFrameBrowserOriginIntegrationTests,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(Path(temp_dir))
            state = AppFrameBrowserOriginIntegrationTests._state_with_frontend(repo_root)
            app = PlatformAsgiHost(state)
            host = "maverick.example.test"
            origin = f"https://{host}"
            cookie = await self._login(app, host=host, scheme="https")
            environment = {
                "MAVERICK_SIDECAR_ORIGIN_MODE": "hosted",
                "MAVERICK_SIDECAR_INSTALLATION_DOMAIN": host,
                "MAVERICK_SIDECAR_PLATFORM_ORIGIN": origin,
                "MAVERICK_BROWSER_ORIGIN_TLS_MODE": "managed_exact",
            }
            request_body = json.dumps(
                {"app_id": "frame-demo", "path": "/apps/frame-demo/"}
            ).encode()
            request_headers = {
                "content-type": "application/json",
                "cookie": cookie,
                "origin": origin,
            }
            with patch.dict(os.environ, environment, clear=False), patch(
                "core.api.app_frame_browser.ensure_browser_origin_tls"
            ) as ensure_tls:
                status, body, _headers = await self._invoke(
                    app,
                    host=host,
                    path=APP_FRAME_LAUNCH_PATH,
                    method="POST",
                    body=request_body,
                    headers=request_headers,
                    scheme="https",
                )
            launch = json.loads(body)
            self.assertEqual(status, 200)
            exact_host = launch["origin"].removeprefix("https://")
            self.assertIn(exact_host, ensure_tls.call_args.args[0])
            self.assertTrue(
                ensure_tls.call_args.kwargs["group_key"].startswith("app-frame-session:")
            )

            with patch.dict(os.environ, environment, clear=False), patch(
                "core.api.app_frame_browser.ensure_browser_origin_tls",
                side_effect=BrowserOriginTlsError("certificate unavailable"),
            ):
                failed_status, failed_body, _failed_headers = await self._invoke(
                    app,
                    host=host,
                    path=APP_FRAME_LAUNCH_PATH,
                    method="POST",
                    body=request_body,
                    headers=request_headers,
                    scheme="https",
                )
            self.assertEqual(failed_status, 503)
            self.assertEqual(json.loads(failed_body), {"error": "app_frame_tls_unavailable"})

    async def _assert_sidecar_certificate_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = self._state_with_sidecar(self._repo_root(Path(temp_dir)))
            shutdown = EntrypointShutdownController()
            self.addCleanup(shutdown.begin_shutdown)
            app = PlatformAsgiHost(state, shutdown_controller=shutdown)
            host = "maverick.example.test"
            origin = f"https://{host}"
            cookie = await self._login(app, host=host, scheme="https")
            environment = {
                "MAVERICK_SIDECAR_ORIGIN_MODE": "hosted",
                "MAVERICK_SIDECAR_INSTALLATION_DOMAIN": host,
                "MAVERICK_SIDECAR_PLATFORM_ORIGIN": origin,
                "MAVERICK_BROWSER_ORIGIN_TLS_MODE": "managed_exact",
            }
            with patch.dict(os.environ, environment, clear=False), patch(
                "core.api.sidecar_browser.ensure_browser_origin_tls"
            ) as ensure_tls:
                status, launch, _headers = await self._launch(
                    app,
                    platform_cookie=cookie,
                    host=host,
                    origin=origin,
                    scheme="https",
                )
            self.assertEqual(status, 200)
            exact_host = launch["origin"].removeprefix("https://")
            ensure_tls.assert_called_once_with(
                [exact_host],
                group_key=f"sidecar-installation:{host}",
                repository_root=state.repository_root,
            )

            with patch.dict(os.environ, environment, clear=False), patch(
                "core.api.sidecar_browser.ensure_browser_origin_tls",
                side_effect=BrowserOriginTlsError("certificate unavailable"),
            ):
                failed_status, failed, _failed_headers = await self._launch(
                    app,
                    platform_cookie=cookie,
                    host=host,
                    origin=origin,
                    scheme="https",
                )
            self.assertEqual(failed_status, 503)
            self.assertEqual(failed["error"], "sidecar_origin_unavailable")
            self.assertNotIn("detail", failed)


if __name__ == "__main__":
    unittest.main()
