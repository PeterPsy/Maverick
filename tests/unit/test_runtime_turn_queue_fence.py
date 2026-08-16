from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.runtime.turn_submission import submit_runtime_turn, submit_runtime_turn_async


class RuntimeTurnQueueFenceTest(unittest.TestCase):
    def test_sync_submission_queues_inside_caller_fence(self) -> None:
        self._assert_submission_queues_inside_fence(
            submit_runtime_turn,
            "core.runtime.turn_submission_service_submit._queue_turn_with_event_result",
        )

    def test_async_submission_queues_inside_caller_fence(self) -> None:
        self._assert_submission_queues_inside_fence(
            submit_runtime_turn_async,
            "core.runtime.turn_submission_service_runtime._queue_turn_with_event_result",
        )

    def _assert_submission_queues_inside_fence(self, submit, queue_patch_target: str) -> None:
        trace: list[str] = []

        @contextmanager
        def queue_fence():
            trace.append("fence.enter")
            try:
                yield
            finally:
                trace.append("fence.exit")

        def queue_turn(*_args, **_kwargs):
            trace.append("turn.queued")
            return SimpleNamespace(turn_id="existing-turn"), [], False

        session = SimpleNamespace(
            session_id="hidden-participant-session",
            runtime_mode="plain_hosted_chat",
            skill_ids=[],
        )
        with patch(queue_patch_target, side_effect=queue_turn):
            submit(
                SimpleNamespace(repository_root=None),
                session=session,
                input_text="fenced message",
                queue_fence=queue_fence,
            )

        self.assertEqual(trace, ["fence.enter", "turn.queued", "fence.exit"])


if __name__ == "__main__":
    unittest.main()
