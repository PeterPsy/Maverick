"""SidecarOriginRecoveryCases fixtures extracted without changing assertions."""

from __future__ import annotations
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
from core.api.asgi_application import PlatformAsgiHost
from core.api.app_frame_scope import (
    APP_FRAME_APP_ID_SCOPE_KEY,
    APP_FRAME_MOUNT_APP_ID_SCOPE_KEY,
    APP_FRAME_ORIGIN_SCOPE_KEY,
    APP_FRAME_PROXY_SCOPE_KEY,
)
from core.api.sidecar_browser import BROWSER_BOOTSTRAP_PATH
from core.api.sidecar_proxy import stop_app_sidecars
from core.apps.sidecar_browser_sessions import SESSION_IDLE_TTL_SECONDS
from core.shared.entrypoints import EntrypointShutdownController


class SidecarOriginRecoveryCases:
    async def _assert_nested_app_frame_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(Path(temp_dir))
            state = self._state_with_sidecar(repo_root)
            shutdown = EntrypointShutdownController()
            self.addCleanup(shutdown.begin_shutdown)
            self.addCleanup(
                stop_app_sidecars,
                workspace_id="default",
                app_id="sidecar-browser-demo",
            )
            app = PlatformAsgiHost(state, shutdown_controller=shutdown)
            platform_host = "loopino.localhost:8000"
            platform_origin = f"http://{platform_host}"
            parent_origin = "http://af-parent.sidecars.loopino.localhost:8000"
            platform_cookie = await self._login(app, host=platform_host)
            parent_scope = {
                APP_FRAME_PROXY_SCOPE_KEY: True,
                APP_FRAME_APP_ID_SCOPE_KEY: "sidecar-browser-demo",
                APP_FRAME_MOUNT_APP_ID_SCOPE_KEY: "sidecar-browser-demo",
                APP_FRAME_ORIGIN_SCOPE_KEY: parent_origin,
            }

            launch_status, launch_body, _headers = await self._invoke(
                app,
                host=platform_host,
                path="/api/app-sidecars/browser-launch",
                method="POST",
                body=json.dumps(
                    {
                        "app_id": "sidecar-browser-demo",
                        "sidecar_id": "web",
                        "path": "/api/projects",
                    }
                ).encode("utf-8"),
                headers={
                    "content-type": "application/json",
                    "cookie": platform_cookie,
                    "origin": platform_origin,
                },
                scope_extra=parent_scope,
            )
            self.assertEqual(launch_status, 200)
            launch = json.loads(launch_body.decode("utf-8"))
            self.assertEqual(launch["bootstrap_transport"], "cors")
            self.assertEqual(launch["parent_origin"], parent_origin)
            self.assertEqual(launch["target_url"], launch["origin"] + "/api/projects")

            sidecar_host = launch["origin"].removeprefix("http://")
            bootstrap_status, _body, bootstrap_headers = await self._invoke(
                app,
                host=sidecar_host,
                path=BROWSER_BOOTSTRAP_PATH,
                method="POST",
                body=f"ticket={launch['ticket']}".encode("utf-8"),
                headers={
                    "content-type": "application/x-www-form-urlencoded",
                    "origin": parent_origin,
                },
            )
            self.assertEqual(bootstrap_status, 204)
            self.assertNotIn("location", bootstrap_headers)
            self.assertEqual(
                bootstrap_headers["access-control-allow-origin"],
                parent_origin,
            )
            self.assertEqual(
                bootstrap_headers["access-control-allow-credentials"],
                "true",
            )
            sidecar_cookie = bootstrap_headers["set-cookie"].split(";", 1)[0]

            projects_status, _body, projects_headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/projects",
                headers={"cookie": sidecar_cookie},
            )
            self.assertEqual(projects_status, 200)
            self.assertIn(
                f"frame-ancestors 'self' {platform_origin} {parent_origin}",
                projects_headers["content-security-policy"],
            )

            mismatched_status, mismatched_body, _headers = await self._invoke(
                app,
                host=platform_host,
                path="/api/app-sidecars/browser-launch",
                method="POST",
                body=json.dumps(
                    {
                        "app_id": "sidecar-browser-demo",
                        "sidecar_id": "web",
                        "path": "/api/projects",
                    }
                ).encode("utf-8"),
                headers={
                    "content-type": "application/json",
                    "cookie": platform_cookie,
                    "origin": platform_origin,
                },
                scope_extra={
                    **parent_scope,
                    APP_FRAME_APP_ID_SCOPE_KEY: "another-app",
                    APP_FRAME_MOUNT_APP_ID_SCOPE_KEY: "another-app",
                },
            )
            self.assertEqual(mismatched_status, 403)
            self.assertEqual(
                json.loads(mismatched_body.decode("utf-8"))["error"],
                "sidecar_parent_invalid",
            )

    async def _assert_expiry_and_restart_revocation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(Path(temp_dir))
            state = self._state_with_sidecar(repo_root)
            shutdown = EntrypointShutdownController()
            self.addCleanup(shutdown.begin_shutdown)
            app = PlatformAsgiHost(state, shutdown_controller=shutdown)
            platform_cookie = await self._login(app, host="loopino.localhost:8000")
            status, launch, _headers = await self._launch(
                app,
                platform_cookie=platform_cookie,
                host="loopino.localhost:8000",
                origin="http://loopino.localhost:8000",
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
                host="loopino.localhost:8000",
                origin="http://loopino.localhost:8000",
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

            idle_clock = time.monotonic()
            state.sidecar_browser_sessions._clock = lambda: idle_clock + SESSION_IDLE_TTL_SECONDS + 1
            after_idle_status, _body, _headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/projects",
                headers={"cookie": sidecar_cookie},
            )
            self.assertEqual(after_idle_status, 401)
            state.sidecar_browser_sessions._clock = time.monotonic
            status, launch, _headers = await self._launch(
                app,
                platform_cookie=platform_cookie,
                host="loopino.localhost:8000",
                origin="http://loopino.localhost:8000",
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
            after_idle_relaunch_status, _body, _headers = await self._invoke(
                app,
                host=sidecar_host,
                path="/api/projects",
                headers={"cookie": sidecar_cookie},
            )
            self.assertEqual(after_idle_relaunch_status, 200)

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
                host="loopino.localhost:8000",
                origin="http://loopino.localhost:8000",
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
            status, launch, _headers = await self._launch(
                app,
                platform_cookie=platform_cookie,
                host="loopino.localhost:8000",
                origin="http://loopino.localhost:8000",
            )
            self.assertEqual(status, 200)
            restarted_host = launch["origin"].removeprefix("http://")
            bootstrap_status, _body, bootstrap_headers = await self._invoke(
                app,
                host=restarted_host,
                path=BROWSER_BOOTSTRAP_PATH,
                method="POST",
                body=f"ticket={launch['ticket']}".encode("utf-8"),
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            self.assertEqual(bootstrap_status, 303)
            restarted_cookie = bootstrap_headers["set-cookie"].split(";", 1)[0]
            restarted_status, _body, _headers = await self._invoke(
                app,
                host=restarted_host,
                path="/api/projects",
                headers={"cookie": restarted_cookie},
            )
            self.assertEqual(restarted_status, 200)
