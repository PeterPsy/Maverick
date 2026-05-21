"""Shared helpers for core-owned CLI command definitions."""

from __future__ import annotations

from typing import Any

from core.cli.models import CliCommandDefinition, CliInvocationPolicy
from core.observability.service import record_platform_audit, record_platform_event


GLOBAL_AGENT_SAFE = CliInvocationPolicy(False, None, True, False, False)
FULL_ACCESS_ADMIN = CliInvocationPolicy(False, "admin", False, True, True)
FULL_ACCESS_WORKSPACE = CliInvocationPolicy(False, None, False, True, True)
OPERATOR_ONLY = CliInvocationPolicy(True, None, False, False, False)
WORKSPACE_SAFE = CliInvocationPolicy(False, None, True, True, False)


def core_cli_command(
    *,
    command_id: str,
    path_segments: list[str],
    description: str,
    owner_id: str,
    invocation_policy: CliInvocationPolicy,
) -> CliCommandDefinition:
    """Build one core-owned CLI command definition."""
    return CliCommandDefinition(
        command_id=command_id,
        path_segments=path_segments,
        description=description,
        argument_schema={"type": "object"},
        owner_kind="core",
        owner_id=owner_id,
        workspace_id=None,
        exposure_scope="core_global",
        invocation_policy=invocation_policy,
        entrypoint_path=None,
    )


def record_cli_audit(
    observability_store,
    *,
    action: str,
    detail: str,
    payload: dict[str, Any],
    workspace_id: str | None = None,
    provider_id: str | None = None,
    runtime_session_id: str | None = None,
) -> None:
    """Emit redaction-safe CLI audit and event records when a store is configured."""
    if observability_store is None:
        return
    record_platform_audit(
        observability_store,
        action=action,
        status="succeeded",
        source_domain="cli",
        detail=detail,
        workspace_id=workspace_id,
        provider_id=provider_id,
        runtime_session_id=runtime_session_id,
        payload=payload,
    )
    record_platform_event(
        observability_store,
        event_type=action,
        event_plane="platform" if runtime_session_id is None else "runtime",
        source_domain="cli",
        workspace_id=workspace_id,
        provider_id=provider_id,
        runtime_session_id=runtime_session_id,
        payload=payload,
    )
