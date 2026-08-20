from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
import json
import unittest

from core.providers.agentic_adapter import (
    RuntimeCancelContext,
    RuntimeCloseContext,
    RuntimeProviderEvent,
    RuntimeRecoveryContext,
)
from core.providers.agentic_models import codex_routing_constraint, codex_runtime_policy
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.providers.errors import ProviderNotFoundError
from core.providers.models import RuntimeBackendLaunchSpec
from core.providers.service import builtin_provider_registry
from core.runtime.agentic_execution import _validate_event
from core.runtime.execution import execute_runtime_turn
from core.runtime.execution_binding import build_runtime_execution_binding
from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.provider_state import RuntimeProviderState
from core.runtime.runtime_session import RuntimeSessionRecord
from tests.support.fake_agentic_adapter import FakeHostedAgenticAdapter
from tests.support.agentic_certification import (
    certified_test_authority,
    certified_test_provider_store,
    fake_capability_evidence,
)


NOW = datetime(2026, 8, 16, tzinfo=UTC)


class AgenticAdapterContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = builtin_provider_registry()
        codex = self.registry.get_provider_definition("codex")
        self.definition = replace(
            codex,
            provider_id="fake-hosted-agentic",
            label="Fake hosted agentic",
            default_model_family="fake-model-v1",
        )
        self.adapter = FakeHostedAgenticAdapter()
        self.evidence = fake_capability_evidence(self.adapter, now=NOW)
        self.registry.register_provider_definition(self.definition)
        self.registry.register_agentic_runtime_adapter(self.adapter)
        self.binding = build_runtime_execution_binding(
            session_id="session-fake",
            workspace_id="default",
            profile_definition_id="profile-fake",
            profile_definition_revision="1",
            workspace_binding_id="binding-fake",
            workspace_binding_revision=0,
            capability_certificate_id="certificate-fake",
            runtime_engine_id=self.adapter.runtime_engine_id,
            adapter_id=self.adapter.adapter_id,
            adapter_version=self.adapter.adapter_version,
            adapter_artifact_digest=runtime_adapter_artifact_digest(self.adapter),
            model_provider_id="fake-model-provider",
            model_id="fake-model-v1",
            provider_protocol="fake-stream-v1",
            provider_api_version="v1",
            routing_constraint=codex_routing_constraint(),
            credential_binding_id=None,
            reasoning_effort=None,
            certified_reasoning_efforts=(),
            default_reasoning_effort=None,
            execution_mode="full-access",
            profile_policy_ceiling=codex_runtime_policy(),
            workspace_policy_ceiling=codex_runtime_policy(),
            egress_policy_id="fake-only",
            egress_policy_revision="1",
            created_at=NOW,
            certificate_evidence_digest=self.evidence.evidence_digest,
        )
        self.session = RuntimeSessionRecord(
            session_id="session-fake",
            workspace_id="default",
            agent_id="chat",
            status="running",
            requested_mode="full-access",
            effective_mode="full-access",
            workspace_root="/workspace",
            workdir="/workspace",
            runtime_root="/runtime/session-fake",
            started_at=NOW,
            updated_at=NOW,
            ended_at=None,
            last_progress_at=NOW,
            execution_binding=self.binding,
            provider_id=self.adapter.runtime_engine_id,
        )
        self.provider_state = RuntimeProviderState(
            session_id=self.session.session_id,
            workspace_id=self.session.workspace_id,
            runtime_engine_id=self.binding.runtime_engine_id,
            model_provider_id=self.binding.model_provider_id,
            continuation_id=None,
            provider_thread_id=None,
            provider_request_id=None,
            provider_private_envelope=None,
            revision=0,
            turn_generation=None,
            updated_at=NOW,
        )
        self.provider_store = certified_test_provider_store(
            self.binding,
            self.adapter,
            evidence=self.evidence,
            now=NOW,
        )

    def test_non_process_adapter_executes_without_legacy_adapter_or_launch_spec(self) -> None:
        events: list[RuntimeExecutionEvent] = []
        accepted: list[dict[str, object]] = []

        result = execute_runtime_turn(
            session=self.session,
            provider=self.definition,
            input_text="hello",
            agentic_adapter=self.adapter,
            provider_state=self.provider_state,
            correlation_id="turn-fake",
            effective_authority=certified_test_authority(
                self.provider_store, self.binding, self.adapter, turn_id="turn-fake", now=NOW
            ),
            event_sink=events.append,
            on_provider_accepted=accepted.append,
        )

        self.assertEqual(result.output_text, "fake hosted answer")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self.adapter.prepare_calls, 1)
        self.assertEqual(self.adapter.execute_calls, 1)
        self.assertEqual(accepted, [{"request_id": "request:turn-fake"}])
        self.assertEqual([event.event_type for event in events], [
            "runtime.output.delta",
            "runtime.output.final",
        ])
        with self.assertRaises(ProviderNotFoundError):
            self.registry.get_runtime_adapter(self.adapter.runtime_engine_id)

    def test_pinned_agentic_execution_requires_effective_authority(self) -> None:
        with self.assertRaisesRegex(ValueError, "effective runtime authority"):
            execute_runtime_turn(
                session=self.session,
                provider=self.definition,
                input_text="hello",
                agentic_adapter=self.adapter,
                provider_state=self.provider_state,
                correlation_id="turn-uncertified",
            )

    def test_public_provider_events_reject_nested_private_state_and_oversize_payloads(self) -> None:
        private = RuntimeProviderEvent(
            event_type="runtime.output.delta",
            correlation_id="turn-fake",
            ordinal=1,
            schema_version="1",
            payload={"metadata": {"thoughtSignature": "never-public"}},
        )
        oversized = RuntimeProviderEvent(
            event_type="runtime.output.delta",
            correlation_id="turn-fake",
            ordinal=1,
            schema_version="1",
            payload={"text": "x" * 1_048_577},
        )

        with self.assertRaisesRegex(ValueError, "Provider-private"):
            _validate_event(private, correlation_id="turn-fake", last_ordinal=0)
        with self.assertRaisesRegex(ValueError, "event bound"):
            _validate_event(oversized, correlation_id="turn-fake", last_ordinal=0)

    def test_cancel_recover_and_close_are_async_and_process_independent(self) -> None:
        cancel = RuntimeCancelContext(self.session, self.binding, self.provider_state, "turn-fake")
        recovery = RuntimeRecoveryContext(self.session, self.binding, self.provider_state)
        close = RuntimeCloseContext(self.session, self.binding, self.provider_state)

        cancel_result, recover_result, close_result = asyncio.run(self._lifecycle(cancel, recovery, close))

        self.assertTrue(cancel_result.cancelled)
        self.assertTrue(recover_result.recovered)
        self.assertTrue(close_result.closed)
        self.assertIsNone(self.adapter.local_process_lifecycle)

    def test_legacy_process_adapter_streams_through_async_bridge(self) -> None:
        large_tool_output = "tool output line\n" * 80_000
        legacy = _LegacyAdapter(self.definition, tool_output=large_tool_output)
        self.registry.register_runtime_adapter(legacy)
        bridge = self.registry.get_agentic_runtime_adapter(self.definition.provider_id)
        legacy_evidence = fake_capability_evidence(bridge, now=NOW)
        legacy_binding = replace(
            self.binding,
            adapter_id=bridge.adapter_id,
            adapter_version=bridge.adapter_version,
            adapter_artifact_digest=runtime_adapter_artifact_digest(bridge),
            certificate_evidence_digest=legacy_evidence.evidence_digest,
            binding_digest="",
        )
        from core.runtime.execution_binding import canonical_digest
        legacy_binding = replace(legacy_binding, binding_digest=canonical_digest(legacy_binding))
        legacy_session = replace(self.session, execution_binding=legacy_binding)
        legacy_store = certified_test_provider_store(
            legacy_binding, bridge, evidence=legacy_evidence, now=NOW
        )
        accepted: list[dict[str, object]] = []
        events: list[RuntimeExecutionEvent] = []
        thread_ids: list[str] = []

        result = execute_runtime_turn(
            session=legacy_session,
            provider=self.definition,
            input_text="hello",
            runtime_adapter=legacy,
            agentic_adapter=bridge,
            provider_state=self.provider_state,
            correlation_id="turn-legacy",
            effective_authority=certified_test_authority(
                legacy_store, legacy_binding, bridge, turn_id="turn-legacy", now=NOW
            ),
            launch_spec=_launch_spec(self.session),
            event_sink=events.append,
            on_provider_accepted=accepted.append,
            on_provider_thread_id=thread_ids.append,
        )

        self.assertEqual(result.output_text, "legacy answer")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(accepted, [{"request_id": "legacy-request"}])
        self.assertEqual(thread_ids, ["legacy-thread"])
        self.assertEqual([event.event_type for event in events], ["runtime.tool_call.completed"])
        tool_payload = events[0].payload
        self.assertTrue(tool_payload["output_compaction"]["applied"])
        self.assertIn("[tool output compacted]", tool_payload["output"])
        self.assertNotIn("aggregatedOutput", tool_payload["raw"]["item"])
        encoded_payload = json.dumps(tool_payload, separators=(",", ":")).encode("utf-8")
        self.assertLessEqual(len(encoded_payload), 1_048_576)

    async def _lifecycle(self, cancel, recovery, close):
        return (
            await self.adapter.cancel(cancel),
            await self.adapter.recover(recovery),
            await self.adapter.close(close),
        )


class _LegacyAdapter:
    def __init__(self, definition, *, tool_output: str | None = None) -> None:
        self.definition = definition
        self.tool_output = tool_output

    def provider_definition(self):
        return self.definition

    def validate_backend(self) -> None:
        return None

    def execute_turn(self, **kwargs):
        if self.tool_output is not None:
            kwargs["event_sink"](
                RuntimeExecutionEvent(
                    event_type="runtime.tool_call.completed",
                    payload={
                        "name": "command",
                        "status": "completed",
                        "command": "generate large output",
                        "exit_code": 0,
                        "output": self.tool_output,
                        "raw": {
                            "item": {
                                "type": "commandExecution",
                                "aggregatedOutput": self.tool_output,
                            }
                        },
                    },
                )
            )
        kwargs["on_provider_thread_id"]("legacy-thread")
        kwargs["on_provider_accepted"]({"request_id": "legacy-request"})
        return type("Result", (), {"output_text": "legacy answer", "exit_code": 0})()

    def interrupt_turn(self, _session_id: str) -> bool:
        return True

    def close_runtime(self, _session_id: str) -> int:
        return 1


def _launch_spec(session) -> RuntimeBackendLaunchSpec:
    return RuntimeBackendLaunchSpec(
        provider_id="fake-hosted-agentic",
        command=["/bin/true"],
        env_overrides={},
        credential_binding_id=None,
        resolved_secret_refs=[],
        working_directory=session.workdir,
        execution_mode=session.effective_mode,
        readable_roots=[],
        writable_roots=[],
    )


if __name__ == "__main__":
    unittest.main()
