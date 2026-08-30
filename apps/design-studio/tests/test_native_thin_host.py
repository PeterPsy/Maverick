"""Architecture tests for the thin, native OpenDesign host boundary."""

from __future__ import annotations

import json
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch


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
        self.assertIn(("GET", "/{*native_path}"), passed)
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            self.assertIn((method, "/api/{*native_path}"), passed)
        for route in {
            ("GET", "/api/projects"),
            ("POST", "/api/projects"),
            ("POST", "/api/runs"),
            ("POST", "/api/runs/{id}/cancel"),
        }:
            self.assertIn(route, passed)
        self.assertFalse(contract["permissions"]["runtime"]["create_sessions"])
        self.assertFalse(contract["permissions"]["runtime"]["cleanup_sessions"])
        self.assertEqual(sidecar["model_access"], {"api": True, "cli": ["codex"], "required": False})
        self.assertEqual(sidecar["data_mount"], {"subpath": "opendesign-native"})
        self.assertEqual(
            sidecar["host_prepare"],
            {
                "entrypoint": "hooks/sidecar_prepare.py",
                "timeout_seconds": 30,
                "environment_keys": [
                    "MAVERICK_APP_OPENDESIGN_LAUNCH_CONFIGURATION"
                ],
            },
        )
        self.assertEqual(sidecar["env"]["MAVERICK_OPENDESIGN_DATA_DIR"], "${app.data_dir}")
        self.assertNotIn("root_filesystem", sidecar)
        self.assertGreaterEqual(sidecar["process_policy"]["limits"]["memory_bytes"], 32 * 1024**3)
        self.assertTrue(contract["permissions"]["providers"]["model_proxy"])
        self.assertFalse(contract["permissions"]["providers"]["deliver_secrets_to_app"])
        self.assertEqual(contract["entrypoints"]["hooks"]["upgrade"], "hooks/install.py")
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
        self.assertTrue(command[0].endswith("/lib/ld-musl-x86_64.so.1"))
        self.assertIn("/sbin/tini --", rendered)
        self.assertIn("/usr/local/bin/node", rendered)
        self.assertIn("/app/apps/daemon/dist/cli.js --no-open", rendered)
        self.assertEqual(cwd, rootfs / "app")
        self.assertEqual(env["OD_DATA_DIR"], str(data))
        self.assertEqual(env["OD_SANDBOX_MODE"], "1")
        self.assertNotIn("NODE_OPTIONS", env)
        self.assertNotIn("MAVERICK_RUNTIME_API_TOKEN", env)
        self.assertFalse(any("patch" in part.lower() or "overlay" in part.lower() for part in command))

    def test_launcher_exposes_only_a_technical_model_capability_to_open_design(self) -> None:
        from opendesign_launcher import build_native_launch
        from model_access_profiles import SANDBOX_PROFILE_PATH
        from opencode_runtime import SANDBOX_BINARY_PATH

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
                path.write_text("official", encoding="utf-8")
            data.mkdir()
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_MODEL_ACCESS_SOCKET": "/model-access/broker.sock",
                    "MAVERICK_MODEL_ACCESS_TOKEN": "scoped-technical-capability",
                },
            ):
                _command, env, _cwd = build_native_launch(
                    rootfs=rootfs,
                    data_dir=data,
                    host="127.0.0.1",
                    port=17456,
                    api_token="technical-token",
                    model_profile_path=SANDBOX_PROFILE_PATH,
                )

        self.assertEqual(env["OD_AGENT_PROFILES_CONFIG"], SANDBOX_PROFILE_PATH.as_posix())
        self.assertEqual(env["OD_ALLOWED_INTERNAL_HOSTS"], "127.0.0.1,localhost")
        self.assertEqual(env["NO_PROXY"], "*")
        self.assertEqual(env["OD_CODEX_DISABLE_PLUGINS"], "1")
        self.assertEqual(env["OD_CODEX_SANDBOX"], "danger-full-access")
        self.assertEqual(env["PATH"].split(":", 1)[0], "/app/service")
        self.assertFalse(any(part.startswith("/maverick/") for part in env["PATH"].split(":")))
        codex_wrapper = SERVICE_ROOT / "maverick-codex"
        opencode_wrapper = SERVICE_ROOT / "maverick-opencode"
        self.assertTrue(codex_wrapper.stat().st_mode & 0o111)
        self.assertTrue(opencode_wrapper.stat().st_mode & 0o111)
        for wrapper in (codex_wrapper, opencode_wrapper):
            source = wrapper.read_text(encoding="utf-8")
            self.assertTrue(source.startswith("#!/usr/bin/python3\n"))
            self.assertNotIn("/maverick/python", source)
            self.assertNotIn("/maverick/app", source)
        self.assertIn(SANDBOX_BINARY_PATH.as_posix(), opencode_wrapper.read_text())
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("MAVERICK_RUNTIME_API_TOKEN", env)
        self.assertNotIn("MAVERICK_API_BASE", env)
        self.assertFalse(any("memory" in value.lower() or "persona" in value.lower() for value in env.values()))

    def test_external_supervisor_marks_the_unchanged_official_process_ready(self) -> None:
        from official_process_supervisor import supervise_official_process

        class Process:
            def __init__(self) -> None:
                self.returncode = None

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                self.returncode = 0
                return self.returncode

            def send_signal(self, _signum):
                raise AssertionError("no signal expected")

            def terminate(self):
                raise AssertionError("ready process should already be reaped")

            def kill(self):
                raise AssertionError("ready process should already be reaped")

        class Bridge:
            stopped = False

            def stop(self):
                self.stopped = True

        process = Process()
        bridge = Bridge()
        states: list[tuple[str, int | None]] = []
        command = ["/official/ld.so", "/official/tini", "--", "/official/node"]
        environment = {"OD_DATA_DIR": "/data/opendesign-native"}
        cwd = Path("/official/app")
        with (
            patch("official_process_supervisor.subprocess.Popen", return_value=process) as launch,
            patch("official_process_supervisor.signal.getsignal", return_value=signal.SIG_DFL),
            patch("official_process_supervisor.signal.signal"),
            self.assertRaises(SystemExit) as exited,
        ):
            supervise_official_process(
                command,
                environment=environment,
                cwd=cwd,
                model_bridge=bridge,
                ready_probe=lambda: True,
                state_changed=lambda state, code: states.append((state, code)),
            )

        self.assertEqual(exited.exception.code, 0)
        launch.assert_called_once_with(command, cwd=cwd, env=environment)
        self.assertEqual(states, [("ready", None), ("stopped", 0)])
        self.assertTrue(bridge.stopped)

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
