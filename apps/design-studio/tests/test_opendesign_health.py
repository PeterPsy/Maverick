"""Truthful launcher heartbeat and repair-state health proofs."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = ROOT / "apps/design-studio"
BACKEND_ROOT = APP_ROOT / "backend"
HOOK_PATH = APP_ROOT / "hooks/health_check.py"
sys.path.insert(0, str(BACKEND_ROOT))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


health_hook = _load("design_studio_health_hook_test", HOOK_PATH)
backend_service = _load("design_studio_backend_health_test", BACKEND_ROOT / "service.py")


class OpenDesignTruthfulHealthTests(unittest.TestCase):
    def test_launcher_claims_require_matching_live_core_manager_state(self) -> None:
        launcher = {
            "sidecar_process_running": True,
            "daemon_ready": True,
            "activation_committed": True,
            "browser_ready": True,
        }

        missing = health_hook._health_layers(
            artifact_ready=True,
            launcher_health=launcher,
            manager_status={"state": "not_started", "phase": "idle"},
        )
        ready = health_hook._health_layers(
            artifact_ready=True,
            launcher_health=launcher,
            manager_status={"state": "ready", "phase": "health_recheck"},
        )

        self.assertFalse(missing["sidecar_process_running"])
        self.assertFalse(missing["browser_ready"])
        self.assertTrue(ready["sidecar_process_running"])
        self.assertTrue(ready["browser_ready"])

    def test_false_health_payload_uses_a_failing_process_exit(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            health_hook._emit_health({"ok": False, "operational": False})

        self.assertEqual(raised.exception.code, 1)

    def test_install_artifact_gate_does_not_claim_browser_operational(self) -> None:
        payload = {
            "ok": True,
            "activation_gate": "artifact_ready",
            "health": health_hook._health_layers(artifact_ready=True),
        }

        health_hook._emit_health(payload)

        self.assertNotIn("operational", payload)
        self.assertFalse(payload["health"]["browser_ready"])

    def test_stale_launcher_heartbeat_cannot_report_browser_ready(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-health-") as temporary:
            status = Path(temporary) / "launcher-status.json"
            payload = {
                "schema_version": "3",
                "startup_id": "startup-test",
                "updated_at_epoch_ms": int((time.time() - 30) * 1000),
                "health": {
                    "sidecar_process_running": True,
                    "daemon_ready": True,
                    "activation_committed": True,
                    "browser_ready": True,
                },
            }
            status.write_text(json.dumps(payload), encoding="utf-8")

            observed = health_hook._launcher_status(status)

        self.assertFalse(observed["health"]["browser_ready"])
        self.assertEqual(observed["last_failure"]["code"], "daemon_ready_timeout")
        self.assertEqual(observed["last_failure"]["phase"], "launcher_heartbeat")

    def test_runtime_state_requires_a_fresh_heartbeat_and_idle_repair(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-runtime-health-") as temporary:
            data_root = Path(temporary)
            generation = data_root / "opendesign"
            generation.mkdir()
            runtime_digest = "a" * 64
            web_digest = "b" * 64
            status = {
                "schema_version": "3",
                "startup_id": "startup-test",
                "updated_at_epoch_ms": int(time.time() * 1000),
                "opendesign_version": backend_service.OPENDESIGN_VERSION,
                "opendesign_commit": backend_service.OPENDESIGN_COMMIT,
                "active": {
                    "runtime_artifact_sha256": runtime_digest,
                    "web_overlay_sha256": web_digest,
                    "od_version": backend_service.OPENDESIGN_VERSION,
                    "data_generation": "gen-test",
                },
                "runtime_artifact_sha256": runtime_digest,
                "web_overlay_sha256": web_digest,
                "bundle": {"location": "verified_registry", "relative_path": runtime_digest},
                "web_overlay": {"location": "verified_registry", "relative_path": web_digest},
                "bundle_configured": True,
                "mode": "oci-musl-runtime",
                "detail": "verified",
                "phase": "browser_ready",
                "health": {
                    "adapter_configured": True,
                    "artifact_available": True,
                    "artifact_verified": True,
                    "artifact_protected": True,
                    "repair_state": "idle",
                    "sidecar_process_running": True,
                    "daemon_ready": True,
                    "activation_committed": True,
                    "browser_ready": True,
                },
                "timings_ms": {},
                "last_failure": None,
            }
            status_path = generation / "launcher-status.json"
            status_path.write_text(json.dumps(status), encoding="utf-8")
            with patch.object(
                backend_service,
                "_opendesign_sidecar_manager_status",
                return_value={"state": "ready", "phase": "health_ready"},
            ):
                self.assertTrue(backend_service._opendesign_runtime_status(str(data_root))["operational"])

            (generation / "repair-state.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "state": "repairing",
                        "observed_at_epoch_ms": int(time.time() * 1000),
                        "error_code": None,
                        "phase": None,
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(
                backend_service,
                "_opendesign_sidecar_manager_status",
                return_value={"state": "ready", "phase": "health_ready"},
            ):
                self.assertFalse(backend_service._opendesign_runtime_status(str(data_root))["operational"])

            (generation / "repair-state.json").unlink()
            with patch.object(
                backend_service,
                "_opendesign_sidecar_manager_status",
                return_value={"state": "starting", "phase": "daemon_ready"},
            ):
                starting = backend_service._opendesign_runtime_status(str(data_root))
            self.assertFalse(starting["operational"])
            self.assertFalse(starting["health"]["browser_ready"])
            self.assertEqual(starting["sidecar_manager"]["phase"], "daemon_ready")


if __name__ == "__main__":
    unittest.main()
