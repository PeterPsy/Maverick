from __future__ import annotations

from types import SimpleNamespace
import unittest

from core.runtime.service import create_runtime_session, queue_runtime_turn
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.turn_submission import submit_runtime_turn_async
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


class TurnSubmissionPrewarmWaitTestCase(unittest.TestCase):
    def test_wait_for_session_prewarm_times_out_with_short_default_cap(self) -> None:
        repo_root = make_temp_repo_root(self)
        runtime_store = _runtime_store()
        session = create_runtime_session(
            runtime_store,
            session_id="sess-prewarm-timeout",
            workspace_id="default",
            agent_id="agent-1",
            start_path=repo_root,
        )
        turn = queue_runtime_turn(runtime_store, turn_id="turn-prewarm-timeout", session_id=session.session_id, input_text="hello")
        state = SimpleNamespace(runtime_store=runtime_store, runtime_event_bus=None)
        register_prewarm = submit_runtime_turn_async.__globals__["_register_session_prewarm"]
        complete_prewarm = submit_runtime_turn_async.__globals__["_complete_session_prewarm"]
        wait_for_prewarm = submit_runtime_turn_async.__globals__["_wait_for_session_prewarm"]
        default_timeout = submit_runtime_turn_async.__globals__["_PREWARM_JOIN_TIMEOUT_SECONDS"]
        prewarm = register_prewarm(session.session_id)
        self.assertIsNotNone(prewarm)
        assert prewarm is not None

        try:
            self.assertLessEqual(default_timeout, 0.3)
            self.assertFalse(
                wait_for_prewarm(
                    session.session_id,
                    state=state,
                    turn=turn,
                    provider_id="codex",
                    timeout_seconds=0.001,
                )
            )
        finally:
            complete_prewarm(session.session_id, prewarm)

        completed = next(
            event
            for event in runtime_store.list_events(session.session_id)
            if event.event_type == "runtime.turn.prewarm_wait_completed"
        )
        self.assertFalse(completed.payload["completed"])
        self.assertTrue(completed.payload["timed_out"])
        self.assertEqual(completed.payload["timeout_seconds"], 0.001)


def _runtime_store() -> RuntimeDocumentStore:
    return RuntimeDocumentStore(
        RuntimeCollections(
            sessions=FakeCollection(),
            turns=FakeCollection(),
            events=FakeCollection(),
            processes=FakeCollection(),
            states=FakeCollection(),
            threads=FakeCollection(),
        )
    )


if __name__ == "__main__":
    unittest.main()
