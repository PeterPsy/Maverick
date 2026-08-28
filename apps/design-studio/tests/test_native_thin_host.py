"""Architecture tests for the thin, native OpenDesign host boundary."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = APP_ROOT / "service"
sys.path.insert(0, str(SERVICE_ROOT))


class NativeThinHostTests(unittest.TestCase):
    def test_contract_passes_native_product_routes_without_core_handlers(self) -> None:
        contract = json.loads((APP_ROOT / "app_contract.json").read_text(encoding="utf-8"))
        sidecar = contract["services"]["http_sidecars"][0]
        policy = sidecar["proxy"]["route_policy"]
        passed = {(route["method"], route["path_template"]) for route in policy["pass_through"]}

        self.assertEqual(policy["handled_by_core"], [])
        for route in {
            ("GET", "/api/app-config"),
            ("PUT", "/api/app-config"),
            ("POST", "/api/chat"),
            ("POST", "/api/provider/models"),
            ("GET", "/api/projects"),
            ("POST", "/api/projects"),
            ("POST", "/api/runs"),
            ("POST", "/api/runs/{id}/cancel"),
        }:
            self.assertIn(route, passed)
        self.assertFalse(contract["permissions"]["runtime"]["create_sessions"])
        self.assertFalse(contract["permissions"]["runtime"]["cleanup_sessions"])
        self.assertNotIn("runtime_event", contract["entrypoints"]["hooks"])
        self.assertEqual(contract["widgets"], [])

    def test_launcher_executes_official_rootfs_without_legacy_runtime_behavior(self) -> None:
        from opendesign_launcher import build_native_launch  # imported after path setup

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rootfs = root / "rootfs"
            data = root / "data"
            for relative in (
                "app/apps/daemon/dist/cli.js",
                "app/apps/web/out/index.html",
                "usr/local/bin/node",
                "lib/ld-musl-x86_64.so.1",
                "sbin/tini",
            ):
                path = rootfs / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("<title>Open Design</title>" if relative.endswith("index.html") else "official", encoding="utf-8")
            data.mkdir()

            command, env, cwd = build_native_launch(
                rootfs=rootfs,
                data_dir=data,
                host="127.0.0.1",
                port=17456,
                api_token="technical-token",
            )

        rendered = " ".join(command)
        self.assertEqual(command[0], "/sbin/tini")
        self.assertIn("/sbin/tini -- node apps/daemon/dist/cli.js --no-open", rendered)
        self.assertEqual(cwd, Path("/app"))
        self.assertEqual(env["OD_DATA_DIR"], str(data))
        self.assertEqual(env["OD_SANDBOX_MODE"], "1")
        self.assertNotIn("MAVERICK_RUNTIME_API_TOKEN", env)
        self.assertFalse(any("patch" in part.lower() or "overlay" in part.lower() for part in command))

    def test_frontend_is_only_a_launch_and_lifecycle_surface(self) -> None:
        source = (APP_ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")

        self.assertIn("requestOpenDesignLaunch", source)
        self.assertIn("<iframe", source)
        self.assertNotIn("createProject", source)
        self.assertNotIn("callDesignStudioBackend", source)
        self.assertNotIn("openSettingsMessage", source)
        self.assertNotIn("openToolsMessage", source)
        self.assertNotIn("maverick.opendesign.navigate", source)


if __name__ == "__main__":
    unittest.main()
