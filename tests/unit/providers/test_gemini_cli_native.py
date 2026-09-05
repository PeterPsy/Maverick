"""The second native uses a real ACP child process, not the Codex bridge."""

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.gemini_cli_native import GeminiCliNativeAdapter
from core.providers.native_acp_transport import NativeAcpError
from core.providers.native_agent_builtins import build_gemini_cli_candidate_installation, build_gemini_cli_candidate_definition
from core.providers.native_agent_runtime import NativeSteerContext
from core.providers.provider_registry import ProviderRegistry


class GeminiCliNativeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        workspace = self.root / "workspace"
        workspace.mkdir()
        self.trace = self.root / "trace.jsonl"
        command = self.root / "gemini-fixture"
        fixture = Path(__file__).resolve().parents[2] / "fixtures/native_acp_peer.py"
        command.write_text(f"#!{sys.executable}\n" + fixture.read_text())
        command.chmod(0o755)
        self.engine = GeminiCliNativeAdapter(command=str(command))
        registry = ProviderRegistry()
        registry.register_native_agent_installation(
            build_gemini_cli_candidate_installation(), definition=build_gemini_cli_candidate_definition(),
            engine_adapter=self.engine,
        )
        self.controller = registry.get_native_agent_controller("gemini-cli")
        self.assertIsNone(self.controller.legacy_adapter)
        self.session = SimpleNamespace(
            session_id="test", workspace_root=str(workspace), workdir=str(workspace),
            runtime_root=str(self.root / "runtime"), effective_mode="sandbox",
        )
        self.binding = SimpleNamespace(model_id="gemini-fixture", credential_binding_id=None, model_revision_policy="provider_alias")
        self.state = SimpleNamespace(provider_thread_id=None)
        # The fixture process replaces only the OS sandbox wrapper. Production
        # launch still uses the real, fail-closed workspace sandbox builder.
        with patch("core.providers.gemini_cli_sandbox.build_bwrap_command", side_effect=lambda **kwargs: kwargs["command"]) as sandbox:
            spec = await self.controller.launch(SimpleNamespace(session=self.session, binding=self.binding, secret_env={}))
            self.assertEqual(sandbox.call_args.kwargs["workspace_root"], workspace)
        self.spec = replace(spec, env_overrides={**spec.env_overrides, "ACP_FIXTURE_TRACE": str(self.trace)})
        self.context = SimpleNamespace(session=self.session, binding=self.binding, provider_state=self.state,
                                       local_launch_spec=self.spec)
        self.launch_patch = patch.object(self.engine, "build_launch_spec", return_value=self.spec)
        self.launch_patch.start()
        self.addCleanup(self.launch_patch.stop)

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

    def messages(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()]

    async def test_connect_stream_final_load_resume_and_close(self):
        prepared = await self.controller.connect(self.context)
        self.state.provider_thread_id = prepared.provider_state_updates["provider_thread_id"]
        client = prepared.prepared_handle
        events = await self.collect("first")
        self.assertEqual(events[-1].payload["text"], "answer:first")
        self.assertEqual(sum(e.event_type == "runtime.output.final" for e in events), 1)
        recovered = await self.controller.resume(self.context)
        self.assertTrue(recovered.recovered)
        self.assertEqual(recovered.provider_state_updates["provider_thread_id"], self.state.provider_thread_id)
        self.assertIsNotNone(client.process.returncode)
        self.assertEqual((await self.collect("second"))[-1].payload["text"], "answer:second")
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
        client = self.engine._connecting["test"]
        result = await self.controller.interrupt(self.context)
        await asyncio.wait_for(asyncio.gather(connecting, return_exceptions=True), 2)
        self.assertTrue(result.cancelled)
        self.assertIsNotNone(client.process.returncode)
        self.assertNotIn("test", self.engine._clients)

    async def test_a_second_turn_cannot_enter_while_the_first_is_connecting(self):
        entered, release = asyncio.Event(), asyncio.Event()
        prepare = self.engine.prepare

        async def delayed_prepare(context):
            entered.set()
            await release.wait()
            return await prepare(context)

        with patch.object(self.engine, "prepare", side_effect=delayed_prepare):
            first = asyncio.create_task(self.collect("first"))
            await asyncio.wait_for(entered.wait(), 2)
            try:
                with self.assertRaisesRegex(NativeAcpError, "turn_already_active"):
                    await asyncio.wait_for(self.collect("second"), 0.2)
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
        self.assertEqual(events[-1].payload["text"], "answer:changed")
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

    async def test_permission_requests_are_denied_and_native_effects_are_observed(self):
        await self.controller.connect(self.context)
        events = await self.collect("permission")
        self.assertEqual(events[-1].payload["text"], "Permission denied")
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
