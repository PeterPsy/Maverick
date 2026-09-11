"""Concurrency and supervised-lifecycle tests for Antigravity CLI."""

import asyncio
from dataclasses import replace
from threading import Barrier, BrokenBarrierError, Event, Lock
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.antigravity_cli_session import AntigravityCliSession
from core.providers.native_agent_runtime import NativeSteerContext
from core.providers.native_structured_cli_transport import NativeStructuredCliError
from tests.unit.providers.antigravity_cli_fixture import AntigravityCliFixture


class AntigravityCliConcurrencyTest(
    AntigravityCliFixture,
    unittest.IsolatedAsyncioTestCase,
):
    async def test_changed_skill_set_restarts_the_session_owner(self):
        source = self.root / "skill"
        source.mkdir()
        (source / "SKILL.md").write_text("# Fixture skill\n", encoding="utf-8")
        skill = SimpleNamespace(
            skill_id="workspace:fixture",
            source_root=str(source),
        )
        with_skill = SimpleNamespace(
            **vars(self.context),
            invoked_skills=(skill,),
        )
        await self.controller.connect(with_skill)
        first_owner = self.engine._owners[self.session.session_id]

        await self.controller.connect(with_skill)
        self.assertIs(
            self.engine._owners[self.session.session_id],
            first_owner,
        )

        without_skill = SimpleNamespace(
            **vars(self.context),
            invoked_skills=(),
        )
        await self.controller.connect(without_skill)
        self.assertIsNot(
            self.engine._owners[self.session.session_id],
            first_owner,
        )
        self.assertFalse(first_owner.thread.is_alive())

    async def test_cache_read_usage_may_exceed_uncached_input(self):
        events = await self.collect("cache-heavy")
        usage = next(
            event.payload
            for event in events
            if event.event_type == "provider.usage"
        )

        self.assertGreater(
            usage["cached_input_tokens"],
            usage["input_tokens"],
        )
        self.assertEqual(
            usage["total_tokens"],
            usage["input_tokens"] + usage["output_tokens"],
        )

    async def test_concurrent_connects_share_one_supervised_process(self):
        rendezvous = Barrier(2)
        counter_lock = Lock()
        active_preparations = 0
        maximum_active_preparations = 0

        def observed_skill_preparation(_runtime_root, _skills):
            nonlocal active_preparations, maximum_active_preparations
            with counter_lock:
                active_preparations += 1
                maximum_active_preparations = max(
                    maximum_active_preparations,
                    active_preparations,
                )
            try:
                try:
                    rendezvous.wait(timeout=0.1)
                except BrokenBarrierError:
                    pass
                return "fixture-skill-digest"
            finally:
                with counter_lock:
                    active_preparations -= 1

        with patch(
            "core.providers.antigravity_cli_native.prepare_antigravity_runtime_skills",
            side_effect=observed_skill_preparation,
        ):
            first, second = await asyncio.gather(
                self.controller.connect(self.context),
                self.controller.connect(self.context),
            )
        self.assertIs(first.prepared_handle, second.prepared_handle)
        self.assertEqual(maximum_active_preparations, 1)
        self.assertEqual(
            sum("startup" in message for message in self.messages()),
            1,
        )

    async def test_interrupt_during_init_fences_and_reaps_connection(self):
        self.context.local_launch_spec = replace(
            self.spec,
            env_overrides={
                **self.spec.env_overrides,
                "ANTIGRAVITY_FIXTURE_HOLD_INIT": "1",
            },
        )
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

    async def test_second_turn_cannot_enter_while_first_is_connecting(self):
        entered, release = Event(), Event()
        prepare = AntigravityCliSession.prepare

        async def delayed_prepare(engine, context):
            entered.set()
            await asyncio.to_thread(release.wait, 3)
            return await prepare(engine, context)

        with patch.object(AntigravityCliSession, "prepare", delayed_prepare):
            first = asyncio.create_task(self.collect("first"))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                with self.assertRaisesRegex(
                    NativeStructuredCliError,
                    "turn_already_active",
                ):
                    await asyncio.wait_for(self.collect("second"), 0.2)
                self.assertFalse(first.done())
            finally:
                release.set()
                await asyncio.wait_for(first, 2)

    async def test_same_turn_steering_is_explicitly_safe_next_turn_only(self):
        await self.controller.connect(self.context)
        started = asyncio.Event()
        task = asyncio.create_task(self.collect("hold", started=started))
        await asyncio.wait_for(started.wait(), 2)
        steered = await self.controller.steer(
            NativeSteerContext(
                "test",
                "changed",
                expected_provider_turn_id="turn",
            )
        )
        self.assertEqual(steered.status, "not_supported")
        self.assertEqual(steered.reason, "antigravity_safe_next_turn_only")
        self.assertTrue((await self.controller.interrupt(self.context)).cancelled)
        await asyncio.gather(task, return_exceptions=True)

    async def test_interrupt_reaps_process_and_recovery_uses_same_conversation(self):
        prepared = await self.controller.connect(self.context)
        self.state.provider_thread_id = prepared.provider_state_updates[
            "provider_thread_id"
        ]
        started = asyncio.Event()
        task = asyncio.create_task(self.collect("hold", started=started))
        await asyncio.wait_for(started.wait(), 2)
        self.assertTrue((await self.controller.interrupt(self.context)).cancelled)
        await asyncio.gather(task, return_exceptions=True)
        self.assertIsNotNone(prepared.prepared_handle.process.returncode)
        self.assertTrue((await self.controller.recover(self.context)).recovered)

    async def test_cancelled_caller_drains_session_worker_before_returning(self):
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

    async def test_repeated_close_cancellation_keeps_session_fenced_until_join(self):
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
                with self.assertRaisesRegex(
                    NativeStructuredCliError,
                    "session_closing",
                ):
                    await self.controller.connect(self.context)
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await closing
        self.assertIsNotNone(prepared.prepared_handle.process.returncode)
        self.assertFalse(owner.thread.is_alive())
        self.assertTrue(owner.loop.is_closed())

    async def test_closing_one_session_does_not_cancel_another(self):
        first = await self.controller.connect(self.context)
        other_session = SimpleNamespace(**{**vars(self.session), "session_id": "other"})
        other_context = SimpleNamespace(**{**vars(self.context), "session": other_session})
        second = await self.controller.connect(other_context)
        second_owner = self.engine._owners["other"]
        try:
            await self.controller.close(self.context)
            self.assertIsNotNone(first.prepared_handle.process.returncode)
            self.assertIsNone(second.prepared_handle.process.returncode)
            turn = SimpleNamespace(
                **vars(other_context),
                input_text="other",
                correlation_id="turn",
                timeout_seconds=3,
            )
            events = [event async for event in self.controller.execute(turn)]
            self.assertEqual(self.final_text(events), "answer:other")
        finally:
            await self.controller.close(other_context)
        self.assertFalse(second_owner.thread.is_alive())
