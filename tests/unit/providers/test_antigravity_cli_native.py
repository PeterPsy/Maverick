"""Executable Antigravity stream-json lifecycle and containment proof."""

import asyncio
from dataclasses import replace
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.antigravity_cli_session import AntigravityCliSession
from core.providers.antigravity_cli_sandbox import antigravity_stream_launch_spec
from core.providers.agentic_adapter import RuntimeRecoveryContext
from core.providers.native_agent_builtins import (
    build_antigravity_cli_candidate_definition,
)
from core.providers.native_agent_runtime import NativeSteerContext
from core.providers.native_structured_cli_transport import NativeStructuredCliError
from core.runtime.agentic_execution import execute_agentic_runtime_turn
from core.runtime.resolved_runtime_engine import (
    ResolvedRuntimeEngine,
    build_optional_local_launch_spec,
)
from tests.unit.providers.antigravity_cli_fixture import AntigravityCliFixture


class AntigravityCliNativeTest(AntigravityCliFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await self.setup_fixture()

    async def asyncTearDown(self):
        await self.controller.close(self.context)

    async def collect(self, text, *, started=None, timeout=3):
        context = SimpleNamespace(
            session=self.session,
            binding=self.binding,
            provider_state=self.state,
            input_text=text,
            correlation_id="turn",
            timeout_seconds=timeout,
        )
        events = []
        async for event in self.controller.execute(context):
            events.append(event)
            if started is not None and event.event_type == "provider.accepted":
                started.set()
        return events

    def final_text(self, events):
        finals = [event for event in events if event.event_type == "runtime.output.final"]
        self.assertEqual(len(finals), 1)
        self.assertEqual(
            [event.ordinal for event in events],
            list(range(1, len(events) + 1)),
        )
        self.assertEqual(events[-1].event_type, "provider.execution.completed")
        self.assertEqual(events[-1].payload["exit_code"], 0)
        return finals[0].payload["text"]

    async def test_successful_turn_and_resume_through_real_core_executor(self):
        authority = self.core_authority()
        for prompt in ("first", "second"):
            events, accepted, sent, threads = [], [], [], []
            result = await execute_agentic_runtime_turn(
                session=self.session,
                provider_state=self.state,
                adapter=self.controller,
                input_text=prompt,
                correlation_id="turn",
                effective_authority=authority,
                local_launch_spec=self.spec,
                event_sink=events.append,
                on_provider_accepted=accepted.append,
                on_provider_turn_start_sent=sent.append,
                on_provider_thread_id=threads.append,
            )
            self.assertEqual(result.exit_code, 0)
            self.assertIsNone(result.failure_reason_code)
            self.assertEqual(result.output_text, "answer:" + prompt)
            self.assertEqual(len(accepted), 1)
            self.assertEqual(len(sent), 1)
            self.assertEqual(threads, ["fixture-conversation"])
            usage = next(event for event in events if event.event_type == "provider.usage")
            self.assertEqual(usage.payload["semantics"], "cumulative")
            self.assertEqual(usage.payload["source"], "antigravity_cli")
            self.state.provider_thread_id = threads[0]
            await self.controller.close(self.context)
        startups = [message["startup"] for message in self.messages() if "startup" in message]
        self.assertEqual(len(startups), 2)
        self.assertIn("--conversation", startups[1]["argv"])
        self.assertIn("fixture-conversation", startups[1]["argv"])

    async def test_launch_is_pinned_machine_readable_and_never_bypasses_permissions(self):
        command = self.spec.command
        self.assertEqual(command.count("stream-json"), 2)
        self.assertIn("--sandbox", command)
        self.assertIn("--disable-slash-commands", command)
        self.assertIn("--model", command)
        self.assertNotIn("--dangerously-skip-permissions", command)
        self.assertIn("/usr/local/lib", self.spec.readable_roots)
        self.assertEqual(self.spec.env_overrides["HOME"], str(self.root / "runtime/antigravity-home"))
        self.assertNotEqual(self.spec.env_overrides["HOME"], str(Path.home()))
        self.assertEqual(self.spec.env_overrides["GEMINI_API_KEY"], "fixture-api-key")
        self.assertNotIn("MAVERICK_PROVIDER_SECRET", self.spec.env_overrides)
        settings_path = (
            Path(self.spec.env_overrides["HOME"])
            / ".gemini/antigravity-cli/settings.json"
        )
        self.assertEqual(
            json.loads(settings_path.read_text(encoding="utf-8")),
            {
                "enableTerminalSandbox": True,
                "modelProvider": "gemini",
                "toolPermission": "request-review",
            },
        )
        self.assertEqual(settings_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.spec.resolved_secret_refs, [])

    async def test_launch_requires_platform_delivered_gemini_credential(self):
        with self.assertRaisesRegex(
            NativeStructuredCliError,
            "antigravity_credential_missing",
        ):
            antigravity_stream_launch_spec(
                SimpleNamespace(
                    session=self.session,
                    binding=self.binding,
                    secret_env={},
                ),
                command=str(self.root / "agy-fixture"),
                dependency_roots=(),
            )

    async def test_resolved_runtime_requests_the_agentic_launch_builder(self):
        resolved = ResolvedRuntimeEngine(
            build_antigravity_cli_candidate_definition(),
            None,
            self.controller,
            None,
        )
        captured = {}

        def builder(_state, **kwargs):
            captured.update(kwargs)
            return "launch"

        result = build_optional_local_launch_spec(
            resolved,
            builder,
            object(),
            session=self.session,
        )

        self.assertEqual(result, "launch")
        self.assertIs(captured["agentic_adapter"], self.controller)
        self.assertIsNone(captured["runtime_adapter"])

    async def test_invalid_streams_never_complete_successfully_through_core(self):
        authority = self.core_authority()
        for prompt in ("empty", "malformed", "oversized", "mismatch-output"):
            with self.subTest(prompt=prompt):
                prepared = await self.controller.connect(self.context)
                events = []
                with self.assertRaises(NativeStructuredCliError):
                    await execute_agentic_runtime_turn(
                        session=self.session,
                        provider_state=self.state,
                        adapter=self.controller,
                        input_text=prompt,
                        correlation_id="turn",
                        effective_authority=authority,
                        local_launch_spec=self.spec,
                        event_sink=events.append,
                    )
                self.assertIsNotNone(prepared.prepared_handle.process.returncode)
                self.assertFalse(
                    any(event.event_type == "runtime.output.final" for event in events)
                )

    async def test_connect_stream_final_resume_and_close(self):
        prepared = await self.controller.connect(self.context)
        self.state.provider_thread_id = prepared.provider_state_updates[
            "provider_thread_id"
        ]
        client = prepared.prepared_handle
        self.assertEqual(prepared.metadata["steering_mode"], "safe_next_turn")
        self.assertEqual(self.final_text(await self.collect("first")), "answer:first")
        recovered = await self.controller.resume(
            RuntimeRecoveryContext(
                session=self.session,
                binding=self.binding,
                provider_state=self.state,
                local_launch_spec=self.spec,
            )
        )
        self.assertTrue(recovered.recovered)
        self.assertEqual(
            recovered.provider_state_updates["provider_thread_id"],
            self.state.provider_thread_id,
        )
        self.assertIsNotNone(client.process.returncode)
        self.assertEqual(self.final_text(await self.collect("second")), "answer:second")
        self.assertTrue((await self.controller.cleanup(self.context)).closed)

    async def test_concurrent_connects_share_one_supervised_process(self):
        first, second = await asyncio.gather(
            self.controller.connect(self.context),
            self.controller.connect(self.context),
        )
        self.assertIs(first.prepared_handle, second.prepared_handle)
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

    async def test_tool_and_permission_steps_are_structured(self):
        tool_events = await self.collect("tool")
        self.assertEqual(self.final_text(tool_events), "tool:fixture")
        projected_tools = [
            event
            for event in tool_events
            if event.event_type.startswith("runtime.tool_call.")
        ]
        self.assertEqual(
            [event.event_type for event in projected_tools],
            ["runtime.tool_call.started", "runtime.tool_call.completed"],
        )
        self.assertEqual(projected_tools[0].payload["argument_names"], ["CommandLine"])
        self.assertIn("arguments_sha256", projected_tools[0].payload)
        self.assertNotIn("arguments", projected_tools[0].payload)
        self.assertIn("output_sha256", projected_tools[1].payload)
        self.assertNotIn("output", projected_tools[1].payload)
        permission_events = await self.collect("permission")
        self.assertEqual(self.final_text(permission_events), "Permission denied")
        failure = next(
            event
            for event in permission_events
            if event.event_type == "runtime.tool_call.failed"
        )
        self.assertEqual(failure.payload["error_type"], "permission_denied")
        self.assertNotIn("error_message", failure.payload)

    async def test_bad_sequence_identity_and_permission_mode_fail_closed(self):
        for prompt, reason in (
            ("duplicate-init", "event_sequence_invalid"),
            ("wrong-conversation", "conversation_mismatch"),
            ("error", "result_error"),
        ):
            with self.subTest(prompt=prompt):
                prepared = await self.controller.connect(self.context)
                with self.assertRaisesRegex(NativeStructuredCliError, reason):
                    await self.collect(prompt)
                self.assertIsNotNone(prepared.prepared_handle.process.returncode)

        untrusted = replace(
            self.spec,
            env_overrides={
                **self.spec.env_overrides,
                "ANTIGRAVITY_FIXTURE_PERMISSION": "always-proceed",
            },
        )
        self.context.local_launch_spec = untrusted
        with self.assertRaisesRegex(
            NativeStructuredCliError,
            "permission_mode_untrusted",
        ):
            await self.controller.connect(self.context)

        self.context.local_launch_spec = replace(
            self.spec,
            env_overrides={
                **self.spec.env_overrides,
                "ANTIGRAVITY_FIXTURE_MISSING_TOOL": "1",
            },
        )
        with self.assertRaisesRegex(
            NativeStructuredCliError,
            "toolset_incomplete",
        ):
            await self.controller.connect(self.context)

    async def test_resume_identity_mismatch_fails_closed(self):
        self.state.provider_thread_id = "fixture-conversation"
        self.context.local_launch_spec = replace(
            self.spec,
            env_overrides={
                **self.spec.env_overrides,
                "ANTIGRAVITY_FIXTURE_MISMATCH_RESUME": "1",
            },
        )
        with self.assertRaisesRegex(
            NativeStructuredCliError,
            "resume_identity_mismatch",
        ):
            await self.controller.connect(self.context)

    async def test_timeout_reaps_protocol_process_tree(self):
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
            self.fail("Antigravity fixture child process survived cleanup")


if __name__ == "__main__":
    unittest.main()
