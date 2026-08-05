from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
import unittest

from core.runtime.errors import RuntimeTransitionError
from core.runtime.event_collection import RuntimeEventJsonCollection
from core.runtime.service import (
    create_runtime_session,
    queue_runtime_turn,
    transition_runtime_session,
    transition_runtime_turn,
)
from core.runtime.session_collection import RuntimeSessionJsonCollection
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.workspace_collection import WorkspaceRuntimeJsonCollection
from tests.support.repo import make_temp_repo_root


class RuntimeTurnActivationFenceTest(unittest.TestCase):
    def test_persisted_cancel_wins_while_stale_activation_waits_on_session_handoff(self) -> None:
        repo_root = make_temp_repo_root(self)
        first_store = _runtime_store(repo_root)
        second_store = _runtime_store(repo_root)
        session = create_runtime_session(
            first_store,
            session_id="session-activation-cas",
            workspace_id="default",
            agent_id="chat",
            start_path=repo_root,
        )
        session = transition_runtime_session(
            first_store,
            session_id=session.session_id,
            target_status="running",
        )
        turn = queue_runtime_turn(
            first_store,
            turn_id="turn-activation-cas",
            session_id=session.session_id,
            input_text="must remain cancelled",
        )
        activation_returned = Event()
        activation_errors: list[BaseException] = []

        def activate_from_stale_reader() -> None:
            try:
                transition_runtime_turn(
                    second_store,
                    turn_id=turn.turn_id,
                    target_status="active",
                )
            except BaseException as error:  # pragma: no cover - asserted below
                activation_errors.append(error)
            finally:
                activation_returned.set()

        with first_store.session_lifecycle_handoff(
            workspace_id=session.workspace_id,
            session_id=session.session_id,
        ):
            activation_thread = Thread(target=activate_from_stale_reader)
            activation_thread.start()
            self.assertFalse(activation_returned.wait(timeout=0.1))
            first_store.save_turn(replace(turn, status="cancelled"))
            first_store.save_session(replace(session, status="stopped"))

        activation_thread.join(timeout=2)
        self.assertFalse(activation_thread.is_alive())
        self.assertEqual(len(activation_errors), 1)
        self.assertIsInstance(activation_errors[0], RuntimeTransitionError)
        self.assertEqual(second_store.get_turn(turn.turn_id).status, "cancelled")
        self.assertEqual(second_store.get_session(session.session_id).status, "stopped")


def _runtime_store(repo_root: Path) -> RuntimeDocumentStore:
    return RuntimeDocumentStore(
        RuntimeCollections(
            sessions=RuntimeSessionJsonCollection(start_path=repo_root, filename="session.json"),
            turns=RuntimeSessionJsonCollection(start_path=repo_root, filename="turns.json"),
            events=RuntimeEventJsonCollection(start_path=repo_root),
            processes=RuntimeSessionJsonCollection(start_path=repo_root, filename="processes.json"),
            states=RuntimeSessionJsonCollection(start_path=repo_root, filename="state.json"),
            threads=WorkspaceRuntimeJsonCollection(start_path=repo_root, filename="threads.json"),
        )
    )


if __name__ == "__main__":
    unittest.main()
