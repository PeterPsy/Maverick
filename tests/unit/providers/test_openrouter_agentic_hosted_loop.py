"""OpenRouter codec integration through the shared hosted runtime loop."""

from __future__ import annotations

from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from core.mcp.models import McpInvocationPolicy, McpToolDefinition
from core.providers.agentic_protocol import EphemeralCredential
from core.providers.openrouter_agentic_client import (
    OpenRouterAgenticClient,
)
from core.providers.maverick_agent_builtins import (
    OPENROUTER_RELACE_GLM_PROVIDER_CONFIG,
)
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_CODEC_ID,
    OPENROUTER_AGENTIC_CODEC_VERSION,
    OPENROUTER_AGENTIC_CONTENT_TYPE,
    OPENROUTER_AGENTIC_MODEL_ID,
    OPENROUTER_AGENTIC_SCHEMA_VERSION,
)
from core.providers.openrouter_agentic_profile import openrouter_agentic_routing_constraint
from core.providers.openrouter_agentic_state import inspect_openrouter_chat_state
from core.runtime.execution import execute_runtime_turn
from core.runtime.errors import RuntimeProviderStateError
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedProviderPrivateCodec,
)
from core.runtime.hosted_agentic_recovery import HostedAgenticRecovery
from core.runtime.provider_step_journal import ProviderStepJournal
from core.runtime.research_runtime import (
    RESEARCH_HOSTED_WEB_RUNTIME,
    RESEARCH_WEB_TOOL_HANDLES,
    isolate_research_authority,
    research_runtime_policy,
)
from tests.support.hosted_agentic_harness import HostedAgenticHarness
from tests.unit.providers.test_openrouter_agentic_codec import (
    _ScriptedTransport,
    _text_stream,
    _tool_stream,
)


OPENROUTER_REQUEST_COST_ESTIMATOR = (
    OPENROUTER_RELACE_GLM_PROVIDER_CONFIG.token_cost_policy.request_ceiling_microusd
)


class OpenRouterAgenticHostedLoopTest(unittest.TestCase):
    def test_real_codec_runs_through_shared_tool_loop(self) -> None:
        harness = HostedAgenticHarness(
            self,
            model_provider_id="openrouter",
            model_id=OPENROUTER_AGENTIC_MODEL_ID,
            provider_protocol="openrouter-chat-completions",
            routing_constraint=openrouter_agentic_routing_constraint(),
            filesystem_list=True,
            json_store=True,
        )
        transport = _ScriptedTransport([
            _tool_stream(
                "generation-loop-1",
                harness.filesystem_list_tool_name,
                arguments={"path": ".", "max_depth": 1, "max_results": 10},
            ),
            _text_stream("generation-loop-2", "OpenRouter fixture answer"),
        ])
        adapter = harness.adapter(
            OpenRouterAgenticClient(transport=transport),
            private_codec=HostedProviderPrivateCodec(
                OPENROUTER_AGENTIC_CODEC_ID,
                OPENROUTER_AGENTIC_CODEC_VERSION,
                OPENROUTER_AGENTIC_SCHEMA_VERSION,
                OPENROUTER_AGENTIC_CONTENT_TYPE,
            ),
            credential=EphemeralCredential("fixture-openrouter-key"),
            cost_estimator=OPENROUTER_REQUEST_COST_ESTIMATOR,
            private_state_inspector=inspect_openrouter_chat_state,
        )
        public_events = []

        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Use only synthetic fixture data.",
            agentic_adapter=adapter,
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
            event_sink=public_events.append,
        )

        self.assertEqual(result.output_text, "OpenRouter fixture answer")
        self.assertEqual(harness.cli_calls, 0)
        self.assertEqual(
            transport.payloads[0]["tools"][0]["function"]["name"],
            harness.filesystem_list_tool_name,
        )
        self.assertIn(harness.filesystem_marker, json.dumps(transport.payloads[1]))
        self.assertEqual(transport.payloads[1]["provider"]["only"], ["relace"])
        serialized = json.dumps([event.payload for event in public_events], default=str)
        self.assertNotIn("private fixture reasoning", serialized)
        self.assertNotIn("private-signature", serialized)

    def test_research_terminal_sequence_commits_through_json_cas(self) -> None:
        harness = self._research_harness()
        transport = _ScriptedTransport([
            _text_stream("generation-research", "Research fixture answer"),
        ])
        adapter = self._adapter(harness, transport)

        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Research only public sources.",
            agentic_adapter=adapter,
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
        )

        self.assertEqual(result.output_text, "Research fixture answer")
        self.assertEqual(
            [tool["function"]["name"] for tool in transport.payloads[0]["tools"]],
            ["web_open", "web_search"],
        )
        record = harness.store.list_provider_step_journals(
            session_id=harness.session.session_id
        )[0]
        self.assertEqual(record.stream_status, "completed")
        self.assertEqual(record.commit_status, "committed")
        self.assertEqual(record.usage_report_count, 1)
        self.assertEqual(
            (record.usage_input_tokens, record.usage_output_tokens),
            (120, 12),
        )
        self.assertEqual(record.final_output_status, "delivered")
        self.assertEqual(record.final_completion_status, "delivered")
        envelope = record.staged_provider_state
        self.assertIsNotNone(envelope)
        assert envelope is not None
        self.assertEqual(
            envelope.source_provenances[0],
            "platform_instruction",
        )

    def test_research_cleanup_keeps_primary_failure_and_terminalizes_json_journal(
        self,
    ) -> None:
        harness = self._research_harness()
        adapter = self._adapter(
            harness,
            _ScriptedTransport([
                _text_stream("generation-research-failure", "Complete answer"),
            ]),
        )

        def fail_after_persist(point, _record):
            if point == "provider_state_staged":
                raise HostedAgenticLoopError("primary_stream_failure")
            if point == "provider_stream_failed":
                raise RuntimeError("cleanup failure after persisted CAS")

        journal = ProviderStepJournal(
            store=harness.store,
            fault_hook=fail_after_persist,
        )
        adapter.loop.provider_step_journal = journal
        adapter.loop.recovery = HostedAgenticRecovery(
            journal=journal,
            tool_ledger=harness.orchestrator.ledger,
            private_state_service=harness.private_state_service,
        )

        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Research only public sources.",
            agentic_adapter=adapter,
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
        )

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.failure_reason_code, "primary_stream_failure")
        record = harness.store.list_provider_step_journals(
            session_id=harness.session.session_id
        )[0]
        self.assertEqual(record.stream_status, "failed")
        self.assertEqual(record.stream_failure_reason_code, "primary_stream_failure")
        self.assertEqual(record.commit_status, "recovery_required")
        self.assertEqual(
            record.recovery_reason_code,
            "provider_acceptance_ambiguous",
        )
        session = harness.store.get_session(harness.session.session_id)
        self.assertEqual(session.status, "recovery_required")
        self.assertEqual(
            session.recovery_reason_code,
            "provider_acceptance_ambiguous",
        )

    def test_research_cleanup_falls_back_when_json_cas_never_terminalizes(
        self,
    ) -> None:
        harness = self._research_harness()
        adapter = self._adapter(
            harness,
            _ScriptedTransport([
                _text_stream("generation-research-uncontained", "Complete answer"),
            ]),
        )

        def fail_after_staging(point, _record):
            if point == "provider_state_staged":
                raise HostedAgenticLoopError("primary_stream_failure")

        journal = ProviderStepJournal(
            store=harness.store,
            fault_hook=fail_after_staging,
        )
        adapter.loop.provider_step_journal = journal
        adapter.loop.recovery = HostedAgenticRecovery(
            journal=journal,
            tool_ledger=harness.orchestrator.ledger,
            private_state_service=harness.private_state_service,
        )
        update = harness.store.update_provider_step_journal
        blocked_stream_updates = 0

        def reject_terminal_cas(record, *, expected_revision):
            nonlocal blocked_stream_updates
            if record.stream_status == "failed":
                blocked_stream_updates += 1
                raise RuntimeProviderStateError("fixture_pre_cas_failure")
            if record.commit_status == "recovery_required":
                raise RuntimeProviderStateError("fixture_pre_cas_failure")
            return update(record, expected_revision=expected_revision)

        with (
            patch.object(
                harness.store,
                "update_provider_step_journal",
                side_effect=reject_terminal_cas,
            ),
            self.assertLogs("core.runtime.hosted_agentic_loop", level="ERROR") as logs,
        ):
            result = execute_runtime_turn(
                session=harness.session,
                provider=harness.provider,
                input_text="Research only public sources.",
                agentic_adapter=adapter,
                provider_state=harness.store.get_provider_state("session-hosted"),
                correlation_id="turn-hosted",
                effective_authority=harness.authority,
            )

        self.assertEqual(blocked_stream_updates, 3)
        self.assertEqual(result.failure_reason_code, "provider_state_ambiguous")
        self.assertIn("primary_stream_failure", "\n".join(logs.output))
        record = harness.store.list_provider_step_journals(
            session_id=harness.session.session_id
        )[0]
        self.assertEqual(record.stream_status, "pending")
        self.assertEqual(record.commit_status, "pending")
        self.assertEqual(
            harness.store.get_session(harness.session.session_id).status,
            "recovery_required",
        )

    def _research_harness(self) -> HostedAgenticHarness:
        harness = HostedAgenticHarness(
            self,
            model_provider_id="openrouter",
            model_id=OPENROUTER_AGENTIC_MODEL_ID,
            provider_protocol="openrouter-chat-completions",
            routing_constraint=openrouter_agentic_routing_constraint(),
            json_store=True,
        )
        schemas = {
            "mcp:app.browser.web_search": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 500}
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            "mcp:app.browser.web_open": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "minLength": 1, "maxLength": 4096}
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        }
        for handle in RESEARCH_WEB_TOOL_HANDLES:
            harness.orchestrator.catalog_builder.mcp_registry.register_tool(
                McpToolDefinition(
                    tool_name=handle.removeprefix("mcp:"),
                    description="Read the public web.",
                    input_schema=schemas[handle],
                    output_schema=None,
                    owner_kind="app",
                    owner_id="browser",
                    workspace_id=None,
                    exposure_scope="core_global",
                    invocation_policy=McpInvocationPolicy(False, False, True, False),
                    entrypoint_path=None,
                    effect_class="read",
                    supports_idempotency=False,
                    schema_public=True,
                    reviewed_schema_component="tool-schema-catalog",
                ),
                lambda _arguments, _context: {"ok": True},
            )
        harness.session = replace(harness.session, runtime_profile="research")
        harness.store.save_session(harness.session)
        harness.policy = research_runtime_policy(harness.policy)
        declared = replace(
            harness.authority,
            allowed_tool_handles=RESEARCH_WEB_TOOL_HANDLES,
            allowed_capabilities=replace(
                harness.authority.allowed_capabilities,
                tool_orchestration=True,
                mcp=True,
            ),
        )
        harness.authority = isolate_research_authority(
            declared,
            runtime_kind=RESEARCH_HOSTED_WEB_RUNTIME,
        )
        return harness

    @staticmethod
    def _adapter(harness, transport):
        return harness.adapter(
            OpenRouterAgenticClient(transport=transport),
            private_codec=HostedProviderPrivateCodec(
                OPENROUTER_AGENTIC_CODEC_ID,
                OPENROUTER_AGENTIC_CODEC_VERSION,
                OPENROUTER_AGENTIC_SCHEMA_VERSION,
                OPENROUTER_AGENTIC_CONTENT_TYPE,
            ),
            credential=EphemeralCredential("fixture-openrouter-key"),
            cost_estimator=OPENROUTER_REQUEST_COST_ESTIMATOR,
            private_state_inspector=inspect_openrouter_chat_state,
        )



if __name__ == "__main__":
    unittest.main()
