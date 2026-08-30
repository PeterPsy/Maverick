from __future__ import annotations

import asyncio
from dataclasses import replace
from threading import Event
import time
from types import SimpleNamespace
import unittest

from core.cli.command_registry import CliCommandRegistry
from core.mcp.models import McpInvocationPolicy, McpToolDefinition
from core.mcp.tool_registry import McpToolRegistry
from core.runtime.execution_binding import canonical_digest
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.hosted_agentic_tool_execution import (
    execute_hosted_authorized_tool,
)
from core.runtime.hosted_tool_process_registry import HostedToolProcessRegistry
from core.runtime.runtime_cancellation import RuntimeCancellationSignal
from core.runtime.tool_catalog import (
    RuntimeToolActorContext,
    RuntimeToolCatalogBuilder,
)
from core.runtime.tool_core_capabilities import (
    build_core_runtime_tool_capabilities,
)
from core.runtime.tool_orchestrator import (
    RuntimeToolConfirmationPolicy,
    RuntimeToolOrchestrator,
)
from core.runtime.tool_schema import provider_tool_name
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class HostedAgenticToolExecutionTest(unittest.TestCase):
    def test_cancelled_mcp_worker_quiesces_before_turn_returns_even_if_declared_read(
        self,
    ) -> None:
        harness = HostedAgenticHarness(self)
        workspace = harness.root / "workspaces" / "default"
        target = workspace / "mcp-after-cancel.txt"
        entered = Event()
        release = Event()
        mcp_registry = McpToolRegistry()

        def blocked_mutation(_arguments, _context):
            entered.set()
            release.wait(timeout=2)
            target.write_text("completed", encoding="utf-8")
            return {"completed": True}

        mcp_registry.register_tool(
            McpToolDefinition(
                tool_name="fixture_blocked_mutation",
                description="Blocked mutating fixture.",
                input_schema={"type": "object", "additionalProperties": False},
                output_schema={"type": "object"},
                owner_kind="app",
                owner_id="fixture",
                workspace_id="default",
                exposure_scope="workspace_enabled_app",
                invocation_policy=McpInvocationPolicy(
                    operator_only=False,
                    sandbox_agent_allowed=True,
                    requires_workspace_context=True,
                    requires_full_access=False,
                ),
                entrypoint_path="apps/fixture/mcp.py",
                # Cancellation lifetime must not rely on a partial handle list or
                # an app's effect declaration: every active worker remains owned.
                effect_class="read",
            ),
            blocked_mutation,
        )
        actor = RuntimeToolActorContext(
            workspace_id="default",
            actor_id="user-1",
            agent_id="chat",
            platform_role="admin",
            workspace_role="owner",
            session_id=harness.session.session_id,
            execution_mode="full-access",
        )
        orchestrator = RuntimeToolOrchestrator(
            catalog_builder=RuntimeToolCatalogBuilder(
                cli_registry=CliCommandRegistry(),
                mcp_registry=mcp_registry,
            ),
            ledger=harness.orchestrator.ledger,
        )
        authority = replace(
            harness.authority,
            allowed_capabilities=replace(
                harness.authority.allowed_capabilities,
                mcp=True,
            ),
            allowed_tool_handles=("mcp:fixture_blocked_mutation",),
            authority_digest="",
        )
        authority = replace(
            authority,
            authority_digest=canonical_digest(authority),
        )
        policy = RuntimeToolConfirmationPolicy(
            policy_revision="cancel-mcp:1",
            require_confirmation_for_mutating=False,
            require_confirmation_for_destructive=False,
            max_tool_result_bytes=262_144,
        )
        catalog = orchestrator.materialize(authority=authority, context=actor)
        observed = orchestrator.observe_provider_tool(
            provider_tool_name=provider_tool_name("mcp:fixture_blocked_mutation"),
            provider_tool_call_id="call-cancel-mcp",
            arguments={},
            provider_request_id="request-cancel-mcp",
            provider_event_ordinal=0,
            provider_call_index=0,
            authority=authority,
            context=actor,
            turn_id="turn-hosted",
            policy=policy,
        )
        authorized = orchestrator.prepare_observed_tool(
            observed.invocation,
            requested_catalog=catalog,
            authority=authority,
            context=actor,
            policy=policy,
        )
        cancellation = RuntimeCancellationSignal()
        deadline = time.monotonic() + 4
        budget = SimpleNamespace(
            finalization_policy=SimpleNamespace(
                finalization_time_reserve_seconds_per_attempt=1.0,
            ),
            tool_execution_deadline=lambda *, cleanup_seconds: (
                deadline - cleanup_seconds
            ),
            monotonic=time.monotonic,
        )

        async def cancel_and_release() -> None:
            task = asyncio.create_task(
                execute_hosted_authorized_tool(
                    tool_orchestrator=orchestrator,
                    outcome=authorized,
                    authority=authority,
                    context=actor,
                    policy=policy,
                    budget=budget,
                    cancellation=cancellation,
                    poll_seconds=0.01,
                )
            )
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            await asyncio.to_thread(cancellation.set)
            await asyncio.sleep(0.05)
            self.assertFalse(task.done())
            self.assertFalse(target.exists())
            release.set()
            with self.assertRaisesRegex(
                HostedAgenticLoopError,
                "runtime_cancelled",
            ):
                await task

        asyncio.run(cancel_and_release())
        self.assertTrue(target.exists())
        persisted = harness.store.get_tool_invocation(
            authorized.invocation.invocation_id
        )
        self.assertEqual(persisted.state, "failed")

    def test_cancelled_shell_cannot_commit_a_late_workspace_effect(self) -> None:
        harness = HostedAgenticHarness(self)
        workspace = harness.root / "workspaces" / "default"
        capabilities = build_core_runtime_tool_capabilities(
            workspace_id="default",
            workspace_root=workspace,
            runtime_root=workspace / "runtime",
        )
        surfaces = {
            surface.definition.handle: surface for surface in capabilities
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
        scope = surfaces[
            "core-capability:workspace.instructions"
        ].handler({"path": ".", "target_is_directory": True}, actor, None)
        orchestrator = RuntimeToolOrchestrator(
            catalog_builder=RuntimeToolCatalogBuilder(
                cli_registry=CliCommandRegistry(),
                mcp_registry=McpToolRegistry(),
                core_capabilities=capabilities,
            ),
            ledger=harness.orchestrator.ledger,
        )
        authority = replace(
            harness.authority,
            allowed_capabilities=replace(
                harness.authority.allowed_capabilities,
                shell=True,
            ),
            allowed_tool_handles=("core-capability:shell.run",),
            authority_digest="",
        )
        authority = replace(
            authority,
            authority_digest=canonical_digest(authority),
        )
        policy = RuntimeToolConfirmationPolicy(
            policy_revision="cancel-shell:1",
            require_confirmation_for_mutating=False,
            require_confirmation_for_destructive=False,
            max_tool_result_bytes=262_144,
        )
        catalog = orchestrator.materialize(authority=authority, context=actor)
        observed = orchestrator.observe_provider_tool(
            provider_tool_name=provider_tool_name(
                "core-capability:shell.run"
            ),
            provider_tool_call_id="call-cancel-shell",
            arguments={
                "argv": [
                    "/bin/sh",
                    "-c",
                    "sleep 0.5; printf late > cancelled-late.txt",
                ],
                "mutation_scopes": [
                    {
                        "path": ".",
                        "instruction_scope_digest": scope.payload[
                            "scope_digest"
                        ],
                    }
                ],
            },
            provider_request_id="request-cancel-shell",
            provider_event_ordinal=0,
            provider_call_index=0,
            authority=authority,
            context=actor,
            turn_id="turn-hosted",
            policy=policy,
        )
        authorized = orchestrator.prepare_observed_tool(
            observed.invocation,
            requested_catalog=catalog,
            authority=authority,
            context=actor,
            policy=policy,
        )
        self.assertEqual(authorized.invocation.state, "authorized")

        cancellation = RuntimeCancellationSignal()
        deadline = time.monotonic() + 4
        budget = SimpleNamespace(
            finalization_policy=SimpleNamespace(
                finalization_time_reserve_seconds_per_attempt=1.0,
            ),
            tool_execution_deadline=lambda *, cleanup_seconds: (
                deadline - cleanup_seconds
            ),
            monotonic=time.monotonic,
        )

        async def cancel_during_execution() -> None:
            task = asyncio.create_task(
                execute_hosted_authorized_tool(
                    tool_orchestrator=orchestrator,
                    outcome=authorized,
                    authority=authority,
                    context=actor,
                    policy=policy,
                    budget=budget,
                    cancellation=cancellation,
                    poll_seconds=0.01,
                )
            )
            await asyncio.sleep(0.1)
            cancellation.set()
            with self.assertRaisesRegex(
                HostedAgenticLoopError,
                "runtime_cancelled",
            ):
                await task

        asyncio.run(cancel_during_execution())
        target = workspace / "cancelled-late.txt"
        self.assertFalse(target.exists())
        time.sleep(0.65)
        self.assertFalse(target.exists())
        persisted = harness.store.get_tool_invocation(
            authorized.invocation.invocation_id
        )
        self.assertEqual(persisted.state, "execution_unknown")

    def test_cancelled_process_start_quiesces_an_unpaired_handle(self) -> None:
        harness = HostedAgenticHarness(self)
        workspace = harness.root / "workspaces" / "default"
        registry = HostedToolProcessRegistry(store=harness.store)
        capabilities = build_core_runtime_tool_capabilities(
            workspace_id="default",
            workspace_root=workspace,
            runtime_root=workspace / "runtime",
            process_registry=registry,
        )
        surfaces = {
            surface.definition.handle: surface for surface in capabilities
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
        scope = surfaces[
            "core-capability:workspace.instructions"
        ].handler({"path": ".", "target_is_directory": True}, actor, None)
        orchestrator = RuntimeToolOrchestrator(
            catalog_builder=RuntimeToolCatalogBuilder(
                cli_registry=CliCommandRegistry(),
                mcp_registry=McpToolRegistry(),
                core_capabilities=capabilities,
            ),
            ledger=harness.orchestrator.ledger,
        )
        authority = replace(
            harness.authority,
            allowed_capabilities=replace(
                harness.authority.allowed_capabilities,
                shell=True,
            ),
            allowed_tool_handles=("core-capability:process.start",),
            authority_digest="",
        )
        authority = replace(
            authority,
            authority_digest=canonical_digest(authority),
        )
        policy = RuntimeToolConfirmationPolicy(
            policy_revision="cancel-process-start:1",
            require_confirmation_for_mutating=False,
            require_confirmation_for_destructive=False,
            max_tool_result_bytes=262_144,
        )
        catalog = orchestrator.materialize(authority=authority, context=actor)
        observed = orchestrator.observe_provider_tool(
            provider_tool_name=provider_tool_name(
                "core-capability:process.start"
            ),
            provider_tool_call_id="call-cancel-process-start",
            arguments={
                "argv": [
                    "/bin/sh",
                    "-c",
                    "sleep 0.15; printf late > cancelled-process.txt; sleep 30",
                ],
                "mutation_scopes": [
                    {
                        "path": ".",
                        "instruction_scope_digest": scope.payload[
                            "scope_digest"
                        ],
                    }
                ],
            },
            provider_request_id="request-cancel-process-start",
            provider_event_ordinal=0,
            provider_call_index=0,
            authority=authority,
            context=actor,
            turn_id="turn-hosted",
            policy=policy,
        )
        authorized = orchestrator.prepare_observed_tool(
            observed.invocation,
            requested_catalog=catalog,
            authority=authority,
            context=actor,
            policy=policy,
        )

        spawned = Event()
        release_start = Event()
        original_start = registry.start

        def delayed_start(**kwargs):
            result = original_start(**kwargs)
            spawned.set()
            release_start.wait(timeout=2)
            return result

        registry.start = delayed_start
        cancellation = RuntimeCancellationSignal()
        deadline = time.monotonic() + 4
        budget = SimpleNamespace(
            finalization_policy=SimpleNamespace(
                finalization_time_reserve_seconds_per_attempt=1.0,
            ),
            tool_execution_deadline=lambda *, cleanup_seconds: (
                deadline - cleanup_seconds
            ),
            monotonic=time.monotonic,
        )

        async def cancel_between_spawn_and_callback() -> None:
            task = asyncio.create_task(
                execute_hosted_authorized_tool(
                    tool_orchestrator=orchestrator,
                    outcome=authorized,
                    authority=authority,
                    context=actor,
                    policy=policy,
                    budget=budget,
                    cancellation=cancellation,
                    poll_seconds=0.01,
                )
            )
            self.assertTrue(await asyncio.to_thread(spawned.wait, 2))
            cancellation.set()
            await asyncio.sleep(0.25)
            self.assertFalse(task.done())
            self.assertFalse((workspace / "cancelled-process.txt").exists())
            release_start.set()
            with self.assertRaisesRegex(
                HostedAgenticLoopError,
                "runtime_cancelled",
            ):
                await task

        asyncio.run(cancel_between_spawn_and_callback())
        self.assertEqual(registry.live_process_count(session_id=actor.session_id), 0)
        records = harness.store.list_processes(actor.session_id)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].status, "terminated")
        time.sleep(0.3)
        self.assertFalse((workspace / "cancelled-process.txt").exists())


if __name__ == "__main__":
    unittest.main()
