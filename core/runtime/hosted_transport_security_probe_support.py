"""Deterministic fixtures for the production hosted transport security probe."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from core.providers.agentic_models import (
    codex_routing_constraint,
    codex_runtime_policy,
)
from core.providers.capability_models import RuntimeCapabilitySet
from core.providers.agentic_protocol import AgenticModelEvent
from core.runtime.authority import EffectiveRuntimeAuthority
from core.runtime.hosted_agentic_budget import HostedAgenticBudget
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedFinalizationPolicy,
)
from core.runtime.hosted_agentic_stream import consume_hosted_provider_step
from core.runtime.runtime_cancellation import RuntimeCancellationSignal
from core.shared.in_memory_collection import InMemoryCollection
from core.workspaces.store import WorkspaceCollections, WorkspaceDocumentStore


PROBE_TIME = datetime(2026, 9, 1, tzinfo=UTC)
PROBE_WORKSPACE_ID = "hosted-transport-security-probe"
PROBE_PROVIDER_ID = "security-probe-provider"


class TransportProbeDecisionStore:
    def __init__(self) -> None:
        self.records: list[object] = []

    def initialize_egress_decision(self, *, workspace_id, record):
        if workspace_id != PROBE_WORKSPACE_ID:
            raise ValueError("egress workspace mismatch")
        self.records.append(record)
        return record


class TransportProbeClient:
    def __init__(self) -> None:
        self.request_count = 0

    async def create_response(self, _request, *, credential):
        del credential
        self.request_count += 1
        if False:
            yield None


class TransportProbeEventClient:
    def __init__(self) -> None:
        self.request_count = 0
        self.event_count = 0

    async def create_response(self, request, *, credential):
        del credential
        self.request_count += 1
        for event in (
            AgenticModelEvent("accepted", request.request_id, 1),
            AgenticModelEvent("completed", request.request_id, 2),
        ):
            self.event_count += 1
            yield event


async def consume_transport_probe_stream(
    *,
    client,
    request,
    before_transport,
) -> str:
    policy = replace(
        codex_runtime_policy(),
        max_steps_per_turn=4,
        max_tool_calls_per_turn=4,
        max_wall_time_seconds=5,
        max_tool_result_bytes=4096,
        max_total_tool_result_bytes=4096,
        max_input_tokens=4096,
        max_output_tokens=256,
        allowed_remote_data_classes=("public",),
    )
    budget = HostedAgenticBudget(
        policy,
        HostedFinalizationPolicy(
            exploration_max_output_tokens=64,
            finalization_max_output_tokens=64,
            finalization_cost_reserve_microusd_per_attempt=0,
            finalization_time_reserve_seconds_per_attempt=0.1,
            max_recovery_attempts=0,
        ),
    )
    try:
        async for _emission in consume_hosted_provider_step(
            client=client,
            request=request,
            credential=None,
            budget=budget,
            cancellation=RuntimeCancellationSignal(),
            destination_upstream_id=None,
            before_transport=before_transport,
        ):
            pass
    except HostedAgenticLoopError as error:
        return error.reason_code
    return "transport_not_denied"


def build_transport_probe_context(root: Path):
    binding = SimpleNamespace(
        runtime_engine_id="maverick-tool-loop",
        adapter_id="maverick-hosted-tool-loop",
        adapter_version="security-probe",
        model_provider_id=PROBE_PROVIDER_ID,
        model_id="security-probe-model",
        provider_protocol="security-probe-v1",
        provider_api_version="v1",
        execution_binding_id="security-probe-binding",
        binding_digest="b" * 64,
        reasoning_effort=None,
        routing_constraint_snapshot=codex_routing_constraint(),
        context_policy_snapshot=None,
    )
    session = SimpleNamespace(
        session_id="security-probe-session",
        workspace_id=PROBE_WORKSPACE_ID,
        workspace_root=str(root),
        workdir=str(root),
        system_prompt="",
    )
    return SimpleNamespace(
        binding=binding,
        session=session,
        correlation_id="security-probe-turn",
        effective_authority=EffectiveRuntimeAuthority(
            execution_binding_id=binding.execution_binding_id,
            turn_id="security-probe-turn",
            certificate_id="security-probe-certificate",
            allowed_capabilities=RuntimeCapabilitySet(
                streaming=True,
                tool_orchestration=False,
                cli=False,
                mcp=False,
                skill_catalog=False,
                filesystem_list=False,
                filesystem_read=False,
                filesystem_write=False,
                shell=False,
                interrupt=True,
                same_turn_steering=False,
                recovery=True,
                confirmation_resume=False,
                provider_private_state=False,
                attachment_modalities=(),
            ),
            allowed_tool_handles=(),
            execution_mode="full-access",
            egress_policy_id="security-probe-public",
            policy_revision_set=("security-probe:1",),
            health_revision="security-probe-health:1",
            authority_digest="security-probe-authority",
            computed_at=PROBE_TIME,
            allowed_remote_data_classes=("public",),
        ),
        input_sources=(),
        invoked_skills=(),
    )


def build_transport_probe_workspace_store() -> WorkspaceDocumentStore:
    collection = InMemoryCollection
    return WorkspaceDocumentStore(
        WorkspaceCollections(
            workspaces=collection(),
            memberships=collection(),
            governance=collection(),
            quotas=collection(),
            active_workspace_selections=collection(),
            data_attestations=collection(),
            resource_classifications=collection(),
            data_governance_audits=collection(),
        )
    )


__all__ = [
    "PROBE_PROVIDER_ID",
    "PROBE_TIME",
    "PROBE_WORKSPACE_ID",
    "TransportProbeClient",
    "TransportProbeEventClient",
    "TransportProbeDecisionStore",
    "build_transport_probe_context",
    "build_transport_probe_workspace_store",
    "consume_transport_probe_stream",
]
