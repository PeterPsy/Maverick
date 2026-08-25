"""Adaptive low-priority background artifact-audit proofs."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


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
