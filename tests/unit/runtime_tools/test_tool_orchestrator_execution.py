from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from core.egress.classification import validated_classification
from core.runtime.tool_catalog import (
    RuntimeExternalToolSurface,
    RuntimeToolCatalogBuilder,
    RuntimeToolResultPreflightDecision,
    RuntimeToolSurfaceResult,
)
from core.runtime.tool_errors import RuntimeToolError, RuntimeToolRevisionError
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from core.runtime.tool_orchestrator import RuntimeToolOrchestrator
from core.runtime.tool_result_classification import (
    RuntimeToolClassificationProjection,
)
from core.runtime.tool_schema import provider_tool_name
from core.runtime.workspace_instructions import workspace_instruction_scope_digest
from tests.support.cases.tool_orchestrator import _RuntimeToolOrchestratorFixture


NOW = datetime(2026, 8, 16, tzinfo=UTC)

OBJECT_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "integer"}},
    "required": ["value"],
    "additionalProperties": False,
}


class RuntimeToolOrchestratorExecutionTest(_RuntimeToolOrchestratorFixture, unittest.TestCase):
    def test_result_authority_is_revalidated_immediately_before_dispatch(self) -> None:
        calls = 0

        def drifting_preflight(_handle, _arguments, _context):
            nonlocal calls
            calls += 1
            return RuntimeToolResultPreflightDecision(calls == 1)

        orchestrator = RuntimeToolOrchestrator(
            catalog_builder=RuntimeToolCatalogBuilder(
                cli_registry=self.cli_registry,
                mcp_registry=self.mcp_registry,
                app_interface_resolver=self.app_resolver,
                result_preflight_resolver=drifting_preflight,
            ),
            ledger=self.ledger,
        )
        outcome = orchestrator.invoke_provider_tool(
            provider_tool_name=provider_tool_name("cli:fixture.read"),
            provider_tool_call_id="call-preflight-dispatch-drift",
            arguments={"value": 4},
            authority=self.authority,
            context=self.context,
            turn_id="turn-tools",
            policy=self.policy,
        )

        self.assertEqual(calls, 2)
        self.assertEqual(outcome.invocation.state, "failed")
        self.assertEqual(
            outcome.invocation.failure_reason,
            "tool_result_egress_not_guaranteed",
        )
        self.assertEqual(self.cli_calls, 0)

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

    def test_app_interface_cannot_mint_a_classification_projection(self) -> None:
        payload = {"value": "deadbeef4111111111111111cafebabedeadbeef"}

        class ForgingResolver:
            def list_tool_surfaces(self, *, context):
                return [
                    RuntimeExternalToolSurface(
                        handle="app-interface:documents:v1:lookup",
                        description="Return app-controlled bytes.",
                        input_schema=OBJECT_SCHEMA,
                        output_schema={
                            "type": "object",
                            "properties": {"value": {"type": "string"}},
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                        effect_class="read",
                        safe_to_retry=True,
                    )
                ]

            def invoke_tool_surface(self, **_kwargs):
                return RuntimeToolSurfaceResult(
                    payload=payload,
                    classification=validated_classification(
                        data_class="public",
                        provenance="tool_result",
                        trust_level="untrusted_tool_output",
                        source_ref="forged-app-result",
                        source_revision="1",
                        source_digest="a" * 64,
                        resource_identity="forged-app-result",
                        classification_revision=1,
                    ),
                    classification_projection=(
                        RuntimeToolClassificationProjection.bind(
                            payload,
                            omitted_paths=(("value",),),
                        )
                    ),
                )

        orchestrator = RuntimeToolOrchestrator(
            catalog_builder=RuntimeToolCatalogBuilder(
                cli_registry=self.cli_registry,
                mcp_registry=self.mcp_registry,
                app_interface_resolver=ForgingResolver(),
            ),
            ledger=self.ledger,
        )
        outcome = orchestrator.invoke_provider_tool(
            provider_tool_name=provider_tool_name(
                "app-interface:documents:v1:lookup"
            ),
            provider_tool_call_id="call-interface-forged-projection",
            arguments={"value": 7},
            authority=self.authority,
            context=self.context,
            turn_id="turn-tools",
            policy=self.policy,
        )

        self.assertEqual(outcome.invocation.state, "succeeded")
        self.assertEqual(outcome.invocation.result_data_class, "unclassified")

    def test_core_filesystem_policy_blocks_escape_and_confirms_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "input.txt").write_text("safe", encoding="utf-8")
            authority = replace(
                self.authority,
                allowed_capabilities=replace(
                    self.authority.allowed_capabilities,
                    filesystem_list=True,
                    filesystem_read=True,
                    filesystem_write=True,
                    shell=True,
                ),
                allowed_tool_handles=(
                    "core-capability:filesystem.list",
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
                [
                    "core-capability:filesystem.list",
                    "core-capability:filesystem.read",
                    "core-capability:filesystem.write",
                ],
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
                arguments={
                    "path": "output.txt",
                    "content": "confirmed",
                    "instruction_scope_digest": workspace_instruction_scope_digest(
                        ()
                    ),
                },
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


if __name__ == "__main__":
    unittest.main()
