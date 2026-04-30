"""Tests for backend downtime watchdog escalation decisions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import StringIO
import json
from contextlib import redirect_stdout
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from core.recovery.backend_watchdog import (
    BackendWatchdogState,
    backend_downtime_seconds,
    mark_rescue_agent_blocked,
    mark_rescue_agent_started,
    record_backend_probe,
    should_start_rescue_agent,
)
from core.recovery.backend_rescue import build_backend_rescue_command, local_recovery_provider_store
from core.providers.service import configure_workspace_provider
from scripts.rescue_backend_watchdog import (
    DEFAULT_LOCK_FILE,
    DEFAULT_LOG_DIR,
    DEFAULT_STATE_FILE,
    main as rescue_watchdog_main,
)


class BackendWatchdogTestCase(unittest.TestCase):
    def test_default_operational_paths_do_not_use_maverick_local_state(self) -> None:
        defaults = (DEFAULT_STATE_FILE, DEFAULT_LOCK_FILE, DEFAULT_LOG_DIR)

        self.assertIn("tmp/recovery", DEFAULT_STATE_FILE)
        self.assertTrue(all(".maverick" not in path for path in defaults))
        self.assertTrue(all("local-state" not in path for path in defaults))

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

    def test_blocked_rescue_does_not_consume_rescue_cooldown(self) -> None:
        first = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)
        threshold_crossed = first + timedelta(seconds=300)
        state = record_backend_probe(BackendWatchdogState(), healthy=False, detail="timeout", now=first)

        state = mark_rescue_agent_blocked(
            state,
            reason="no_provider_configured",
            detail="no_provider_configured",
            now=threshold_crossed,
        )

        self.assertIsNone(state.last_rescue_started_at)
        self.assertEqual(state.last_blocked_reason, "no_provider_configured")
        self.assertTrue(
            should_start_rescue_agent(
                state,
                threshold_seconds=300,
                cooldown_seconds=1800,
                now=threshold_crossed + timedelta(seconds=1),
            )
        )

    def test_state_round_trip_preserves_timestamps(self) -> None:
        now = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)
        state = mark_rescue_agent_blocked(
            mark_rescue_agent_started(
                record_backend_probe(BackendWatchdogState(), healthy=False, detail="timeout", now=now),
                now=now + timedelta(seconds=300),
            ),
            reason="provider_unavailable",
            detail="missing backend recovery command",
            now=now + timedelta(seconds=301),
        )

        restored = BackendWatchdogState.from_dict(state.to_dict())

        self.assertEqual(restored, state)

    def test_recovery_command_is_derived_from_persisted_provider_selection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-rescue-provider-") as temp_dir:
            root = Path(temp_dir)
            store = local_recovery_provider_store(root)
            configure_workspace_provider(store, workspace_id="default", provider_id="codex", codex_command="/bin/echo")

            resolved = build_backend_rescue_command(
                repository_root=root,
                workspace_id="default",
                codex_command="/bin/echo",
            )

        self.assertEqual(resolved.provider_id, "codex")
        self.assertEqual(resolved.command[:4], ["/bin/echo", "exec", "--dangerously-bypass-approvals-and-sandbox", "--json"])
        self.assertIn("-C", resolved.command)
        self.assertIn(str(root), resolved.command)
        self.assertEqual(resolved.command[-1], "-")

    def test_raw_rescue_command_does_not_bypass_missing_provider_selection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-watchdog-") as temp_dir:
            root = Path(temp_dir)
            output = StringIO()
            with patch("scripts.rescue_backend_watchdog._probe_backend", return_value=(False, "down")), redirect_stdout(output):
                exit_code = rescue_watchdog_main(
                    [
                        "--repository-root",
                        str(root),
                        "--state-file",
                        str(root / "state.json"),
                        "--lock-file",
                        str(root / "lock"),
                        "--log-dir",
                        str(root / "logs"),
                        "--threshold-seconds",
                        "0",
                        "--rescue-command",
                        "/bin/echo",
                    ]
                )

            state = BackendWatchdogState.from_dict(json.loads((root / "state.json").read_text(encoding="utf-8")))

        payload = json.loads(output.getvalue().strip().splitlines()[-1])
        self.assertEqual(exit_code, 0)
        self.assertFalse(payload["rescue_started"])
        self.assertEqual(payload["blocked_reason"], "no_provider_configured")
        self.assertIsNone(state.last_rescue_started_at)
        self.assertEqual(state.last_blocked_reason, "no_provider_configured")

    def test_rescue_watchdog_blocks_without_configured_provider_command(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-watchdog-") as temp_dir:
            root = Path(temp_dir)
            output = StringIO()
            with patch("scripts.rescue_backend_watchdog._probe_backend", return_value=(False, "down")), redirect_stdout(output):
                exit_code = rescue_watchdog_main(
                    [
                        "--repository-root",
                        str(root),
                        "--state-file",
                        str(root / "state.json"),
                        "--lock-file",
                        str(root / "lock"),
                        "--log-dir",
                        str(root / "logs"),
                        "--threshold-seconds",
                        "0",
                    ]
                )

            state = BackendWatchdogState.from_dict(json.loads((root / "state.json").read_text(encoding="utf-8")))

        payload = json.loads(output.getvalue().strip().splitlines()[-1])
        self.assertEqual(exit_code, 0)
        self.assertFalse(payload["rescue_started"])
        self.assertEqual(payload["blocked_reason"], "no_provider_configured")
        self.assertIsNone(state.last_rescue_started_at)
        self.assertEqual(state.last_blocked_reason, "no_provider_configured")


if __name__ == "__main__":
    unittest.main()
