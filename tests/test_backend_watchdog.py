"""Tests for backend downtime watchdog escalation decisions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from core.recovery.backend_watchdog import (
    BackendWatchdogState,
    backend_downtime_seconds,
    mark_rescue_agent_started,
    record_backend_probe,
    should_start_rescue_agent,
)


class BackendWatchdogTestCase(unittest.TestCase):
    def test_unhealthy_probe_starts_continuous_downtime_window(self) -> None:
        first = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)
        second = first + timedelta(seconds=120)

        state = record_backend_probe(BackendWatchdogState(), healthy=False, detail="connection refused", now=first)
        state = record_backend_probe(state, healthy=False, detail="connection refused", now=second)

        self.assertEqual(state.first_unhealthy_at, first)
        self.assertEqual(state.last_checked_at, second)
        self.assertEqual(state.last_status, "unhealthy")
        self.assertEqual(backend_downtime_seconds(state, now=second), 120)

    def test_healthy_probe_resets_downtime_window(self) -> None:
        first = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)
        recovered = first + timedelta(seconds=301)

        state = record_backend_probe(BackendWatchdogState(), healthy=False, detail="timeout", now=first)
        state = record_backend_probe(state, healthy=True, now=recovered)

        self.assertIsNone(state.first_unhealthy_at)
        self.assertEqual(state.last_healthy_at, recovered)
        self.assertEqual(state.last_status, "healthy")
        self.assertFalse(should_start_rescue_agent(state, now=recovered))

    def test_rescue_starts_after_threshold_and_respects_cooldown(self) -> None:
        first = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)
        threshold_crossed = first + timedelta(seconds=300)
        before_cooldown = threshold_crossed + timedelta(seconds=100)
        after_cooldown = threshold_crossed + timedelta(seconds=1800)

        state = record_backend_probe(BackendWatchdogState(), healthy=False, detail="timeout", now=first)

        self.assertFalse(should_start_rescue_agent(state, threshold_seconds=300, now=first + timedelta(seconds=299)))
        self.assertTrue(should_start_rescue_agent(state, threshold_seconds=300, now=threshold_crossed))

        state = mark_rescue_agent_started(state, now=threshold_crossed)

        self.assertFalse(
            should_start_rescue_agent(
                state,
                threshold_seconds=300,
                cooldown_seconds=1800,
                now=before_cooldown,
            )
        )
        self.assertTrue(
            should_start_rescue_agent(
                state,
                threshold_seconds=300,
                cooldown_seconds=1800,
                now=after_cooldown,
            )
        )

    def test_state_round_trip_preserves_timestamps(self) -> None:
        now = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)
        state = mark_rescue_agent_started(
            record_backend_probe(BackendWatchdogState(), healthy=False, detail="timeout", now=now),
            now=now + timedelta(seconds=300),
        )

        restored = BackendWatchdogState.from_dict(state.to_dict())

        self.assertEqual(restored, state)


if __name__ == "__main__":
    unittest.main()
