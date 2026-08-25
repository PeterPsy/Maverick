"""Lifecycle and typed-failure proofs for isolated sidecar browser launch."""

from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.api.asgi_application import PlatformAsgiHost
from core.api.platform_state import bootstrap_platform_state
from core.shared.entrypoints import EntrypointShutdownController
from tests.integration.app_hosting.sidecar_browser_origin_support import SidecarBrowserOriginTestSupport


class SidecarBrowserLaunchLifecycleTests(SidecarBrowserOriginTestSupport, unittest.TestCase):
    def test_ticket_store_failure_is_typed_only_after_transactional_health(self) -> None:
        asyncio.run(self._assert_ticket_store_failure_is_typed())

    async def _assert_ticket_store_failure_is_typed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(Path(temp_dir))
            state = self._state_with_sidecar(repo_root)
            shutdown = EntrypointShutdownController()
            self.addCleanup(shutdown.begin_shutdown)
            app = PlatformAsgiHost(state, shutdown_controller=shutdown)
            cookie = await self._login(app, host="maverick.localhost:8000")
            with patch.object(
                state.sidecar_browser_sessions,
                "issue_ticket",
                side_effect=RuntimeError("ticket store unavailable"),
            ):
                status, payload, _headers = await self._launch(
                    app,
                    platform_cookie=cookie,
                    host="maverick.localhost:8000",
                    origin="http://maverick.localhost:8000",
                )

            self.assertEqual(status, 503)
            self.assertEqual(payload["error"], "browser_ticket_failed")
            self.assertEqual(payload["phase"], "browser_ticket_issue")
            self.assertIs(payload["auto_repairable"], False)

    def test_cold_launch_after_host_restart_waits_for_declared_health_budget(self) -> None:
        asyncio.run(self._assert_cold_launch_after_host_restart())

    async def _assert_cold_launch_after_host_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(Path(temp_dir))
            state = self._state_with_sidecar(
                repo_root,
                startup_delay_seconds=0.4,
                health_timeout_ms=3000,
            )
            first_shutdown = EntrypointShutdownController()
            first_app = PlatformAsgiHost(state, shutdown_controller=first_shutdown)
            first_cookie = await self._login(first_app, host="maverick.localhost:8000")
            first_status, _launch, _headers = await self._launch(
                first_app,
                platform_cookie=first_cookie,
                host="maverick.localhost:8000",
                origin="http://maverick.localhost:8000",
            )
            self.assertEqual(first_status, 200)
            first_shutdown.begin_shutdown()

            restarted_state = bootstrap_platform_state(start_path=repo_root)
            restarted_shutdown = EntrypointShutdownController()
            self.addCleanup(restarted_shutdown.begin_shutdown)
            restarted_app = PlatformAsgiHost(
                restarted_state,
                shutdown_controller=restarted_shutdown,
            )
            restarted_cookie = await self._login(
                restarted_app,
                host="maverick.localhost:8000",
            )
            restarted_status, _launch, _headers = await self._launch(
                restarted_app,
                platform_cookie=restarted_cookie,
                host="maverick.localhost:8000",
                origin="http://maverick.localhost:8000",
            )
            self.assertEqual(restarted_status, 200)


if __name__ == "__main__":
    unittest.main()
