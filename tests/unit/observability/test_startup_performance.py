"""Tests for startup performance instrumentation helpers."""

from __future__ import annotations

import logging
import os
from unittest import TestCase
from unittest.mock import patch

from core.observability.startup_performance import (
    record_startup_timing,
    startup_performance_enabled,
    startup_timer,
)


class StartupPerformanceTests(TestCase):
    def test_instrumentation_is_opt_in(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(startup_performance_enabled())

        with patch.dict(os.environ, {"MAVERICK_STARTUP_PERF_LOGS": "1"}, clear=True):
            self.assertTrue(startup_performance_enabled())

    def test_record_returns_rounded_timing_when_disabled(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            timing = record_startup_timing("runtime.threads.payload", duration_ms=12.34567, thread_count=3)

        self.assertEqual(timing.name, "runtime.threads.payload")
        self.assertEqual(timing.duration_ms, 12.346)
        self.assertEqual(timing.payload["thread_count"], 3)

    def test_timer_logs_json_when_enabled(self) -> None:
        logger = logging.getLogger("maverick.startup")
        logger.setLevel(logging.INFO)
        with patch.dict(os.environ, {"MAVERICK_STARTUP_PERF_LOGS": "true"}, clear=True):
            with self.assertLogs("maverick.startup", level="INFO") as records:
                with startup_timer("frontend.asset", app_id="chat") as details:
                    details["bytes"] = 10

        line = "\n".join(records.output)
        self.assertIn("startup.performance", line)
        self.assertIn('"name":"frontend.asset"', line)
        self.assertIn('"app_id":"chat"', line)
