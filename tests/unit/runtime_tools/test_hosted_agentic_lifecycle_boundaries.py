from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import os
from threading import Event, Thread
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.agentic_adapter import RuntimeCancelContext, RuntimeTurnContext
from core.runtime.hosted_agentic_engine import HostedAgenticEngineAdapter
from core.runtime.hosted_tool_process_registry import HostedToolProcessRegistry
from core.runtime.process_control import runtime_processes_alive_for_session
from core.runtime.runtime_cancellation import RuntimeCancellationSignal
from core.runtime.runtime_process_lifecycle import interrupt_runtime_provider_turn
from core.runtime.session_termination import terminate_runtime_session
from core.runtime.tool_catalog import RuntimeToolActorContext
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.tool_orchestrator import RuntimeToolExecutionControl
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class HostedAgenticLifecycleBoundaryTest(unittest.TestCase):
    def test_external_cancellation_linearizes_before_cow_commit(self) -> None:
        harness = HostedAgenticHarness(self)
        target = harness.root / "workspaces" / "default" / "must-not-commit.txt"
        cancellation = RuntimeCancellationSignal()
        control = RuntimeToolExecutionControl(
            deadline_monotonic=time.monotonic() + 5,
            deadline_utc=datetime.now(tz=UTC) + timedelta(seconds=5),
            execution_lease_id="lease-cancel-before-commit",
            cancellation=Event(),
            external_cancellation=cancellation,
        )
        ready = Event()
        release = Event()
        errors: list[str] = []

        def enter_commit() -> None:
            ready.set()
            release.wait(timeout=2)
            try:
                control.run_if_active(
                    lambda: target.write_text("escaped", encoding="utf-8")
                )
            except RuntimeToolError as error:
                errors.append(error.reason_code)

        worker = Thread(target=enter_commit)
        worker.start()
        self.assertTrue(ready.wait(timeout=2))
        cancellation.set()
        release.set()
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, ["runtime_cancelled"])
        self.assertFalse(target.exists())

    def test_agentic_interrupt_forwards_wait_for_termination(self) -> None:
        harness = HostedAgenticHarness(self)
        adapter = object()
        state = SimpleNamespace(
            provider_store=object(),
            provider_registry=object(),
            runtime_store=harness.store,
        )
        engine = (
            SimpleNamespace(provider_id="maverick-tool-loop"),
            None,
            adapter,
            None,
        )
        with patch(
            "core.runtime.runtime_process_lifecycle.resolve_runtime_engine_for_session",
            return_value=engine,
        ), patch(
            "core.runtime.runtime_process_lifecycle.cancel_agentic_runtime",
            return_value=SimpleNamespace(cancelled=True),
        ) as cancel:
            interrupted = interrupt_runtime_provider_turn(
                state,
                harness.session,
                turn_id="turn-hosted",
                wait_for_termination=True,
            )

        self.assertTrue(interrupted)
        self.assertTrue(cancel.call_args.kwargs["wait_for_termination"])

    def test_hosted_cancel_waits_for_turn_quiescence_when_requested(self) -> None:
        harness = HostedAgenticHarness(self)
        started = Event()
        stopped = Event()

        class DelayedCancellationLoop:
            tool_ledger = SimpleNamespace(store=harness.store)

            async def execute(self, _context, *, cancellation):
                started.set()
                while not cancellation.is_set():
                    await asyncio.sleep(0.005)
                await asyncio.sleep(0.05)
                stopped.set()
                if False:
                    yield None

        adapter = HostedAgenticEngineAdapter(
            runtime_engine_id="maverick-tool-loop",
            adapter_id="fixture-hosted",
            adapter_version="1",
            loop=DelayedCancellationLoop(),
        )

        async def cancel_and_wait() -> None:
            async def consume() -> None:
                async for _event in adapter.execute(
                    RuntimeTurnContext(
                        session=harness.session,
                        binding=harness.binding,
                        provider_state=harness.store.get_provider_state(
                            harness.session.session_id
                        ),
                        input_text="fixture",
                        correlation_id="turn-hosted",
                    )
                ):
                    pass

            execution = asyncio.create_task(consume())
            self.assertTrue(await asyncio.to_thread(started.wait, 2))
            result = await adapter.cancel(
                RuntimeCancelContext(
                    session=harness.session,
                    binding=harness.binding,
                    provider_state=harness.store.get_provider_state(
                        harness.session.session_id
                    ),
                    correlation_id="turn-hosted",
                    wait_for_termination=True,
                )
            )
            self.assertTrue(result.cancelled)
            self.assertTrue(stopped.is_set())
            self.assertTrue(execution.done())
            await execution

        asyncio.run(cancel_and_wait())

    def test_session_termination_finalizes_adapter_owned_process_handles(self) -> None:
        harness = HostedAgenticHarness(self)
        workspace = harness.root / "workspaces" / "default"
        registry = HostedToolProcessRegistry(store=harness.store)
        capabilities = {
            surface.definition.handle: surface
            for surface in build_core_runtime_tool_capabilities(
                workspace_id="default",
                workspace_root=workspace,
                runtime_root=workspace / "runtime",
                process_registry=registry,
            )
        }
        actor = RuntimeToolActorContext(
            workspace_id="default",
            actor_id="user-1",
            agent_id="chat",
            platform_role="admin",
            workspace_role="owner",
            session_id=harness.session.session_id,
            execution_mode="full-access",
        )
        scope = capabilities[
            "core-capability:workspace.instructions"
        ].handler({"path": ".", "target_is_directory": True}, actor, None)
        started = capabilities[
            "core-capability:process.start"
        ].handler(
            {
                "argv": ["/bin/sh", "-c", "sleep 30"],
                "mutation_scopes": [
                    {
                        "path": ".",
                        "instruction_scope_digest": scope.payload[
                            "scope_digest"
                        ],
                    }
                ],
            },
            actor,
            None,
        )
        process_id = str(started.payload["process_id"])
        live = registry._live[process_id]
        output_fd = live.output_fd
        overlay_root = live.effect_overlay.root
        self.assertEqual(registry.live_process_count(session_id=actor.session_id), 1)
        self.assertEqual(harness.store.get_process(process_id).status, "running")
        self.assertTrue(overlay_root.is_dir())

        base = harness.adapter(DeterministicFakeAgenticClient())
        adapter = HostedAgenticEngineAdapter(
            runtime_engine_id=base.runtime_engine_id,
            adapter_id=base.adapter_id,
            adapter_version=base.adapter_version,
            loop=base.loop,
            process_registry=registry,
        )
        provider_store = object()
        provider_registry = object()
        with patch(
            "core.runtime.session_termination.resolve_runtime_engine_for_session",
            return_value=(object(), None, adapter, None),
        ) as resolve_engine:
            result = terminate_runtime_session(
                harness.store,
                session_id=harness.session.session_id,
                reason="fixture session cleanup",
                provider_store=provider_store,
                provider_registry=provider_registry,
            )

        resolve_engine.assert_called_once_with(
            provider_store,
            session=harness.session,
            registry=provider_registry,
        )
        self.assertEqual(result["terminated_processes"], 1)
        self.assertEqual(registry.live_process_count(session_id=actor.session_id), 0)
        self.assertEqual(harness.store.get_process(process_id).status, "terminated")
        self.assertFalse(runtime_processes_alive_for_session(actor.session_id))
        self.assertFalse(overlay_root.exists())
        with self.assertRaises(OSError):
            os.fstat(output_fd)


if __name__ == "__main__":
    unittest.main()
