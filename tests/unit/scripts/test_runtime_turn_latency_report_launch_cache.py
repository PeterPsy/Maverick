from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import tempfile
import unittest

from tests.unit.scripts.test_runtime_turn_latency_report import (
    BASE,
    _event,
    _turn_events,
    _write_events,
    _write_session,
    runtime_turn_latency_report,
)


class RuntimeTurnLatencyReportLaunchCacheTestCase(unittest.TestCase):
    def test_exposes_launch_cache_metrics_and_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "maverick"
            _write_session(root, "default", "sess-launch", runtime_mode="agentic", provider_id="codex")
            _write_events(
                root,
                "default",
                "sess-launch",
                [
                    *_turn_events(
                        "sess-launch",
                        "turn-launch",
                        BASE,
                        provider_id="codex",
                        ensure_runtime_ms=0.01,
                        ensure_provider_thread_ms=0.01,
                    ),
                    _event(
                        "dispatch-launch-cache",
                        "default",
                        "sess-launch",
                        "turn-launch-cache",
                        "runtime.provider.dispatching",
                        BASE + timedelta(minutes=1),
                        {
                            "provider_id": "codex",
                            "runtime_mode": "agentic",
                            "launch_cache_fingerprint_ms": 8,
                            "launch_cache_hit": False,
                            "launch_cache_fingerprint_prefix": "abc123def456",
                            "skill_count": 3,
                        },
                    ),
                ],
            )

            report = runtime_turn_latency_report.build_report(root, workspaces={"default"}, limit_turns=0, include_turns=True)

        turn = next(item for item in report["turns"] if item["turn_id"] == "turn-launch-cache")
        metrics = turn["metrics"]
        self.assertEqual(metrics["launch_cache_hit"], 0)
        self.assertEqual(metrics["launch_cache_fingerprint_ms"], 8)
        self.assertEqual(metrics["skill_count"], 3)
        self.assertEqual(turn["attributes"]["launch_cache_fingerprint_prefix"], "abc123def456")
        self.assertEqual(report["cohorts"]["codex_warm"]["metrics"]["launch_cache_hit"]["true_rate"], 0.0)
        self.assertEqual(report["cohorts"]["codex_warm"]["metrics"]["skill_count"]["p50"], 3)

    def test_associates_app_reference_prepare_with_next_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "maverick"
            _write_session(root, "default", "sess-prepare", runtime_mode="agentic", provider_id="codex")
            _write_events(
                root,
                "default",
                "sess-prepare",
                [
                    _event(
                        "refs-prepare",
                        "default",
                        "sess-prepare",
                        None,
                        "runtime.app_references.prepare_completed",
                        BASE - timedelta(milliseconds=250),
                        {
                            "provider_id": "codex",
                            "app_reference_prepare_ms": 120,
                            "app_reference_prepare_validate_ms": 5,
                            "app_reference_prepare_materialize_ms": 110,
                            "app_reference_count": 1,
                            "storage_reference_count": 1,
                            "materialized_reference_count": 1,
                            "reference_cache_hit": True,
                        },
                    ),
                    *_turn_events("sess-prepare", "turn-after-prepare", BASE, provider_id="codex"),
                ],
            )

            report = runtime_turn_latency_report.build_report(root, workspaces={"default"}, limit_turns=0, include_turns=True)

        metrics = report["turns"][0]["metrics"]
        self.assertEqual(metrics["app_reference_prepare_ms"], 120)
        self.assertEqual(metrics["app_reference_prepare_validate_ms"], 5)
        self.assertEqual(metrics["app_reference_prepare_materialize_ms"], 110)
        self.assertEqual(metrics["app_reference_prepare_cache_hit"], 1)
        self.assertEqual(metrics["storage_reference_count"], 1)


if __name__ == "__main__":
    unittest.main()
