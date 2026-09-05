"""ACP ownership across the real synchronous Core service/turn boundaries."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from threading import Event
import time
import unittest

from core.providers.native_agent_builtins import build_gemini_cli_candidate_definition
from core.providers.native_acp_transport import NativeAcpError
from core.providers.native_agent_runtime import NativeSteerContext
from core.runtime.agentic_runtime_service import prepare_agentic_runtime, close_agentic_runtime, cancel_agentic_runtime
from core.runtime.async_runtime import run_runtime_coroutine
from core.runtime.execution import execute_runtime_turn
from core.runtime.provider_state import RuntimeProviderState
from tests.unit.providers.gemini_cli_fixture import GeminiCliFixture


class FixtureRuntimeStore:
    """Only persistence is in-memory; all lifecycle and execution code is real."""

    def __init__(self, session):
        self.session = session
        self.state = RuntimeProviderState(
            session_id=session.session_id, workspace_id="default", runtime_engine_id="gemini-cli",
            model_provider_id="gemini-cli", continuation_id=None, provider_thread_id=None,
            provider_request_id=None, provider_private_envelope=None, revision=1,
            turn_generation=None, updated_at=datetime.now(tz=UTC),
        )

    def get_session(self, session_id):
        assert session_id == self.session.session_id
        return self.session

    def get_provider_state(self, session_id):
        assert session_id == self.session.session_id
        return self.state

    def update_provider_state(self, state, *, expected_revision):
        assert expected_revision == self.state.revision
        self.state = state
        return state


class GeminiCliSyncRuntimeTest(GeminiCliFixture, unittest.TestCase):
    def setUp(self):
        run_runtime_coroutine(self.setup_fixture())
        self.authority = self.core_authority()
        self.session.status = "created"
        self.store = FixtureRuntimeStore(self.session)

    def tearDown(self):
        close_agentic_runtime(self.store, session_id="test", adapter=self.controller)

    def execute(self, prompt, **kwargs):
        return execute_runtime_turn(
            session=self.session, provider=build_gemini_cli_candidate_definition(),
            input_text=prompt, agentic_adapter=self.controller, provider_state=self.store.state,
            correlation_id="turn", effective_authority=self.authority, launch_spec=self.spec,
            timeout_seconds=3, **kwargs,
        )

    def test_two_consecutive_sync_turns_keep_the_connection_live(self):
        for prompt in ("first", "second"):
            result = self.execute(prompt)
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.output_text, "answer:" + prompt)
        self.assertEqual(sum(m.get("method") == "initialize" for m in self.messages()), 1)
        self.assertEqual(sum(m.get("method") == "session/new" for m in self.messages()), 1)

    def test_sync_prepare_two_turns_and_idempotent_cleanup(self):
        prepared = prepare_agentic_runtime(
            self.store, session_id="test", adapter=self.controller,
            effective_authority=self.authority, local_launch_spec=self.spec,
        )
        client = prepared.prepared_handle
        self.assertEqual(self.store.state.provider_thread_id, "fixture-session")
        self.assertFalse(client._reader.done())
        self.assertFalse(client._reader.get_loop().is_closed())
        owner = self.engine._owners["test"]
        again = prepare_agentic_runtime(
            self.store, session_id="test", adapter=self.controller,
            effective_authority=self.authority, local_launch_spec=self.spec,
        )
        self.assertIs(again.prepared_handle, client)
        for prompt in ("first", "second"):
            result = self.execute(prompt)
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.output_text, "answer:" + prompt)
            self.assertIsNone(client.process.returncode)
            self.assertFalse(client._reader.done())
        self.assertTrue(close_agentic_runtime(self.store, session_id="test", adapter=self.controller).closed)
        self.assertIsNotNone(client.process.returncode)
        self.assertTrue(client._reader.done())
        self.assertTrue(client._reader.get_loop().is_closed())
        self.assertFalse(owner.thread.is_alive())
        self.assertEqual(self.engine._owners, {})

    def test_sync_interrupt_an_active_turn_then_resume_and_execute(self):
        prepared = prepare_agentic_runtime(
            self.store, session_id="test", adapter=self.controller,
            effective_authority=self.authority, local_launch_spec=self.spec,
        )
        owner = self.engine._owners["test"]
        accepted, events = Event(), []
        with ThreadPoolExecutor(max_workers=1) as worker:
            turn = worker.submit(self.execute, "hold", event_sink=events.append,
                                 on_provider_accepted=lambda _payload: accepted.set())
            self.assertTrue(accepted.wait(2))
            result = cancel_agentic_runtime(
                self.store, session_id="test", correlation_id="turn",
                adapter=self.controller, wait_for_termination=True,
            )
            self.assertTrue(result.cancelled)
            with self.assertRaises((NativeAcpError, asyncio.CancelledError)):
                turn.result(timeout=3)
        self.assertFalse(any(e.event_type == "runtime.output.final" for e in events))
        self.assertIsNotNone(prepared.prepared_handle.process.returncode)
        self.assertFalse(owner.thread.is_alive())
        self.assertTrue(owner.loop.is_closed())
        self.context.provider_state = self.store.state
        resumed = run_runtime_coroutine(self.controller.resume(self.context))
        self.assertTrue(resumed.recovered)
        self.assertEqual(resumed.provider_state_updates["provider_thread_id"], "fixture-session")
        self.assertEqual(self.execute("after-interrupt").output_text, "answer:after-interrupt")
        self.assertEqual(sum(m.get("method") == "session/load" for m in self.messages()), 1)

    def test_sync_interrupt_during_preparation_reaps_reader_process_and_loop(self):
        spec = replace(self.spec, env_overrides={**self.spec.env_overrides, "ACP_FIXTURE_HOLD_INIT": "1"})
        with ThreadPoolExecutor(max_workers=1) as worker:
            preparing = worker.submit(
                prepare_agentic_runtime, self.store, session_id="test", adapter=self.controller,
                effective_authority=self.authority, local_launch_spec=spec,
            )
            deadline = time.monotonic() + 2
            while not self.trace.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(self.trace.exists())
            owner = self.engine._owners["test"]
            client = owner.engine.connecting
            result = cancel_agentic_runtime(
                self.store, session_id="test", correlation_id="turn",
                adapter=self.controller, wait_for_termination=True,
            )
            self.assertTrue(result.cancelled)
            with self.assertRaises((NativeAcpError, asyncio.CancelledError)):
                preparing.result(timeout=3)
        self.assertIsNotNone(client.process.returncode)
        self.assertTrue(client._reader.done())
        self.assertFalse(owner.thread.is_alive())
        self.assertTrue(owner.loop.is_closed())
        self.assertEqual(self.engine._owners, {})

    def test_sync_steering_and_cleanup_from_an_existing_caller_loop(self):
        async def caller():
            # Exercises run_runtime_coroutine's worker-thread branch as well.
            self.assertEqual(self.execute("first").exit_code, 0)
            self.assertEqual(self.execute("second").exit_code, 0)
            accepted = Event()
            with ThreadPoolExecutor(max_workers=1) as worker:
                turn = worker.submit(self.execute, "hold", on_provider_accepted=lambda _p: accepted.set())
                self.assertTrue(accepted.wait(2))
                result = run_runtime_coroutine(self.controller.steer(NativeSteerContext("test", "changed")))
                self.assertEqual(result.status, "steered")
                self.assertEqual(turn.result(timeout=3).output_text, "answer:changed")
            owner = self.engine._owners["test"]
            self.assertTrue(close_agentic_runtime(self.store, session_id="test", adapter=self.controller).closed)
            self.assertFalse(owner.thread.is_alive())

        asyncio.run(caller())

    def test_sync_cleanup_unblocks_an_active_turn(self):
        accepted = Event()
        with ThreadPoolExecutor(max_workers=1) as worker:
            turn = worker.submit(self.execute, "hold", on_provider_accepted=lambda _p: accepted.set())
            self.assertTrue(accepted.wait(2))
            owner = self.engine._owners["test"]
            client = owner.engine.client
            result = close_agentic_runtime(self.store, session_id="test", adapter=self.controller)
            self.assertTrue(result.closed)
            with self.assertRaises((NativeAcpError, asyncio.CancelledError)):
                turn.result(timeout=3)
        self.assertIsNotNone(client.process.returncode)
        self.assertTrue(client._reader.done())
        self.assertFalse(owner.thread.is_alive())
        self.assertTrue(owner.loop.is_closed())

    def test_sync_callback_failure_does_not_leave_an_acp_worker_behind(self):
        prepared = prepare_agentic_runtime(
            self.store, session_id="test", adapter=self.controller,
            effective_authority=self.authority, local_launch_spec=self.spec,
        )
        owner = self.engine._owners["test"]

        def broken_callback(_payload):
            raise ValueError("fixture consumer failed")

        with self.assertRaisesRegex(ValueError, "fixture consumer failed"):
            self.execute("hold", on_provider_accepted=broken_callback)
        self.assertIsNotNone(prepared.prepared_handle.process.returncode)
        self.assertFalse(owner.thread.is_alive())
        self.assertTrue(owner.loop.is_closed())


if __name__ == "__main__":
    unittest.main()
