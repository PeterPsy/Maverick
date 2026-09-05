"""The second native uses a real ACP child process, not the Codex bridge."""

import asyncio
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.native_acp_transport import NativeAcpError
from core.providers.gemini_cli_session import GeminiAcpSession
from core.providers.native_agent_runtime import NativeSteerContext
from core.runtime.agentic_execution import execute_agentic_runtime_turn
from tests.unit.providers.gemini_cli_fixture import GeminiCliFixture


class GeminiCliNativeTest(GeminiCliFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await self.setup_fixture()

    async def asyncTearDown(self):
        await self.controller.close(self.context)

    async def collect(self, text, *, started=None, timeout=3):
        context = SimpleNamespace(session=self.session, binding=self.binding, provider_state=self.state,
                                  input_text=text, correlation_id="turn", timeout_seconds=timeout)
        events = []
        async for event in self.controller.execute(context):
            events.append(event)
            if started is not None:
                started.set()
        return events

    def final_text(self, events):
        finals = [event for event in events if event.event_type == "runtime.output.final"]
        self.assertEqual(len(finals), 1)
        self.assertEqual([event.ordinal for event in events], list(range(1, len(events) + 1)))
        self.assertEqual(events[-1].event_type, "provider.execution.completed")
        self.assertEqual(events[-1].payload["exit_code"], 0)
        return finals[0].payload["text"]

    async def test_successful_turn_and_resume_through_the_real_core_executor(self):
        authority = self.core_authority()
        for prompt in ("first", "second"):
            events, accepted, sent, threads = [], [], [], []
            result = await execute_agentic_runtime_turn(
                session=self.session, provider_state=self.state, adapter=self.controller,
                input_text=prompt, correlation_id="turn", effective_authority=authority,
                local_launch_spec=self.spec, event_sink=events.append,
                on_provider_accepted=accepted.append, on_provider_turn_start_sent=sent.append,
                on_provider_thread_id=threads.append,
            )
            self.assertEqual(result.exit_code, 0)
            self.assertIsNone(result.failure_reason_code)
            self.assertEqual(result.output_text, "answer:" + prompt)
            self.assertEqual(sum(event.event_type == "runtime.output.final" for event in events), 1)
            self.assertEqual(len(accepted), 1)
            self.assertEqual(len(sent), 1)
            self.assertEqual(threads, ["fixture-session"])
            self.state.provider_thread_id = threads[0]
            await self.controller.close(self.context)
        self.assertEqual(sum(m.get("method") == "session/load" for m in self.messages()), 1)

    async def test_invalid_streams_never_complete_successfully_through_core(self):
        authority = self.core_authority()
        for prompt in ("empty", "malformed", "escape"):
            with self.subTest(prompt=prompt):
                prepared = await self.controller.connect(self.context)
                events = []
                with self.assertRaises(NativeAcpError):
                    await execute_agentic_runtime_turn(
                        session=self.session, provider_state=self.state, adapter=self.controller,
                        input_text=prompt, correlation_id="turn", effective_authority=authority,
                        local_launch_spec=self.spec, event_sink=events.append,
                    )
                self.assertIsNotNone(prepared.prepared_handle.process.returncode)
                self.assertFalse(any(event.event_type == "runtime.output.final" for event in events))

    async def test_steering_at_acceptance_discards_the_already_dequeued_old_chunk(self):
        await self.controller.connect(self.context)
        context = SimpleNamespace(session=self.session, binding=self.binding, provider_state=self.state,
                                  input_text="hold", correlation_id="turn", timeout_seconds=3)
        events = []
        async for event in self.controller.execute(context):
            events.append(event)
            if event.event_type == "provider.accepted":
                result = await self.controller.steer(NativeSteerContext("test", "changed"))
                self.assertEqual(result.status, "steered")
        self.assertEqual(self.final_text(events), "answer:changed")

    async def test_connect_stream_final_load_resume_and_close(self):
        prepared = await self.controller.connect(self.context)
        self.state.provider_thread_id = prepared.provider_state_updates["provider_thread_id"]
        client = prepared.prepared_handle
        events = await self.collect("first")
        self.assertEqual(self.final_text(events), "answer:first")
        self.assertEqual(sum(e.event_type == "runtime.output.final" for e in events), 1)
        recovered = await self.controller.resume(self.context)
        self.assertTrue(recovered.recovered)
        self.assertEqual(recovered.provider_state_updates["provider_thread_id"], self.state.provider_thread_id)
        self.assertIsNotNone(client.process.returncode)
        self.assertEqual(self.final_text(await self.collect("second")), "answer:second")
        self.assertEqual([m["method"] for m in self.messages() if m.get("method", "").startswith("session/")],
                         ["session/new", "session/prompt", "session/load", "session/prompt"])
        self.assertTrue((await self.controller.cleanup(self.context)).closed)

    async def test_concurrent_connects_share_one_supervised_protocol_process(self):
        first, second = await asyncio.gather(
            self.controller.connect(self.context), self.controller.connect(self.context),
        )
        self.assertIs(first.prepared_handle, second.prepared_handle)
        self.assertEqual(sum(m.get("method") == "session/new" for m in self.messages()), 1)

    async def test_interrupt_during_initialize_fences_and_reaps_the_connection(self):
        self.context.local_launch_spec = replace(self.spec, env_overrides={
            **self.spec.env_overrides, "ACP_FIXTURE_HOLD_INIT": "1",
        })
        connecting = asyncio.create_task(self.controller.connect(self.context))
        async with asyncio.timeout(2):
            while not self.trace.exists():
                await asyncio.sleep(0.01)
        owner = self.engine._owners["test"]
        client = owner.engine.connecting
        result = await self.controller.interrupt(self.context)
        await asyncio.wait_for(asyncio.gather(connecting, return_exceptions=True), 2)
        self.assertTrue(result.cancelled)
        self.assertIsNotNone(client.process.returncode)
        self.assertNotIn("test", self.engine._owners)
        self.assertFalse(owner.thread.is_alive())

    async def test_a_second_turn_cannot_enter_while_the_first_is_connecting(self):
        entered, release = Event(), Event()
        prepare = GeminiAcpSession.prepare

        async def delayed_prepare(engine, context):
            entered.set()
            await asyncio.to_thread(release.wait, 3)
            return await prepare(engine, context)

        with patch.object(GeminiAcpSession, "prepare", delayed_prepare):
            first = asyncio.create_task(self.collect("first"))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                with self.assertRaisesRegex(NativeAcpError, "turn_already_active"):
                    await asyncio.wait_for(self.collect("second"), 0.2)
                self.assertFalse(first.done())
            finally:
                release.set()
                await asyncio.wait_for(first, 2)

    async def test_structured_steering_replaces_the_active_prompt_with_one_final(self):
        await self.controller.connect(self.context)
        started = asyncio.Event()
        task = asyncio.create_task(self.collect("hold", started=started))
        await asyncio.wait_for(started.wait(), 2)
        steered = await self.controller.steer(NativeSteerContext("test", "changed", expected_provider_turn_id="turn"))
        self.assertEqual(steered.status, "steered")
        events = await asyncio.wait_for(task, 2)
        self.assertEqual(self.final_text(events), "answer:changed")
        self.assertEqual(sum(e.event_type == "runtime.output.final" for e in events), 1)

    async def test_interrupt_reaps_the_process_and_recovery_uses_the_same_session(self):
        prepared = await self.controller.connect(self.context)
        self.state.provider_thread_id = prepared.provider_state_updates["provider_thread_id"]
        started = asyncio.Event()
        task = asyncio.create_task(self.collect("hold", started=started))
        await asyncio.wait_for(started.wait(), 2)
        self.assertTrue((await self.controller.interrupt(self.context)).cancelled)
        await asyncio.gather(task, return_exceptions=True)
        self.assertIsNotNone(prepared.prepared_handle.process.returncode)
        self.assertTrue((await self.controller.recover(self.context)).recovered)

    async def test_cancelled_caller_drains_its_session_worker_before_returning(self):
        prepared = await self.controller.connect(self.context)
        owner = self.engine._owners["test"]
        started = asyncio.Event()
        task = asyncio.create_task(self.collect("hold", started=started))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNotNone(prepared.prepared_handle.process.returncode)
        self.assertFalse(owner.thread.is_alive())
        self.assertTrue(owner.loop.is_closed())
        self.assertEqual(self.engine._owners, {})

    async def test_repeated_close_cancellation_keeps_the_session_fenced_until_join(self):
        prepared = await self.controller.connect(self.context)
        owner = self.engine._owners["test"]
        entered, release = Event(), Event()
        close = owner.engine.close

        async def delayed_close(context):
            entered.set()
            await asyncio.to_thread(release.wait, 3)
            return await close(context)

        with patch.object(owner.engine, "close", delayed_close):
            closing = asyncio.create_task(self.controller.close(self.context))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                for _ in range(2):
                    closing.cancel()
                    await asyncio.sleep(0)
                self.assertFalse(closing.done())
                self.assertIs(self.engine._owners["test"], owner)
                with self.assertRaisesRegex(NativeAcpError, "session_closing"):
                    await self.controller.connect(self.context)
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await closing
        self.assertIsNotNone(prepared.prepared_handle.process.returncode)
        self.assertFalse(owner.thread.is_alive())
        self.assertTrue(owner.loop.is_closed())

    async def test_closing_one_session_does_not_cancel_another_sessions_loop(self):
        first = await self.controller.connect(self.context)
        other_session = SimpleNamespace(**{**vars(self.session), "session_id": "other"})
        other_context = SimpleNamespace(**{**vars(self.context), "session": other_session})
        second = await self.controller.connect(other_context)
        second_owner = self.engine._owners["other"]
        try:
            await self.controller.close(self.context)
            self.assertIsNotNone(first.prepared_handle.process.returncode)
            self.assertIsNone(second.prepared_handle.process.returncode)
            self.assertTrue(second_owner.thread.is_alive())
            turn = SimpleNamespace(**vars(other_context), input_text="other", correlation_id="turn", timeout_seconds=3)
            self.assertEqual(self.final_text([e async for e in self.controller.execute(turn)]), "answer:other")
        finally:
            await self.controller.close(other_context)
        self.assertFalse(second_owner.thread.is_alive())

    async def test_permission_requests_are_denied_and_native_effects_are_observed(self):
        await self.controller.connect(self.context)
        events = await self.collect("permission")
        self.assertEqual(self.final_text(events), "Permission denied")
        effects = [e for e in events if e.payload.get("phase") == "native_tool_effect"]
        self.assertEqual(len(effects), 2)
        response = next(m for m in self.messages() if m.get("id") == "permission")
        self.assertEqual(response["result"]["outcome"]["outcome"], "cancelled")

    async def test_malformed_blank_and_outside_effect_streams_fail_closed(self):
        for prompt, reason in (("malformed", "stream_invalid"), ("empty", "agent_final_output_empty"),
                               ("escape", "effect_outside_workspace")):
            with self.subTest(prompt=prompt):
                prepared = await self.controller.connect(self.context)
                with self.assertRaisesRegex(NativeAcpError, reason):
                    await self.collect(prompt)
                self.assertIsNotNone(prepared.prepared_handle.process.returncode)

    async def test_timeout_reaps_the_protocol_process_tree(self):
        prepared = await self.controller.connect(self.context)
        with self.assertRaises(TimeoutError):
            await self.collect("fork", timeout=0.2)
        self.assertIsNotNone(prepared.prepared_handle.process.returncode)
        child = int(self.trace.with_suffix(".pid").read_text())
        stat = Path(f"/proc/{child}/stat")
        for _ in range(40):
            if not stat.exists() or stat.read_text().split()[2] == "Z":
                break
            await asyncio.sleep(0.05)
        else:
            self.fail("ACP child process survived cleanup")


if __name__ == "__main__":
    unittest.main()
