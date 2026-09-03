"""Pinned destination and effective tool policy helpers for hosted turns."""

from __future__ import annotations

from core.egress.agentic_models import AgenticEgressPolicy
from core.providers.agentic_models import AgenticRuntimePolicy
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.full_workspace_contract import FULL_WORKSPACE_CORE_TOOL_HANDLES
from core.runtime.tool_orchestrator import (
    RuntimeToolConfirmationPolicy,
    RuntimeToolInvocationOutcome,
)
from core.runtime.tool_result_artifacts import project_hosted_tool_result
from core.runtime.hosted_agentic_tool_results import pairing_safe_tool_result


HOSTED_CORE_TOOL_HANDLES = FULL_WORKSPACE_CORE_TOOL_HANDLES
_TOOL_POLICY_FLAG_BY_HANDLE = {
    "core-capability:workspace.instructions": "allow_filesystem_read",
    "core-capability:filesystem.list": "allow_filesystem_list",
    "core-capability:filesystem.search": "allow_filesystem_read",
    "core-capability:filesystem.read": "allow_filesystem_read",
    "core-capability:filesystem.write": "allow_filesystem_write",
    "core-capability:filesystem.edit": "allow_filesystem_write",
    "core-capability:filesystem.patch": "allow_filesystem_write",
    "core-capability:filesystem.move": "allow_filesystem_write",
    "core-capability:filesystem.delete": "allow_filesystem_write",
    "core-capability:shell.run": "allow_shell",
    "core-capability:process.start": "allow_shell",
    "core-capability:process.status": "allow_shell",
    "core-capability:process.input": "allow_shell",
    "core-capability:process.interrupt": "allow_shell",
    "core-capability:artifact.read": "allow_filesystem_read",
}
_TOOL_POLICY_SURFACE_BY_HANDLE = {
    "core-capability:cli.list": "cli",
    "core-capability:cli.run": "cli",
    "core-capability:mcp.list": "mcp",
    "core-capability:mcp.call": "mcp",
}


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


def validate_hosted_request_policy(
    *,
    source_data_classes: tuple[str, ...],
    tool_handles: tuple[str, ...],
    tool_surface_bindings: tuple[tuple[str, str], ...],
    policy: AgenticRuntimePolicy,
) -> None:
    """Validate provider-visible bytes and catalog against one live policy."""
    if any(
        data_class not in policy.allowed_remote_data_classes
        for data_class in source_data_classes
    ):
        raise HostedAgenticLoopError("egress_data_class_denied")
    if tool_handles != tuple(
        handle for handle, _surface_kind in tool_surface_bindings
    ):
        raise HostedAgenticLoopError("tool_not_authorized")
    if tool_handles:
        if policy.tool_handle_mode == "none":
            raise HostedAgenticLoopError("tool_not_authorized")
        if policy.tool_handle_mode == "exact" and any(
            handle not in policy.allowed_tool_handles for handle in tool_handles
        ):
            raise HostedAgenticLoopError("tool_not_authorized")
        if policy.tool_handle_mode not in {"exact", "all_currently_authorized"}:
            raise HostedAgenticLoopError("tool_not_authorized")
        allowed_surfaces = set(policy.allowed_surface_kinds)
        if any(
            surface_kind not in allowed_surfaces
            for _handle, surface_kind in tool_surface_bindings
        ):
            raise HostedAgenticLoopError("tool_capability_denied")
        for handle in tool_handles:
            required_surface = _TOOL_POLICY_SURFACE_BY_HANDLE.get(handle)
            required_flag = _TOOL_POLICY_FLAG_BY_HANDLE.get(handle)
            if (
                required_surface is not None
                and required_surface not in allowed_surfaces
            ) or (
                required_flag is not None
                and not getattr(policy, required_flag, False)
            ):
                raise HostedAgenticLoopError("tool_capability_denied")


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


def normalized_tool_result(
    orchestrator,
    outcome,
    *,
    context_policy=None,
    allowed_remote_data_classes: tuple[str, ...],
) -> tuple[dict[str, object], bool]:
    record = outcome.invocation
    if record.state == "succeeded":
        classification = orchestrator.persisted_result_classification(record)
        result = orchestrator.ledger.load_result(record)
        projected = project_hosted_tool_result(
            result,
            invocation=record,
            context_policy=context_policy,
        )
        # Preserve provider call/result pairing without exporting denied bytes.
        # The original private result remains available only in the ledger.
        return pairing_safe_tool_result(
            projected,
            is_error=False,
            result_data_class=classification.data_class,
            allowed_remote_data_classes=allowed_remote_data_classes,
        )
    if record.state in {"denied", "expired", "failed", "cancelled"}:
        if record.result_private_ref:
            return orchestrator.ledger.load_result(record), True
        return {"error": record.failure_reason or f"tool_{record.state}"}, True
    raise HostedAgenticLoopError("tool_execution_failed")
