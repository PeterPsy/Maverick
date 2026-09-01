"""Models for the platform-managed CLI surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from core.execution_policy.models import ExecutionMode
from core.identity.models import PlatformRole
from core.shared.tool_effects import ToolArgumentEffectMap


CliOwnerKind = Literal["core", "app"]
CliExposureScope = Literal["core_global", "workspace_enabled_app"]
CliCallerKind = Literal["operator", "sandbox_agent", "full_access_agent"]
CliEffectClass = Literal["read", "mutating", "destructive", "unclassified"]
CliAgenticResultDataClass = Literal["public"]


@dataclass(frozen=True)
class CliInvocationPolicy:
    """Policy gates applied before one CLI command may run."""

    operator_only: bool
    required_platform_role: PlatformRole | None
    sandbox_agent_allowed: bool
    requires_workspace_context: bool
    requires_full_access: bool


@dataclass(frozen=True)
class CliCommandDefinition:
    """Describe one command surfaced by the Maverick platform."""

    command_id: str
    path_segments: list[str]
    description: str
    argument_schema: dict[str, Any]
    owner_kind: CliOwnerKind
    owner_id: str
    workspace_id: str | None
    exposure_scope: CliExposureScope
    invocation_policy: CliInvocationPolicy
    entrypoint_path: str | None
    effect_class: CliEffectClass = "unclassified"
    supports_idempotency: bool = False
    safe_to_retry: bool = False
    schema_public: bool = False
    certified_tcb_component: str | None = None
    agentic_result_data_class: CliAgenticResultDataClass | None = None
    argument_effects: ToolArgumentEffectMap | None = None


@dataclass(frozen=True)
class CliInvocationContext:
    """Trusted invocation context resolved by the platform before CLI execution."""

    caller_kind: CliCallerKind
    workspace_id: str | None
    agent_id: str | None
    effective_mode: ExecutionMode | None
    platform_role: PlatformRole | None = None
    user_id: str | None = None
    workspace_role: str | None = None
    runtime_session_id: str | None = None
    idempotency_key: str | None = None
