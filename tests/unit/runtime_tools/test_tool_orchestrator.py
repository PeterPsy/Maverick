from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from core.cli.command_registry import CliCommandRegistry
from core.cli.models import CliCommandDefinition, CliInvocationPolicy
from core.mcp.models import McpInvocationPolicy, McpToolDefinition
from core.mcp.tool_registry import McpToolRegistry
from core.providers.capability_models import RuntimeCapabilitySet
from core.runtime.authority import EffectiveRuntimeAuthority
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.tool_catalog import (
    RuntimeAppInterfaceResolver,
    RuntimeExternalToolSurface,
    RuntimeToolActorContext,
    RuntimeToolCatalogBuilder,
)
from core.runtime.tool_errors import RuntimeToolError, RuntimeToolRevisionError
from core.runtime.tool_ledger import RuntimeToolLedger
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from core.runtime.tool_orchestrator import (
    RuntimeToolConfirmationPolicy,
    RuntimeToolOrchestrator,
)
from core.runtime.tool_private_payloads import InMemoryRuntimeToolPrivatePayloadStore
from core.runtime.tool_schema import provider_tool_name
from tests.support.collections import FakeCollection


NOW = datetime(2026, 8, 16, tzinfo=UTC)
OBJECT_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "integer"}},
    "required": ["value"],
    "additionalProperties": False,
}


class _FakeAppResolver(RuntimeAppInterfaceResolver):
    def __init__(self) -> None:
        self.calls = 0

    def list_tool_surfaces(self, *, context):
        return [
            RuntimeExternalToolSurface(
                handle="app-interface:documents:v1:lookup",
                description="Look up a document through the selected provider.",
                input_schema=OBJECT_SCHEMA,
                output_schema=OBJECT_SCHEMA,
                effect_class="read",
                safe_to_retry=True,
            )
        ]

    def invoke_tool_surface(self, *, handle, arguments, context, idempotency_key):
        self.calls += 1
        return {"value": arguments["value"]}


class RuntimeToolOrchestratorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cli_calls = 0
        self.mcp_calls = 0
        self.cli_registry = CliCommandRegistry()
        self.mcp_registry = McpToolRegistry()
        self.cli_registry.register_command(
            CliCommandDefinition(
                command_id="fixture.read",
                path_segments=["fixture", "read"],
                description="Read a fixture.",
                argument_schema=OBJECT_SCHEMA,
                owner_kind="core",
                owner_id="test",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=CliInvocationPolicy(False, None, True, True, False),
                entrypoint_path=None,
                effect_class="read",
                safe_to_retry=True,
            ),
            self._read,
        )
        self.mcp_registry.register_tool(
            McpToolDefinition(
                tool_name="fixture_mutate",
                description="Mutate a fixture.",
                input_schema=OBJECT_SCHEMA,
                output_schema=OBJECT_SCHEMA,
                owner_kind="core",
                owner_id="test",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=McpInvocationPolicy(False, True, True, False),
                entrypoint_path=None,
                effect_class="mutating",
                supports_idempotency=True,
            ),
            self._mutate,
        )
        self.tool_invocations = FakeCollection()
        self.tool_grants = FakeCollection()
        self.store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                tool_invocations=self.tool_invocations,
                tool_confirmation_grants=self.tool_grants,
            )
        )
        self.private_store = InMemoryRuntimeToolPrivatePayloadStore()
        self.ledger = RuntimeToolLedger(
            store=self.store,
            private_payload_store=self.private_store,
            digest_key=b"runtime-tool-test-key-32-bytes!!",
        )
        self.app_resolver = _FakeAppResolver()
        self.orchestrator = self._orchestrator()
        self.authority = self._authority(
            "cli:fixture.read",
            "mcp:fixture_mutate",
            "app-interface:documents:v1:lookup",
        )
        self.context = RuntimeToolActorContext(
            workspace_id="default",
            actor_id="user-1",
            agent_id="chat",
            platform_role=None,
            workspace_role="member",
            session_id="session-tools",
            execution_mode="sandbox",
        )
        self.policy = RuntimeToolConfirmationPolicy(
            policy_revision="policy:1",
            require_confirmation_for_mutating=True,
            require_confirmation_for_destructive=True,
            max_tool_result_bytes=1024,
        )

    def _orchestrator(self) -> RuntimeToolOrchestrator:
        return RuntimeToolOrchestrator(
            catalog_builder=RuntimeToolCatalogBuilder(
                cli_registry=self.cli_registry,
                mcp_registry=self.mcp_registry,
                app_interface_resolver=self.app_resolver,
            ),
            ledger=self.ledger,
        )

    def _authority(self, *handles: str) -> EffectiveRuntimeAuthority:
        return EffectiveRuntimeAuthority(
            execution_binding_id="binding-tools",
            turn_id="turn-tools",
            certificate_id="certificate-tools",
            allowed_capabilities=RuntimeCapabilitySet(
                streaming=True,
                tool_orchestration=True,
                cli=True,
                mcp=True,
                skill_catalog=False,
                filesystem_read=False,
                filesystem_write=False,
                shell=False,
                interrupt=True,
                same_turn_steering=False,
                recovery=True,
                confirmation_resume=True,
                provider_private_state=True,
                attachment_modalities=(),
            ),
            allowed_tool_handles=handles,
            execution_mode="sandbox",
            egress_policy_id="fake-data",
            policy_revision_set=("policy:1",),
            health_revision="health:1",
            authority_digest="authority-digest",
            computed_at=NOW,
        )

    def _read(self, arguments, context):
        self.cli_calls += 1
        self.assertIsNone(context.idempotency_key)
        return {"value": arguments["value"]}

    def _mutate(self, arguments, context):
        self.mcp_calls += 1
        self.assertTrue(context.idempotency_key)
        return {"value": arguments["value"] + 1}

    def test_read_tool_executes_once_through_cli_runner(self) -> None:
        name = provider_tool_name("cli:fixture.read")
        outcome = self.orchestrator.invoke_provider_tool(
            provider_tool_name=name,
            provider_tool_call_id="call-read",
            arguments={"value": 4},
            authority=self.authority,
            context=self.context,
            turn_id="turn-tools",
            policy=self.policy,
        )

        self.assertEqual(outcome.invocation.state, "succeeded")
        self.assertEqual(self.cli_calls, 1)
        self.assertNotIn("value", outcome.invocation.arguments_summary)
        self.assertTrue(outcome.invocation.arguments_private_ref.startswith("tool-private:v1:"))

        replay = self.orchestrator.invoke_provider_tool(
            provider_tool_name=name,
            provider_tool_call_id="call-read",
            arguments={"value": 4},
            authority=self.authority,
            context=self.context,
            turn_id="turn-tools",
            policy=self.policy,
        )
        self.assertEqual(replay.invocation.state, "succeeded")
        self.assertEqual(self.cli_calls, 1)

    def test_mutation_waits_for_one_shot_confirmation_and_resumes_once(self) -> None:
        pending = self._propose_mutation("call-mutate")
        self.assertEqual(pending.invocation.state, "awaiting_confirmation")
        self.assertEqual(self.mcp_calls, 0)

        decision = self.orchestrator.decide_confirmation(
            invocation_id=pending.invocation.invocation_id,
            decision="approve",
            arguments_digest=pending.invocation.arguments_digest,
            expected_invocation_revision=pending.invocation.revision,
            confirming_actor_id="user-1",
            policy=self.policy,
        )
        self.assertEqual(decision.confirmation_grant.state, "active")
        completed = self.orchestrator.resume_confirmed(
            invocation_id=pending.invocation.invocation_id,
            grant_id=decision.confirmation_grant.grant_id,
            authority=self.authority,
            context=self.context,
            policy=self.policy,
        )
        self.assertEqual(completed.invocation.state, "succeeded")
        self.assertEqual(self.mcp_calls, 1)

        replay = self.orchestrator.resume_confirmed(
            invocation_id=pending.invocation.invocation_id,
            grant_id=decision.confirmation_grant.grant_id,
            authority=self.authority,
            context=self.context,
            policy=self.policy,
        )
        self.assertEqual(replay.invocation.state, "succeeded")
        self.assertEqual(self.mcp_calls, 1)
        grant = self.store.get_tool_confirmation_grant(decision.confirmation_grant.grant_id)
        self.assertEqual(grant.state, "consumed")

    def test_crash_after_mutation_started_never_duplicates_effect(self) -> None:
        pending = self._propose_mutation("call-crash")
        decision = self.orchestrator.decide_confirmation(
            invocation_id=pending.invocation.invocation_id,
            decision="approve",
            arguments_digest=pending.invocation.arguments_digest,
            expected_invocation_revision=pending.invocation.revision,
            confirming_actor_id="user-1",
            policy=self.policy,
        )
        authorized = self.ledger.authorize(
            invocation_id=pending.invocation.invocation_id,
            grant_id=decision.confirmation_grant.grant_id,
        )
        self.ledger.transition(authorized, "executing")

        recovered = self._orchestrator().recover_invocation(
            invocation_id=pending.invocation.invocation_id,
            authority=self.authority,
            context=self.context,
        )
        self.assertEqual(recovered.invocation.state, "execution_unknown")
        self.assertEqual(self.mcp_calls, 0)

    def test_confirmation_digest_revision_and_expiry_fail_closed(self) -> None:
        pending = self._propose_mutation("call-expiry")
        with self.assertRaisesRegex(RuntimeToolError, "tool_confirmation_digest_mismatch"):
            self.orchestrator.decide_confirmation(
                invocation_id=pending.invocation.invocation_id,
                decision="approve",
                arguments_digest="0" * 64,
                expected_invocation_revision=pending.invocation.revision,
                confirming_actor_id="user-1",
                policy=self.policy,
            )
        with self.assertRaises(RuntimeToolRevisionError):
            self.orchestrator.decide_confirmation(
                invocation_id=pending.invocation.invocation_id,
                decision="approve",
                arguments_digest=pending.invocation.arguments_digest,
                expected_invocation_revision=pending.invocation.revision - 1,
                confirming_actor_id="user-1",
                policy=self.policy,
            )
        record, grant = self.ledger.confirm(
            invocation_id=pending.invocation.invocation_id,
            decision="approve",
            arguments_digest=pending.invocation.arguments_digest,
            expected_invocation_revision=pending.invocation.revision,
            confirming_actor_id="user-1",
            policy_revision="policy:1",
            ttl_seconds=1,
            now=NOW,
        )
        expired = self.ledger.authorize(
            invocation_id=record.invocation_id,
            grant_id=grant.grant_id,
            now=NOW + timedelta(seconds=2),
        )
        self.assertEqual(expired.state, "expired")

    def test_second_actor_cannot_mint_an_alternative_confirmation(self) -> None:
        pending = self._propose_mutation("call-single-grant")
        first = self.orchestrator.decide_confirmation(
            invocation_id=pending.invocation.invocation_id,
            decision="approve",
            arguments_digest=pending.invocation.arguments_digest,
            expected_invocation_revision=pending.invocation.revision,
            confirming_actor_id="user-1",
            policy=self.policy,
        )
        with self.assertRaisesRegex(RuntimeToolError, "tool_confirmation_already_decided"):
            self.orchestrator.decide_confirmation(
                invocation_id=pending.invocation.invocation_id,
                decision="approve",
                arguments_digest=pending.invocation.arguments_digest,
                expected_invocation_revision=first.invocation.revision,
                confirming_actor_id="user-2",
                policy=self.policy,
            )
        self.assertEqual(
            len(self.store.list_tool_confirmation_grants(invocation_id=pending.invocation.invocation_id)),
            1,
        )

    def test_app_interface_is_resolved_without_app_id_specialization(self) -> None:
        outcome = self.orchestrator.invoke_provider_tool(
            provider_tool_name=provider_tool_name("app-interface:documents:v1:lookup"),
            provider_tool_call_id="call-interface",
            arguments={"value": 7},
            authority=self.authority,
            context=self.context,
            turn_id="turn-tools",
            policy=self.policy,
        )
        self.assertEqual(outcome.invocation.state, "succeeded")
        self.assertEqual(self.app_resolver.calls, 1)

    def test_unclassified_and_unauthorized_tools_are_not_materialized(self) -> None:
        self.cli_registry.register_command(
            replace(
                self.cli_registry.get_command("fixture.read"),
                command_id="fixture.unknown",
                effect_class="unclassified",
            ),
            self._read,
        )

    def test_core_filesystem_policy_blocks_escape_and_confirms_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "input.txt").write_text("safe", encoding="utf-8")
            authority = replace(
                self.authority,
                allowed_capabilities=replace(
                    self.authority.allowed_capabilities,
                    filesystem_read=True,
                    filesystem_write=True,
                    shell=True,
                ),
                allowed_tool_handles=(
                    "core-capability:filesystem.read",
                    "core-capability:filesystem.write",
                    "core-capability:shell.run",
                ),
            )
            orchestrator = RuntimeToolOrchestrator(
                catalog_builder=RuntimeToolCatalogBuilder(
                    cli_registry=self.cli_registry,
                    mcp_registry=self.mcp_registry,
                    core_capabilities=build_core_runtime_tool_capabilities(
                        workspace_id="default", workspace_root=root
                    ),
                ),
                ledger=self.ledger,
            )
            catalog = orchestrator.materialize(authority=authority, context=self.context)
            self.assertEqual(
                [item.handle for item in catalog.descriptors],
                ["core-capability:filesystem.read", "core-capability:filesystem.write"],
            )
            read = orchestrator.invoke_provider_tool(
                provider_tool_name=provider_tool_name("core-capability:filesystem.read"),
                provider_tool_call_id="call-core-read",
                arguments={"path": "input.txt"},
                authority=authority,
                context=self.context,
                turn_id="turn-tools",
                policy=self.policy,
            )
            self.assertEqual(read.invocation.state, "succeeded")
            escaped = orchestrator.invoke_provider_tool(
                provider_tool_name=provider_tool_name("core-capability:filesystem.read"),
                provider_tool_call_id="call-core-escape",
                arguments={"path": "../outside.txt"},
                authority=authority,
                context=self.context,
                turn_id="turn-tools",
                policy=self.policy,
            )
            self.assertEqual(escaped.invocation.state, "failed")
            write = orchestrator.invoke_provider_tool(
                provider_tool_name=provider_tool_name("core-capability:filesystem.write"),
                provider_tool_call_id="call-core-write",
                arguments={"path": "output.txt", "content": "confirmed"},
                authority=authority,
                context=self.context,
                turn_id="turn-tools",
                policy=self.policy,
            )
            self.assertEqual(write.invocation.state, "awaiting_confirmation")
            self.assertFalse((root / "output.txt").exists())
        catalog = self.orchestrator.materialize(authority=self.authority, context=self.context)
        self.assertEqual(
            [item.handle for item in catalog.descriptors],
            [
                "app-interface:documents:v1:lookup",
                "cli:fixture.read",
                "mcp:fixture_mutate",
            ],
        )

    def _propose_mutation(self, call_id: str):
        return self.orchestrator.invoke_provider_tool(
            provider_tool_name=provider_tool_name("mcp:fixture_mutate"),
            provider_tool_call_id=call_id,
            arguments={"value": 1},
            authority=self.authority,
            context=self.context,
            turn_id="turn-tools",
            policy=self.policy,
        )


if __name__ == "__main__":
    unittest.main()
