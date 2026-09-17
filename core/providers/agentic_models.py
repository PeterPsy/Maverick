"""Installation and workspace records for agentic runtime profiles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


RuntimeDataClass = Literal[
    "public",
    "workspace_internal_fake",
    "workspace_internal",
    "personal_data",
    "credential_or_secret",
    "regulated_or_customer_data",
    "host_operational_metadata",
    "unclassified",
]
ToolHandleMode = Literal["none", "all_currently_authorized", "exact"]
RuntimeSurfaceKind = Literal["cli", "mcp", "app-interface", "core-capability"]
ContextCompactionMode = Literal["disabled", "provider_history"]
AttachmentProjectionMode = Literal["workspace_reference", "native_or_reference"]
SteeringDeliveryMode = Literal["provider_native", "safe_next_turn"]
ModelRevisionPolicy = Literal["exact", "provider_alias"]

ParallelToolCallLimit = Literal["unbounded"]
UNBOUNDED_PARALLEL_TOOL_CALLS: ParallelToolCallLimit = "unbounded"


@dataclass(frozen=True)
class RuntimeCapabilitySet:
    """Behaviors implemented by one runtime profile.

    Capabilities are part of the profile contract and have no independent
    issuance, renewal, or expiry lifecycle.
    """

    streaming: bool
    tool_orchestration: bool
    cli: bool
    mcp: bool
    skill_catalog: bool
    filesystem_list: bool
    filesystem_read: bool
    filesystem_write: bool
    shell: bool
    interrupt: bool
    same_turn_steering: bool
    recovery: bool
    confirmation_resume: bool
    provider_private_state: bool
    attachment_modalities: tuple[str, ...]
    app_references: bool = False
    confirmations: bool = False


@dataclass(frozen=True)
class AgenticContextPolicy:
    """Profile-pinned context window, compaction, and interaction contract."""

    revision: str
    max_request_input_tokens: int
    context_reserve_tokens: int
    compaction_mode: ContextCompactionMode
    compaction_trigger_tokens: int
    max_compacted_state_bytes: int
    summary_max_bytes: int
    tool_result_inline_bytes: int
    tool_result_summary_bytes: int
    attachment_projection_mode: AttachmentProjectionMode
    steering_delivery_mode: SteeringDeliveryMode
    max_same_turn_steering_messages: int


@dataclass(frozen=True)
class AgenticRuntimePolicy:
    """One immutable ceiling for agentic runtime work."""

    max_steps_per_turn: int
    max_tool_calls_per_turn: int
    # This compatibility-named field is not an independent concurrency limit.
    # New bindings persist the explicit ``unbounded`` contract; hydration still
    # accepts legacy zero-valued session pins in authority validation.
    max_parallel_tool_calls: ParallelToolCallLimit
    max_wall_time_seconds: int
    max_tool_result_bytes: int
    max_total_tool_result_bytes: int
    max_input_tokens: int
    max_output_tokens: int
    max_estimated_cost_microusd: int | None
    allowed_surface_kinds: tuple[RuntimeSurfaceKind, ...]
    tool_handle_mode: ToolHandleMode
    allowed_tool_handles: tuple[str, ...]
    allow_filesystem_list: bool
    allow_filesystem_read: bool
    allow_filesystem_write: bool
    allow_shell: bool
    require_confirmation_for_mutating: bool
    require_confirmation_for_destructive: bool
    allowed_remote_data_classes: tuple[RuntimeDataClass, ...]


@dataclass(frozen=True)
class RoutingConstraint:
    """Pinned endpoint and upstream constraints for one profile."""

    endpoint_id: str
    allowed_upstream_ids: tuple[str, ...]
    allow_fallbacks: bool
    require_parameters: bool
    data_collection_policy: Literal["provider_contract", "deny"]
    require_zdr: bool
    allowed_quantizations: tuple[str, ...]


@dataclass(frozen=True)
class ActorSelectionPolicy:
    """Actors allowed to select a workspace profile without granting tools."""

    allow_workspace_admins: bool
    allowed_user_ids: tuple[str, ...]
    allowed_workspace_role_ids: tuple[str, ...]
    allowed_agent_type_ids: tuple[str, ...]


@dataclass(frozen=True)
class AgenticProfileDefinition:
    """Current installation-level engine/provider/model configuration.

    A definition is replaced in place when its implementation changes.  It is
    not a release artifact and has no rollout, renewal, expiry, or historical
    revision lifecycle.
    """

    definition_id: str
    display_name: str
    runtime_engine_id: str
    model_provider_id: str
    model_id: str
    provider_protocol: str
    provider_api_version: str | None
    adapter_id: str
    adapter_version_constraint: str
    routing_constraint: RoutingConstraint
    policy_ceiling: AgenticRuntimePolicy
    capabilities: RuntimeCapabilitySet
    reasoning_efforts: tuple[str, ...]
    default_reasoning_effort: str | None
    created_at: datetime
    egress_policy_id: str
    egress_policy_revision: str
    context_policy: AgenticContextPolicy | None = None
    model_revision: str | None = None
    model_revision_policy: ModelRevisionPolicy = "provider_alias"
    revision: str = "1"
    execution_family: str = ""


ProfileRolloutStatus = Literal["disabled", "preview", "available", "suspended"]


@dataclass(frozen=True)
class AgenticProfileDefinitionStatus:
    """Rollout status record."""

    definition_id: str
    definition_revision: str
    rollout_status: ProfileRolloutStatus
    revision: int
    updated_at: datetime


@dataclass(frozen=True)
class WorkspaceAgenticProfileBinding:
    """Direct workspace configuration for one provider/model definition."""

    binding_id: str
    workspace_id: str
    definition_id: str
    credential_binding_id: str | None
    enabled: bool
    is_default: bool
    actor_policy: ActorSelectionPolicy
    workspace_policy_ceiling: AgenticRuntimePolicy
    egress_policy_id: str
    egress_policy_revision: str
    created_at: datetime
    updated_at: datetime
    definition_revision: str = "1"
    revision: int = 1


@dataclass(frozen=True)
class AgenticMigrationRecord:
    """Migration journal record."""

    migration_id: str
    schema_version: str
    status: Literal["started", "completed", "failed"]
    profile_count: int = 0
    binding_count: int = 0
    session_count: int = 0
    inferred_session_count: int = 0
    summary_digest: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


def codex_runtime_policy() -> AgenticRuntimePolicy:
    """Return the non-enforced Phase-0 ceiling matching current Codex behavior."""
    return AgenticRuntimePolicy(
        max_steps_per_turn=256,
        max_tool_calls_per_turn=256,
        max_parallel_tool_calls=UNBOUNDED_PARALLEL_TOOL_CALLS,
        max_wall_time_seconds=86_400,
        max_tool_result_bytes=1_048_576,
        max_total_tool_result_bytes=16_777_216,
        max_input_tokens=1_000_000,
        max_output_tokens=128_000,
        max_estimated_cost_microusd=None,
        allowed_surface_kinds=("cli", "mcp", "app-interface", "core-capability"),
        tool_handle_mode="all_currently_authorized",
        allowed_tool_handles=(),
        allow_filesystem_list=True,
        allow_filesystem_read=True,
        allow_filesystem_write=True,
        allow_shell=True,
        require_confirmation_for_mutating=False,
        require_confirmation_for_destructive=False,
        allowed_remote_data_classes=(),
    )


def codex_runtime_capabilities() -> RuntimeCapabilitySet:
    """Return the capabilities implemented by the Codex app-server adapter."""
    return RuntimeCapabilitySet(
        streaming=True,
        tool_orchestration=True,
        cli=True,
        mcp=True,
        skill_catalog=True,
        filesystem_list=True,
        filesystem_read=True,
        filesystem_write=True,
        shell=True,
        interrupt=True,
        same_turn_steering=True,
        recovery=True,
        confirmation_resume=False,
        provider_private_state=False,
        attachment_modalities=("file",),
        app_references=True,
        confirmations=False,
    )


def codex_routing_constraint() -> RoutingConstraint:
    """Return the local app-server routing constraint used by Codex profiles."""
    return RoutingConstraint(
        endpoint_id="local-codex-app-server",
        allowed_upstream_ids=(),
        allow_fallbacks=False,
        require_parameters=True,
        data_collection_policy="provider_contract",
        require_zdr=False,
        allowed_quantizations=(),
    )


def default_actor_selection_policy() -> ActorSelectionPolicy:
    """Preserve current workspace-member selection while recording it explicitly."""
    return ActorSelectionPolicy(
        allow_workspace_admins=True,
        allowed_user_ids=(),
        allowed_workspace_role_ids=("admin", "member"),
        allowed_agent_type_ids=(),
    )
