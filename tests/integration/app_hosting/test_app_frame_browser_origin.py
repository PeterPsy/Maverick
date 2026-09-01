"""Integration coverage for per-app isolated browser origins."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
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
            self.assertIn(
                f'src="{platform_origin}/apps/frame-demo/assets/app-contenthash.js"'.encode(),
                html_body,
            )
            self.assertIn(
                f'href="{platform_origin}/apps/frame-demo/assets/app-contenthash.css"'.encode(),
                html_body,
            )
            self.assertNotIn(b'src="/apps/frame-demo/assets/', html_body)
            self.assertNotIn(b'href="/apps/frame-demo/assets/', html_body)
            self.assertNotIn("content-encoding", html_headers)
            self.assertEqual(html_headers["cache-control"], "private, no-store")
            self.assertEqual(html_headers["cross-origin-resource-policy"], "same-origin")
            self.assertEqual(html_headers["origin-agent-cluster"], "?1")
            self.assertIn(f"frame-ancestors 'self' {platform_origin}", html_headers["content-security-policy"])

            asset_status, asset_body, asset_headers = await self._invoke(
                app,
                host=platform_host,
                path="/apps/frame-demo/assets/app-contenthash.js",
                headers={"accept-encoding": "gzip"},
            )
            self.assertEqual(asset_status, 200)
            self.assertEqual(gzip.decompress(asset_body), self._asset_source())
            self.assertEqual(asset_headers["content-encoding"], "gzip")
            self.assertEqual(asset_headers["vary"], "Accept-Encoding")
            self.assertEqual(asset_headers["cache-control"], "public, max-age=31536000, immutable")
            self.assertEqual(asset_headers["access-control-allow-origin"], "*")
            self.assertEqual(asset_headers["cross-origin-resource-policy"], "cross-origin")

            for asset_name, source, compressed in (
                ("pdf.worker-contenthash.mjs", self._worker_source(), True),
                ("count-down-contenthash.mp3", self._audio_source(), False),
                ("decoder-contenthash.wasm", self._wasm_source(), True),
            ):
                with self.subTest(asset_name=asset_name):
                    runtime_status, runtime_body, runtime_headers = await self._invoke(
                        app,
                        host=platform_host,
                        path=f"/apps/frame-demo/assets/{asset_name}",
                        headers={"accept-encoding": "gzip"},
                    )
                    self.assertEqual(runtime_status, 200)
                    self.assertEqual(runtime_headers["cache-control"], "public, max-age=31536000, immutable")
                    self.assertEqual(runtime_headers["access-control-allow-origin"], "*")
                    self.assertEqual(runtime_headers["cross-origin-resource-policy"], "cross-origin")
                    if compressed:
                        self.assertEqual(runtime_headers["content-encoding"], "gzip")
                        self.assertEqual(gzip.decompress(runtime_body), source)
                    else:
                        self.assertNotIn("content-encoding", runtime_headers)
                        self.assertEqual(runtime_body, source)

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
        assets_root = frontend_root / "assets"
        assets_root.mkdir()
        (assets_root / "app-contenthash.js").write_bytes(AppFrameBrowserOriginIntegrationTests._asset_source())
        (assets_root / "app-contenthash.css").write_text("body { color: currentColor; }", encoding="utf-8")
        (assets_root / "pdf.worker-contenthash.mjs").write_bytes(AppFrameBrowserOriginIntegrationTests._worker_source())
        (assets_root / "count-down-contenthash.mp3").write_bytes(AppFrameBrowserOriginIntegrationTests._audio_source())
        (assets_root / "decoder-contenthash.wasm").write_bytes(AppFrameBrowserOriginIntegrationTests._wasm_source())
        index_body = (
            "<!doctype html><html><head><title>frame-demo</title>"
            '<script type="module" crossorigin src="/apps/frame-demo/assets/app-contenthash.js"></script>'
            '<link rel="stylesheet" crossorigin href="/apps/frame-demo/assets/app-contenthash.css">'
            "</head><body>frame-demo</body></html>"
        )
        (frontend_root / "index.html").write_text(
            index_body,
            encoding="utf-8",
        )
        records = {
            relative: AppFrameBrowserOriginIntegrationTests._asset_record(frontend_root, relative)
            for relative in (
                "assets/app-contenthash.css",
                "assets/app-contenthash.js",
                "assets/count-down-contenthash.mp3",
                "assets/decoder-contenthash.wasm",
                "assets/pdf.worker-contenthash.mjs",
                "index.html",
            )
        }
        (frontend_root / "maverick-frontend-assets.json").write_text(
            json.dumps(
                {
                    "schema": "maverick.frontend-assets.v2",
                    "build_id": "a" * 64,
                    "entrypoints": ["index.html"],
                    "immutable": [
                        records["assets/app-contenthash.css"],
                        records["assets/app-contenthash.js"],
                        records["assets/count-down-contenthash.mp3"],
                        records["assets/decoder-contenthash.wasm"],
                        records["assets/pdf.worker-contenthash.mjs"],
                    ],
                    "revalidated": [records["index.html"]],
                }
            ),
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

    @staticmethod
    def _asset_source() -> bytes:
        return ("export const isolatedAsset = 'public-cache';\n" * 80).encode("utf-8")

    @staticmethod
    def _worker_source() -> bytes:
        return ("self.onmessage = () => self.postMessage('ready');\n" * 80).encode("utf-8")

    @staticmethod
    def _audio_source() -> bytes:
        return b"ID3" + bytes(range(256)) * 8

    @staticmethod
    def _wasm_source() -> bytes:
        return b"\x00asm\x01\x00\x00\x00" + b"\x00" * 2048

    @staticmethod
    def _asset_record(frontend_root: Path, relative: str) -> dict[str, object]:
        body = (frontend_root / relative).read_bytes()
        return {
            "path": relative,
            "sha256": hashlib.sha256(body).hexdigest(),
            "size_bytes": len(body),
        }
