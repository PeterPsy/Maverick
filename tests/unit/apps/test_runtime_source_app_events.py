from __future__ import annotations

from pathlib import Path
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.apps import runtime_event_hooks


class RuntimeSourceAppEventsTestCase(unittest.TestCase):
    def test_async_source_app_runtime_event_does_not_wait_for_hook_completion(self) -> None:
        started = Event()
        release = Event()
        completed = Event()

        def slow_dispatch(*_args, **_kwargs):
            started.set()
            release.wait(timeout=1)
            completed.set()
            return {"ok": True}

        state = SimpleNamespace()
        session = SimpleNamespace(source_app_id="sensor-hub", session_id="sess-1", workspace_id="default")
        turn = SimpleNamespace(turn_id="turn-1", status="queued", failure_reason="")

        with patch.object(runtime_event_hooks, "dispatch_source_app_runtime_event", side_effect=slow_dispatch) as dispatch:
            scheduled = runtime_event_hooks.dispatch_source_app_runtime_event_async(
                state,
                session=session,
                turn=turn,
                event_type="runtime.turn.queued",
                start_path=Path("."),
            )

            self.assertTrue(scheduled)
            self.assertTrue(started.wait(timeout=0.5))
            self.assertFalse(completed.is_set())
            release.set()
            self.assertTrue(completed.wait(timeout=0.5))
            dispatch.assert_called_once()

    def test_async_source_app_runtime_event_skips_sessions_without_source_app(self) -> None:
        session = SimpleNamespace(source_app_id="", session_id="sess-1", workspace_id="default")
        turn = SimpleNamespace(turn_id="turn-1", status="queued", failure_reason="")

        with patch.object(runtime_event_hooks, "dispatch_source_app_runtime_event") as dispatch:
            scheduled = runtime_event_hooks.dispatch_source_app_runtime_event_async(
                SimpleNamespace(),
                session=session,
                turn=turn,
                event_type="runtime.turn.queued",
            )

        self.assertFalse(scheduled)
        dispatch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
