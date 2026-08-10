"""Hosted text request cancellation tests."""

from __future__ import annotations

from multiprocessing import get_context
from pathlib import Path
from threading import Event, Thread
import unittest
from unittest.mock import patch

from core.providers.text_generation import (
    HostedTextCancellation,
    HostedTextGenerationError,
    OpenAICompatibleHttpTransport,
    OpenAICompatibleTextGenerationClient,
    TextGenerationMessage,
    TextGenerationRequest,
)
from core.runtime.event_collection import RuntimeEventJsonCollection
from core.runtime.plain_hosted_cancellation import (
    interrupt_plain_hosted_requests,
    plain_hosted_request_cancellation,
    reconcile_stale_plain_hosted_request_owners,
)
from core.runtime.service import (
    create_runtime_session,
    queue_runtime_turn,
    request_runtime_turn_cancellation,
    transition_runtime_session,
    transition_runtime_turn,
)
from core.runtime.session_collection import RuntimeSessionJsonCollection
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.workspace_collection import WorkspaceRuntimeJsonCollection
from tests.support.repo import make_temp_repo_root


class HostedTextCancellationTest(unittest.TestCase):
    def test_durable_intent_stops_request_owned_by_another_process(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = _runtime_store(repo_root)
        session = create_runtime_session(
            store,
            session_id="cross-process-hosted-session",
            workspace_id="default",
            agent_id="chat",
            runtime_mode="plain_hosted_chat",
            start_path=repo_root,
        )
        transition_runtime_session(store, session_id=session.session_id, target_status="running")
        turn = queue_runtime_turn(
            store,
            turn_id="cross-process-hosted-turn",
            session_id=session.session_id,
            input_text="wait for cancellation",
        )
        transition_runtime_turn(store, turn_id=turn.turn_id, target_status="active")
        context = get_context("spawn")
        request_started = context.Event()
        provider_stopped = context.Event()
        owner = context.Process(
            target=_run_remote_hosted_request,
            args=(repo_root, session.session_id, turn.turn_id, request_started, provider_stopped),
        )
        owner.start()
        try:
            self.assertTrue(request_started.wait(timeout=2))
            request_runtime_turn_cancellation(
                store,
                turn_id=turn.turn_id,
                reason="cross-process interrupt",
            )

            interrupted = interrupt_plain_hosted_requests(
                session.session_id,
                turn_id=turn.turn_id,
                store=store,
                wait_for_termination=True,
            )

            self.assertTrue(interrupted)
            self.assertTrue(provider_stopped.is_set())
            owner.join(timeout=2)
            self.assertFalse(owner.is_alive())
            persisted = store.get_turn(turn.turn_id)
            self.assertIsNotNone(persisted.provider_request_finished_at)
            self.assertIsNotNone(persisted.provider_request_cancellation_acknowledged_at)
        finally:
            owner.join(timeout=2)
            if owner.is_alive():
                owner.terminate()
                owner.join(timeout=2)
        self.assertEqual(owner.exitcode, 0)

    def test_old_ack_from_another_turn_does_not_report_new_turn_interrupted(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = _runtime_store(repo_root)
        session = create_runtime_session(
            store,
            session_id="hosted-ack-correlation-session",
            workspace_id="default",
            agent_id="chat",
            runtime_mode="plain_hosted_chat",
            start_path=repo_root,
        )
        first = queue_runtime_turn(
            store,
            turn_id="hosted-ack-old-turn",
            session_id=session.session_id,
            input_text="old provider request",
        )
        transition_runtime_turn(store, turn_id=first.turn_id, target_status="active")
        with plain_hosted_request_cancellation(
            session_id=session.session_id,
            turn_id=first.turn_id,
            store=store,
        ) as cancellation:
            request_runtime_turn_cancellation(store, turn_id=first.turn_id, reason="cancel old turn")
            self.assertTrue(cancellation.wait_cancelled(timeout=1))
        transition_runtime_turn(store, turn_id=first.turn_id, target_status="cancelled")
        second = queue_runtime_turn(
            store,
            turn_id="hosted-ack-new-turn",
            session_id=session.session_id,
            input_text="no provider request",
        )
        transition_runtime_turn(store, turn_id=second.turn_id, target_status="active")
        request_runtime_turn_cancellation(store, turn_id=second.turn_id, reason="cancel new turn")

        interrupted = interrupt_plain_hosted_requests(
            session.session_id,
            turn_id=second.turn_id,
            store=store,
            wait_for_termination=True,
        )

        self.assertFalse(interrupted)

    def test_reconciliation_preserves_live_remote_owner_and_closes_it_after_crash(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = _runtime_store(repo_root)
        session = create_runtime_session(
            store,
            session_id="live-remote-owner-session",
            workspace_id="default",
            agent_id="chat",
            runtime_mode="plain_hosted_chat",
            start_path=repo_root,
        )
        turn = queue_runtime_turn(
            store,
            turn_id="live-remote-owner-turn",
            session_id=session.session_id,
            input_text="stay alive",
        )
        context = get_context("spawn")
        request_started = context.Event()
        release_request = context.Event()
        owner = context.Process(
            target=_hold_remote_hosted_request,
            args=(repo_root, session.session_id, turn.turn_id, request_started, release_request),
        )
        owner.start()
        try:
            self.assertTrue(request_started.wait(timeout=2))

            reconciled_while_alive = reconcile_stale_plain_hosted_request_owners(
                store,
                session_id=session.session_id,
            )

            self.assertEqual(reconciled_while_alive, 0)
            self.assertTrue(owner.is_alive())
            self.assertIsNone(store.get_turn(turn.turn_id).provider_request_finished_at)
            owner.terminate()
            owner.join(timeout=2)
            self.assertFalse(owner.is_alive())

            reconciled_after_crash = reconcile_stale_plain_hosted_request_owners(
                store,
                session_id=session.session_id,
            )

            self.assertEqual(reconciled_after_crash, 1)
            crashed = store.get_turn(turn.turn_id)
            self.assertIsNotNone(crashed.provider_request_finished_at)
            self.assertIsNone(crashed.provider_request_cancellation_acknowledged_at)
        finally:
            if owner.is_alive():
                release_request.set()
                owner.join(timeout=2)
            if owner.is_alive():
                owner.terminate()
                owner.join(timeout=2)

    def test_streaming_cancellation_closes_and_stops_response(self) -> None:
        class BlockingResponse:
            status = 200

            def __init__(self) -> None:
                self.iteration_started = Event()
                self.closed = Event()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def __iter__(self):
                self.iteration_started.set()
                if not self.closed.wait(timeout=2):
                    raise AssertionError("Timed out waiting for transport cancellation.")
                return
                yield b""  # pragma: no cover - marks this method as an iterator

            def close(self) -> None:
                self.closed.set()

        response = BlockingResponse()
        cancellation = HostedTextCancellation()
        client = OpenAICompatibleTextGenerationClient(
            provider_id="openrouter",
            api_key="secret-token",
            transport=OpenAICompatibleHttpTransport(),
        )
        errors: list[BaseException] = []

        def generate() -> None:
            try:
                client.generate(
                    TextGenerationRequest(
                        model_id="google/gemma-4-31b-it:free",
                        messages=[TextGenerationMessage(role="user", content="Hello")],
                        timeout_seconds=10,
                        stream=True,
                    ),
                    cancellation=cancellation,
                )
            except BaseException as error:  # pragma: no cover - asserted below
                errors.append(error)

        with patch("core.providers.text_generation.urllib_request.urlopen", return_value=response):
            provider_thread = Thread(target=generate)
            provider_thread.start()
            self.assertTrue(response.iteration_started.wait(timeout=1))
            cancellation.cancel()
            provider_thread.join(timeout=2)

        self.assertFalse(provider_thread.is_alive())
        self.assertTrue(response.closed.is_set())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], HostedTextGenerationError)
        self.assertEqual(errors[0].reason_code, "provider_cancelled")


def _run_remote_hosted_request(
    repo_root: Path,
    session_id: str,
    turn_id: str,
    request_started,
    provider_stopped,
) -> None:
    store = _runtime_store(repo_root)
    with plain_hosted_request_cancellation(
        session_id=session_id,
        turn_id=turn_id,
        store=store,
    ) as cancellation:
        request_started.set()
        if not cancellation.wait_cancelled(timeout=3):
            raise AssertionError("Durable cancellation intent was not observed by the provider owner.")
        provider_stopped.set()


def _hold_remote_hosted_request(
    repo_root: Path,
    session_id: str,
    turn_id: str,
    request_started,
    release_request,
) -> None:
    store = _runtime_store(repo_root)
    with plain_hosted_request_cancellation(
        session_id=session_id,
        turn_id=turn_id,
        store=store,
    ):
        request_started.set()
        if not release_request.wait(timeout=5):
            raise AssertionError("Timed out waiting to release remote hosted request.")


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
