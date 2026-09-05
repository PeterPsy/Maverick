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
ProfileRolloutStatus = Literal["disabled", "preview", "available", "suspended"]
ContextCompactionMode = Literal["disabled", "provider_history"]
AttachmentProjectionMode = Literal["workspace_reference", "native_or_reference"]
SteeringDeliveryMode = Literal["provider_native", "safe_next_turn"]
ModelRevisionPolicy = Literal["exact", "provider_alias"]


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
    max_parallel_tool_calls: int
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
    """Immutable installation-level engine/provider/model combination."""

    definition_id: str
    revision: str
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
    capability_certificate_id: str
    created_at: datetime
    egress_policy_id: str
    egress_policy_revision: str
    full_workspace_contract_revision: str = ""
    execution_family: str = ""
    harness_recipe_id: str = ""
    harness_recipe_revision: str = ""
    harness_recipe_digest: str = ""
    provider_capability_catalog_digest: str = ""
    semantic_projection_compiler_revision: str = ""
    tool_contract_revision: str = ""
    context_policy: AgenticContextPolicy | None = None
    model_revision: str | None = None
    model_revision_policy: ModelRevisionPolicy = "provider_alias"
    provider_config_id: str = ""
    provider_config_revision: str = ""
    provider_config_digest: str = ""
    protocol_adapter_id: str = ""
    protocol_adapter_version: str = ""
    native_model_catalog_digest: str = ""


@dataclass(frozen=True)
class AgenticProfileDefinitionStatus:
    """Revisioned rollout state separated from an immutable definition."""

    definition_id: str
    definition_revision: str
    rollout_status: ProfileRolloutStatus
    revision: int
    updated_at: datetime


@dataclass(frozen=True)
class WorkspaceAgenticProfileBinding:
    """Workspace governance binding for one exact profile revision."""

    binding_id: str
    workspace_id: str
    definition_id: str
    definition_revision: str
    credential_binding_id: str | None
    enabled: bool
    is_default: bool
    actor_policy: ActorSelectionPolicy
    workspace_policy_ceiling: AgenticRuntimePolicy
    egress_policy_id: str
    egress_policy_revision: str
    revision: int
    created_at: datetime
    updated_at: datetime
    lineage_binding_ids: tuple[str, ...] = ()
    admission_enabled_at: datetime | None = None
    admission_disabled_at: datetime | None = None


@dataclass(frozen=True)
class AgenticMigrationRecord:
    """Redaction-safe journal for one idempotent agentic schema migration."""

    migration_id: str
    schema_version: str
    status: Literal["started", "completed", "failed"]
    profile_count: int
    binding_count: int
    session_count: int
    inferred_session_count: int
    summary_digest: str
    created_at: datetime
    updated_at: datetime


def codex_runtime_policy() -> AgenticRuntimePolicy:
    """Return the non-enforced Phase-0 ceiling matching current Codex behavior."""
    return AgenticRuntimePolicy(
        max_steps_per_turn=256,
        max_tool_calls_per_turn=256,
        max_parallel_tool_calls=0,
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
