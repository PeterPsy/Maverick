"""Adaptive low-priority background artifact-audit proofs."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[3]
HOOK_PATH = ROOT / "apps/design-studio/hooks/background_tick.py"
SERVICE_ROOT = ROOT / "apps/design-studio/service"
sys.path.insert(0, str(SERVICE_ROOT))


def _load_hook():
    spec = importlib.util.spec_from_file_location("design_studio_background_audit_test", HOOK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


background = _load_hook()


class OpenDesignBackgroundAuditTests(unittest.TestCase):
    def test_repair_state_redacts_untyped_exception_values(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-repair-state-") as temporary:
            root = Path(temporary)
            path = background.write_repair_state(
                root,
                state="failed",
                error_code="/private/runtime/path",
                phase="token=secret",
                observed_at_epoch_ms=123,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            mode = path.stat().st_mode & 0o777

        self.assertEqual(payload["error_code"], "artifact_repair_failed")
        self.assertEqual(payload["phase"], "artifact_repair")
        self.assertEqual(payload["observed_at_epoch_ms"], 123)
        self.assertEqual(mode, 0o600)

    def test_failed_audit_recovery_revokes_readiness_before_one_repair(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-background-repair-") as temporary:
            data_root = Path(temporary)
            ready_marker = data_root / "opendesign/maverick-ready.json"
            ready_marker.parent.mkdir()
            ready_marker.write_text("{}", encoding="utf-8")
            events: list[str] = []

            def state(_root, *, state, **_kwargs):
                events.append(f"state:{state}")

            def control(_root, *, operation, **_kwargs):
                events.append(f"control:{operation}")
                if operation == "restart":
                    return {"status": "ready", "readiness": {"ready": True}}
                return {"ready": False}

            def operation(name, **_kwargs):
                events.append(f"artifact:{name}")
                return {
                    "status": "ready",
                    "store_generation": "store-1",
                    "retained_runtime_artifacts": ["a" * 64, "b" * 64],
                    "retained_web_overlays": ["c" * 64],
                }

            with (
                patch.object(background, "write_repair_state", side_effect=state),
                patch.object(background, "request_sidecar_control", side_effect=control),
                patch.object(background, "run_artifact_operation", side_effect=operation),
            ):
                result = background._recover_failed_audit(
                    data_root=data_root,
                    workspace_id="default",
                )
            marker_removed = not ready_marker.exists()

        self.assertTrue(marker_removed)
        self.assertEqual(
            events,
            [
                "state:repairing",
                "control:stop",
                "artifact:repair",
                "control:restart",
                "state:idle",
            ],
        )
        self.assertEqual(result["runtime_count"], 2)
        self.assertEqual(result["web_count"], 1)

    def test_failed_recovery_is_persisted_and_suppressed_until_backoff(self) -> None:
        class RecoveryFailure(RuntimeError):
            code = "artifact_repair_failed"
            phase = "repair_source_verify"

        with tempfile.TemporaryDirectory(prefix="od-background-backoff-") as temporary:
            marker = Path(temporary) / "background-full-audit.json"
            emit = Mock()
            with (
                patch.object(background, "_recover_failed_audit", side_effect=RecoveryFailure()),
                patch.object(background, "emit_json", emit),
                self.assertRaises(SystemExit) as raised,
            ):
                background._handle_failed_audit(
                    RuntimeError("private audit detail"),
                    marker_path=marker,
                    data_root=Path(temporary) / "data",
                    workspace_id="default",
                    attempted_at_epoch_ms=1_000_000,
                )
            payload = json.loads(marker.read_text(encoding="utf-8"))
            with patch.object(background.time, "time", return_value=1_001):
                due = background._audit_due(marker)

        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(payload["status"], "failed")
        self.assertTrue(payload["auto_repair_requested"])
        self.assertEqual(payload["audit_error_code"], "artifact_integrity_mismatch")
        self.assertEqual(payload["recovery_error_code"], "artifact_repair_failed")
        self.assertEqual(payload["recovery_phase"], "repair_source_verify")
        self.assertNotIn("private audit detail", json.dumps(payload))
        self.assertFalse(due)
        self.assertFalse(emit.call_args.args[0]["ok"])

    def test_recovery_kill_leaves_a_persistent_repairing_backoff(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-background-kill-") as temporary:
            root = Path(temporary)
            marker = root / "background-full-audit.json"
            ready_marker = root / "data/opendesign/maverick-ready.json"
            ready_marker.parent.mkdir(parents=True)
            ready_marker.write_text("{}", encoding="utf-8")
            with (
                patch.object(background, "_recover_failed_audit", side_effect=SystemExit(9)),
                self.assertRaises(SystemExit) as raised,
            ):
                background._handle_failed_audit(
                    RuntimeError("audit failure"),
                    marker_path=marker,
                    data_root=root / "data",
                    workspace_id="default",
                    attempted_at_epoch_ms=2_000_000,
                )
            payload = json.loads(marker.read_text(encoding="utf-8"))
            with patch.object(background.time, "time", return_value=2_001):
                due = background._audit_due(marker)
            marker_removed = not ready_marker.exists()

        self.assertEqual(raised.exception.code, 9)
        self.assertEqual(payload["status"], "repairing")
        self.assertTrue(payload["auto_repair_requested"])
        self.assertFalse(due)
        self.assertTrue(marker_removed)

    def test_stop_failure_leaves_daemon_unready_and_does_not_mutate_store(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-background-stop-fail-") as temporary:
            data_root = Path(temporary)
            ready_marker = data_root / "opendesign/maverick-ready.json"
            ready_marker.parent.mkdir()
            ready_marker.write_text("{}", encoding="utf-8")
            artifact_operation = Mock()
            states: list[str] = []
            with (
                patch.object(
                    background,
                    "request_sidecar_control",
                    side_effect=RuntimeError("control unavailable"),
                ),
                patch.object(background, "run_artifact_operation", artifact_operation),
                patch.object(
                    background,
                    "write_repair_state",
                    side_effect=lambda _root, *, state, **_kwargs: states.append(state),
                ),
                self.assertRaises(RuntimeError),
            ):
                background._recover_failed_audit(
                    data_root=data_root,
                    workspace_id="default",
                )
            marker_removed = not ready_marker.exists()

        self.assertTrue(marker_removed)
        self.assertEqual(states, ["repairing", "failed"])
        artifact_operation.assert_not_called()

    def test_pressure_parser_is_bounded_and_fail_open(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-pressure-") as temporary:
            pressure = Path(temporary) / "cpu.pressure"
            pressure.write_text(
                "some avg10=12.50 avg60=3.00 avg300=1.00 total=100\n"
                "full avg10=0.25 avg60=0.10 avg300=0.01 total=10\n",
                encoding="ascii",
            )
            self.assertEqual(background._pressure_average(pressure, resource="some"), 12.5)
            self.assertEqual(background._pressure_average(pressure, resource="full"), 0.25)
            self.assertEqual(background._pressure_average(pressure.with_name("missing"), resource="some"), 0.0)

    def test_adaptive_audit_uses_one_worker_under_load(self) -> None:
        with (
            patch.object(background.os, "cpu_count", return_value=4),
            patch.object(background.os, "getloadavg", return_value=(4.0, 3.0, 2.0)),
            patch.object(background, "_pressure_average", return_value=0.0),
        ):
            self.assertEqual(background._adaptive_audit_workers(), 1)
        with (
            patch.object(background.os, "cpu_count", return_value=8),
            patch.object(background.os, "getloadavg", return_value=(0.5, 0.5, 0.5)),
            patch.object(background, "_pressure_average", return_value=0.0),
        ):
            self.assertEqual(background._adaptive_audit_workers(), 2)

    def test_priority_lowering_is_best_effort_and_requests_idle_io(self) -> None:
        with (
            patch.object(background.os, "nice", side_effect=OSError("denied")),
            patch.object(background.subprocess, "run") as run,
        ):
            background._lower_io_and_cpu_priority()
        self.assertEqual(run.call_args.args[0][:3], ["/usr/bin/ionice", "-c", "3"])


if __name__ == "__main__":
    unittest.main()
