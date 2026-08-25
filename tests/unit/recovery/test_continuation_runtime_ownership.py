from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.recovery.continuation_materialization import (
    close_predecessor_runtime_process,
    fence_predecessor_and_start_successor,
)


class RuntimeContinuationOwnershipTest(unittest.TestCase):
    def test_predecessor_runtime_closes_before_successor_starts(self) -> None:
        predecessor = SimpleNamespace(
            session_id="session-predecessor",
            status="running",
            execution_binding=SimpleNamespace(runtime_engine_id="codex"),
        )
        successor = SimpleNamespace(
            session_id="session-successor",
            status="created",
        )
        handoff = SimpleNamespace(
            predecessor_session_id=predecessor.session_id,
            successor_session_id=successor.session_id,
        )
        runtime_store = Mock()
        runtime_store.list_turns.return_value = []
        runtime_store.get_session.side_effect = lambda session_id: {
            predecessor.session_id: predecessor,
            successor.session_id: successor,
        }[session_id]
        state = SimpleNamespace(
            runtime_store=runtime_store,
            observability_store=None,
            repository_root=None,
        )
        lifecycle: list[str] = []

        def release_runtime(*_args, **_kwargs):
            lifecycle.append("predecessor_closed")
            return 1

        def transition(*_args, **kwargs):
            lifecycle.append(f"transition:{kwargs['target_status']}")

        with patch(
            "core.runtime.runtime_process_lifecycle.release_idle_runtime_processes",
            side_effect=release_runtime,
        ) as release, patch(
            "core.recovery.continuation_materialization.transition_runtime_session",
            side_effect=transition,
        ), patch(
            "core.recovery.continuation_materialization.runtime_processes_alive_for_session",
            return_value=False,
        ):
            close_predecessor_runtime_process(state, handoff)
            fence_predecessor_and_start_successor(
                state,
                handoff,
                now=datetime(2026, 8, 25, tzinfo=UTC),
            )

        release.assert_called_once_with(
            state,
            session_id=predecessor.session_id,
            provider_id="codex",
            reason="continuation_fork_predecessor_fenced",
            idle_ttl_seconds=0,
        )
        self.assertEqual(
            lifecycle,
            ["predecessor_closed", "transition:stopped", "transition:running"],
        )


if __name__ == "__main__":
    unittest.main()
