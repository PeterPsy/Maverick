"""Restrictive workspace policy and actor selection rules for agentic profiles."""

from __future__ import annotations

from dataclasses import replace

from core.providers.agentic_models import (
    AgenticProfileDefinition,
    AgenticRuntimePolicy,
    WorkspaceAgenticProfileBinding,
)
from core.providers.errors import AgenticProfileError
from core.runtime.authority import intersect_runtime_policies
from core.runtime.execution_binding import canonical_digest


REMOTE_PREVIEW_EGRESS_POLICY_ID = "fake-data-remote-preview"
REMOTE_PREVIEW_EGRESS_POLICY_REVISION = "1"


def actor_selection_allowed(
    binding: WorkspaceAgenticProfileBinding,
    *,
    user_id: str,
    platform_role: str,
    workspace_role: str,
    agent_type_id: str,
) -> bool:
    """Return whether the human actor and selected agent satisfy live policy."""
    if not human_actor_selection_allowed(
        binding,
        user_id=user_id,
        platform_role=platform_role,
        workspace_role=workspace_role,
    ):
        return False
    policy = binding.actor_policy
    return not policy.allowed_agent_type_ids or agent_type_id in policy.allowed_agent_type_ids


def human_actor_selection_allowed(
    binding: WorkspaceAgenticProfileBinding,
    *,
    user_id: str,
    platform_role: str,
    workspace_role: str,
) -> bool:
    """Return whether a human may see and select one workspace profile."""
    policy = binding.actor_policy
    return (
        (policy.allow_workspace_admins and (platform_role == "admin" or workspace_role == "admin"))
        or user_id in policy.allowed_user_ids
        or workspace_role in policy.allowed_workspace_role_ids
    )


def workspace_policy_from_patch(
    profile_policy: AgenticRuntimePolicy,
    patch: dict[str, object],
    *,
    current_policy: AgenticRuntimePolicy | None = None,
) -> AgenticRuntimePolicy:
    """Apply an admin patch without discarding restrictions omitted by the caller."""
    base_policy = current_policy or profile_policy
    numeric_fields = (
        "max_steps_per_turn",
        "max_tool_calls_per_turn",
        "max_wall_time_seconds",
        "max_output_tokens",
    )
    updates: dict[str, object] = {}
    for field in numeric_fields:
        if field not in patch:
            continue
        value = patch[field]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise AgenticProfileError(f"workspace_profile_{field}_invalid")
        updates[field] = value
    if "max_estimated_cost_microusd" in patch:
        value = patch["max_estimated_cost_microusd"]
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise AgenticProfileError("workspace_profile_cost_limit_invalid")
        updates["max_estimated_cost_microusd"] = value
    if "allowed_remote_data_classes" in patch:
        raw_classes = patch["allowed_remote_data_classes"]
        if not isinstance(raw_classes, list) or any(not isinstance(item, str) for item in raw_classes):
            raise AgenticProfileError("workspace_profile_data_classes_invalid")
        allowed = set(profile_policy.allowed_remote_data_classes)
        requested = set(raw_classes)
        if requested - allowed:
            raise AgenticProfileError("workspace_profile_data_classes_widened")
        updates["allowed_remote_data_classes"] = tuple(
            item for item in profile_policy.allowed_remote_data_classes if item in requested
        )
    if patch.get("tool_access_enabled") is False:
        updates.update(tool_handle_mode="none", allowed_tool_handles=())
    elif patch.get("tool_access_enabled") is True and base_policy.tool_handle_mode == "none":
        updates.update(
            tool_handle_mode=profile_policy.tool_handle_mode,
            allowed_tool_handles=profile_policy.allowed_tool_handles,
        )
    for field in (
        "require_confirmation_for_mutating",
        "require_confirmation_for_destructive",
    ):
        if field in patch:
            value = patch[field]
            if not isinstance(value, bool):
                raise AgenticProfileError(f"workspace_profile_{field}_invalid")
            updates[field] = value
    candidate = replace(base_policy, **updates)
    effective = intersect_runtime_policies(profile_policy, candidate)
    if canonical_digest(effective) != canonical_digest(candidate):
        raise AgenticProfileError("workspace_profile_policy_widened")
    return candidate


def egress_policy_for_definition(definition: AgenticProfileDefinition) -> tuple[str, str]:
    """Return publisher-owned egress metadata without inferring engine semantics."""
    return definition.egress_policy_id, definition.egress_policy_revision
