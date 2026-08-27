"""Pinned destination and effective tool policy helpers for hosted turns."""

from __future__ import annotations

from core.egress.agentic_models import AgenticEgressPolicy
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.tool_orchestrator import (
    RuntimeToolConfirmationPolicy,
    RuntimeToolInvocationOutcome,
)


HOSTED_CORE_TOOL_HANDLES = (
    "core-capability:filesystem.list",
    "core-capability:filesystem.read",
    "core-capability:filesystem.write",
    "core-capability:shell.run",
)


def authorized_core_tool_handles(binding) -> tuple[str, ...]:
    """Return the exact Core candidates the hosted adapter can materialize."""
    policy = binding.profile_policy_ceiling_snapshot
    if policy.tool_handle_mode == "none":
        return ()
    if policy.tool_handle_mode == "exact":
        allowed = set(policy.allowed_tool_handles)
        return tuple(handle for handle in HOSTED_CORE_TOOL_HANDLES if handle in allowed)
    return HOSTED_CORE_TOOL_HANDLES


def destination_upstream(context) -> str | None:
    upstreams = context.binding.routing_constraint_snapshot.allowed_upstream_ids
    if not upstreams:
        return None
    if len(upstreams) != 1:
        raise HostedAgenticLoopError("provider_upstream_selection_required")
    return upstreams[0]


def hosted_egress_policy(context, policy) -> AgenticEgressPolicy:
    binding = context.binding
    return AgenticEgressPolicy(
        policy_id=binding.egress_policy_id,
        revision=binding.egress_policy_revision,
        allowed_data_classes=policy.allowed_remote_data_classes,
        allowed_provider_ids=(binding.model_provider_id,),
        allowed_upstream_ids=binding.routing_constraint_snapshot.allowed_upstream_ids,
    )


def hosted_tool_policy(authority, policy) -> RuntimeToolConfirmationPolicy:
    return RuntimeToolConfirmationPolicy(
        policy_revision="|".join(authority.policy_revision_set),
        require_confirmation_for_mutating=policy.require_confirmation_for_mutating,
        require_confirmation_for_destructive=policy.require_confirmation_for_destructive,
        max_tool_result_bytes=policy.max_tool_result_bytes,
    )


def tool_event_payload(
    outcome: RuntimeToolInvocationOutcome,
    *,
    display_state: str | None = None,
) -> dict[str, object]:
    record = outcome.invocation
    return {
        "invocation_id": record.invocation_id,
        "provider_tool_call_id": record.provider_tool_call_id,
        "tool_handle": record.resolved_tool_handle,
        "provider_safe_name": record.provider_safe_name,
        "resolution_status": record.resolution_status,
        "effect_class": record.effect_class,
        "state": display_state or record.state,
        **({"persisted_state": record.state} if display_state and display_state != record.state else {}),
        "arguments_summary": record.arguments_summary,
        "arguments_digest": record.arguments_digest,
        "invocation_revision": record.revision,
        **({"failure_reason": record.failure_reason} if record.failure_reason else {}),
    }


def normalized_tool_result(orchestrator, outcome) -> tuple[dict[str, object], bool]:
    record = outcome.invocation
    if record.state == "succeeded":
        return orchestrator.ledger.load_result(record), False
    if record.state in {"denied", "expired", "failed", "cancelled"}:
        if record.result_private_ref:
            return orchestrator.ledger.load_result(record), True
        return {"error": record.failure_reason or f"tool_{record.state}"}, True
    raise HostedAgenticLoopError("tool_execution_failed")
