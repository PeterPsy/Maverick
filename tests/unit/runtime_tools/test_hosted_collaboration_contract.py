from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.cli.command_registry import CliCommandRegistry
from core.cli.inter_agent_commands import inter_agent_command_specs
from core.mcp.inter_agent_tools import inter_agent_tool_specs
from core.mcp.tool_registry import McpToolRegistry
from core.runtime.hosted_collaboration_behavior import (
    HOSTED_COLLABORATION_BEHAVIOR_IDS,
    inspect_hosted_collaboration_behavior,
)
from core.runtime.content_data_classification import classify_runtime_content
from core.runtime.hosted_tool_result_admission import (
    build_hosted_tool_result_admission_resolver,
    build_hosted_tool_result_preflight_resolver,
)
from core.runtime.hosted_tool_result_projections import (
    INTER_AGENT_CLI_PROJECTIONS,
    INTER_AGENT_EFFECTS,
    INTER_AGENT_MCP_PROJECTIONS,
    INTER_AGENT_RESULT_PROJECTIONS,
    definition_has_certified_result_projection,
)
from core.runtime.tool_catalog import RuntimeToolActorContext, RuntimeToolSurfaceResult


_PRIVATE_MARKER = "customer SSN 123-45-6789"
_RUN_ID = "iarun_0123456789abcdef0123456789abcdef"
_PARTICIPANT_ID = "iap_0123456789abcdef0123456789abcdef"
_DIGEST_WITH_LUHN_SUBSEQUENCE = (
    "20914ef24928d26319dd8ac4ff04b2204cf4630440387733486e3cc0cc2084f0"
)


class HostedCollaborationContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cli = CliCommandRegistry()
        for definition, handler in inter_agent_command_specs():
            self.cli.register_command(definition, handler)
        self.mcp = McpToolRegistry()
        for definition, handler in inter_agent_tool_specs():
            self.mcp.register_tool(definition, handler)
        self.context = RuntimeToolActorContext(
            workspace_id="default",
            actor_id="user-1",
            agent_id="chat",
            platform_role="admin",
            workspace_role="owner",
            session_id="session-collaboration",
            execution_mode="full-access",
        )

    def test_every_inter_agent_surface_has_an_effect_and_safe_projection(self) -> None:
        expected_effects = {
            contract: INTER_AGENT_EFFECTS[operation]
            for operation, contract in INTER_AGENT_RESULT_PROJECTIONS.items()
        }
        for definitions, projections, identity_field in (
            (self.cli.list_commands(), INTER_AGENT_CLI_PROJECTIONS, "command_id"),
            (self.mcp.list_tools(), INTER_AGENT_MCP_PROJECTIONS, "tool_name"),
        ):
            self.assertEqual(len(definitions), 8)
            for definition in definitions:
                identity = getattr(definition, identity_field)
                with self.subTest(identity=identity):
                    contract = projections[identity]
                    effect, safe_to_retry = expected_effects[contract]
                    self.assertEqual(definition.effect_class, effect)
                    self.assertEqual(definition.safe_to_retry, safe_to_retry)
                    self.assertEqual(definition.agentic_result_projection, contract)
                    self.assertTrue(
                        definition_has_certified_result_projection(definition)
                    )
                    self.assertIsNone(definition.agentic_result_data_class)

    def test_preflight_and_post_effect_projection_pair_every_operation(self) -> None:
        preflight = build_hosted_tool_result_preflight_resolver(
            cli_registry=self.cli,
            mcp_registry=self.mcp,
        )
        admission = build_hosted_tool_result_admission_resolver(
            cli_registry=self.cli,
            mcp_registry=self.mcp,
        )
        fixtures = _operation_results()
        for surface, projections in (
            ("cli", INTER_AGENT_CLI_PROJECTIONS),
            ("mcp", INTER_AGENT_MCP_PROJECTIONS),
        ):
            for identity, contract in projections.items():
                operation = next(
                    key
                    for key, value in INTER_AGENT_RESULT_PROJECTIONS.items()
                    if value == contract
                )
                handle = (
                    "core-capability:cli.run"
                    if surface == "cli"
                    else "core-capability:mcp.call"
                )
                identity_field = "command_id" if surface == "cli" else "tool_name"
                arguments = {identity_field: identity, "arguments": {}}
                with self.subTest(surface=surface, identity=identity):
                    decision = preflight(handle, arguments, self.context)
                    self.assertTrue(decision.admitted_before_effect)
                    self.assertEqual(decision.guaranteed_data_class, "public")
                    self.assertIn(_PRIVATE_MARKER, repr(fixtures[operation]))
                    result = admission(
                        handle,
                        arguments,
                        fixtures[operation],
                        self.context,
                    )
                    self.assertIsInstance(result, RuntimeToolSurfaceResult)
                    self.assertEqual(result.classification.data_class, "public")
                    self.assertEqual(
                        result.classification.trust_level,
                        "trusted_platform",
                    )
                    self.assertEqual(result.payload["projection_contract"], contract)
                    self.assertNotIn(_PRIVATE_MARKER, repr(result.payload))

    def test_projection_authority_is_not_transferable_to_an_arbitrary_core_tool(self) -> None:
        definition = SimpleNamespace(
            command_id="unrelated.command",
            owner_kind="core",
            schema_public=True,
            certified_tcb_component="tool-schema-catalog",
            agentic_result_projection=INTER_AGENT_RESULT_PROJECTIONS["create"],
        )
        self.assertFalse(definition_has_certified_result_projection(definition))

    def test_invalid_certified_result_is_replaced_without_content_fallback(self) -> None:
        admission = build_hosted_tool_result_admission_resolver(
            cli_registry=self.cli,
            mcp_registry=self.mcp,
            public_content_authority_resolver=lambda _workspace_id: object(),
        )
        malformed = {"run": {"status": "created", "secret": _PRIVATE_MARKER}}
        for handle, arguments in (
            (
                "core-capability:cli.run",
                {"command_id": "inter-agent.runs.create", "arguments": {}},
            ),
            (
                "core-capability:mcp.call",
                {"tool_name": "inter_agent_run_create", "arguments": {}},
            ),
        ):
            with self.subTest(handle=handle):
                result = admission(handle, arguments, malformed, self.context)
                self.assertIsInstance(result, RuntimeToolSurfaceResult)
                self.assertEqual(result.classification.data_class, "public")
                self.assertEqual(result.payload["outcome"], "invalid_tool_result")
                self.assertNotIn(_PRIVATE_MARKER, repr(result.payload))

    def test_projection_reapplication_is_idempotent_and_drops_extra_fields(self) -> None:
        admission = build_hosted_tool_result_admission_resolver(
            cli_registry=self.cli,
            mcp_registry=self.mcp,
        )
        arguments = {
            "command_id": "inter-agent.runs.create",
            "arguments": {},
        }
        first = admission(
            "core-capability:cli.run",
            arguments,
            _operation_results()["create"],
            self.context,
        )
        replayed = admission(
            "core-capability:cli.run",
            arguments,
            {**first.payload, "unexpected": _PRIVATE_MARKER},
            self.context,
        )
        self.assertEqual(replayed.payload, first.payload)
        self.assertNotIn(_PRIVATE_MARKER, repr(replayed.payload))

    def test_certified_reference_digest_uses_authenticated_classification_view(
        self,
    ) -> None:
        admission = build_hosted_tool_result_admission_resolver(
            cli_registry=self.cli,
            mcp_registry=self.mcp,
        )
        result = admission(
            "core-capability:cli.run",
            {"command_id": "inter-agent.runs.create", "arguments": {}},
            {
                "projection_contract": INTER_AGENT_RESULT_PROJECTIONS["create"],
                "operation": "create",
                "outcome": "succeeded",
                "run_ref_sha256": _DIGEST_WITH_LUHN_SUBSEQUENCE,
                "run_status": "created",
            },
            self.context,
        )

        self.assertEqual(
            classify_runtime_content(result.payload, content_type="application/json"),
            "regulated_or_customer_data",
        )
        self.assertIsNotNone(result.classification_projection)
        classification_payload = result.classification_projection.resolve(
            result.payload
        )
        self.assertNotIn("run_ref_sha256", classification_payload)
        self.assertEqual(
            classify_runtime_content(
                classification_payload,
                content_type="application/json",
            ),
            "unclassified",
        )

    def test_behavior_gate_executes_cli_create_then_mcp_wait(self) -> None:
        self.assertEqual(
            inspect_hosted_collaboration_behavior(),
            HOSTED_COLLABORATION_BEHAVIOR_IDS,
        )

    def test_behavior_gate_reuses_verified_workflow_within_one_process(self) -> None:
        inspect_hosted_collaboration_behavior.cache_clear()
        with patch(
            "core.runtime.hosted_collaboration_behavior._probe_workflow",
            return_value=True,
        ) as workflow:
            self.assertEqual(
                inspect_hosted_collaboration_behavior(),
                HOSTED_COLLABORATION_BEHAVIOR_IDS,
            )
            self.assertEqual(
                inspect_hosted_collaboration_behavior(),
                HOSTED_COLLABORATION_BEHAVIOR_IDS,
            )
        workflow.assert_called_once_with()

    def test_behavior_gate_retries_a_transient_probe_failure(self) -> None:
        inspect_hosted_collaboration_behavior.cache_clear()
        self.addCleanup(inspect_hosted_collaboration_behavior.cache_clear)
        with patch(
            "core.runtime.hosted_collaboration_behavior._probe_workflow",
            side_effect=(RuntimeError("transient probe failure"), True),
        ) as workflow:
            self.assertEqual(inspect_hosted_collaboration_behavior(), ())
            self.assertEqual(
                inspect_hosted_collaboration_behavior(),
                HOSTED_COLLABORATION_BEHAVIOR_IDS,
            )
            self.assertEqual(
                inspect_hosted_collaboration_behavior(),
                HOSTED_COLLABORATION_BEHAVIOR_IDS,
            )
        self.assertEqual(workflow.call_count, 2)


def _operation_results() -> dict[str, dict[str, object]]:
    run = {
        "run_id": _RUN_ID,
        "status": "created",
        "created_by_user_id": _PRIVATE_MARKER,
    }
    participant = {
        "participant_id": _PARTICIPANT_ID,
        "status": "idle",
        "label": _PRIVATE_MARKER,
    }
    detail = {
        "run": run,
        "participants": [participant],
        "edges": [{"label": _PRIVATE_MARKER}],
        "budget_policy": {"private": _PRIVATE_MARKER},
        "budget_ledger": {"private": _PRIVATE_MARKER},
    }
    return {
        "create": dict(detail),
        "spawn": {
            "created": True,
            "participant": participant,
            "runtime_session": {
                "session_id": _PRIVATE_MARKER,
                "status": "running",
                "system_prompt": _PRIVATE_MARKER,
            },
        },
        "send": {
            "participant": participant,
            "turn": {
                "turn_id": _PRIVATE_MARKER,
                "status": "completed",
                "input_text": _PRIVATE_MARKER,
            },
            "events": [{"payload": _PRIVATE_MARKER}],
        },
        "execute": {
            **detail,
            "participant_results": [{"output_text": _PRIVATE_MARKER}],
            "final_answer": _PRIVATE_MARKER,
        },
        "wait": dict(detail),
        "interrupt": {
            "run": {**run, "status": "paused"},
            "interrupted_sessions": [{"failure_reason": _PRIVATE_MARKER}],
        },
        "resume": {**detail, "run": {**run, "status": "running"}},
        "close": {
            "run": {**run, "status": "cancelled"},
            "participant_cleanups": [{"failure_reason": _PRIVATE_MARKER}],
            "deleted": None,
        },
    }


if __name__ == "__main__":
    unittest.main()
