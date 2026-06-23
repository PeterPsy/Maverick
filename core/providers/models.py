"""Provider-domain records for runtime backends and hosted model providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from core.execution_policy.models import ExecutionMode


ProviderKind = Literal["runtime_backend", "hosted_api"]
ProviderRole = Literal["runtime_engine", "model_provider", "speech_provider"]
ProviderStatus = Literal["active", "disabled", "experimental"]
ProviderBindingStatus = Literal["active", "disabled"]
ProviderSelectionScope = Literal["workspace_default"]
ProviderHostedSelectionProfile = Literal["fast_model"]
ProviderBlockedReason = Literal["no_provider_configured", "provider_unavailable"]
ProviderSecretBindingScope = Literal["provider", "app", "provider_or_app"]
ProviderSecretResolutionStage = Literal["execution_only"]
ProviderRoutingProfile = Literal["fast_model", "plain_hosted_chat", "heavy_runtime"]


@dataclass(frozen=True)
class ProviderReasoningOption:
    """One provider-supported reasoning effort for a model."""

    effort: str
    label: str
    description: str | None = None


@dataclass(frozen=True)
class ProviderModelOption:
    """One model option reported by a provider adapter."""

    model_id: str
    label: str
    description: str | None
    default_reasoning_effort: str | None
    supported_reasoning_efforts: list[ProviderReasoningOption] = field(default_factory=list)


@dataclass(frozen=True)
class ProviderCapabilitySet:
    """Capability metadata exposed by one provider definition."""

    supports_interactive_runtime: bool
    supports_streaming: bool
    supports_tools: bool
    supports_mcp: bool
    supports_skills: bool
    supports_filesystem_access: bool
    supports_remote_execution: bool
    supports_api_key_auth: bool
    supports_local_binary: bool
    input_modalities: list[str] = field(default_factory=list)
    output_modalities: list[str] = field(default_factory=list)
    supports_streaming_input: bool = False
    supports_streaming_output: bool = False
    supports_realtime: bool = False
    supports_tool_calling: bool = False
    supports_structured_output: bool = False
    supports_turn_detection: bool = False
    supports_barge_in: bool = False
    latency_class: str | None = None
    future_only_supports_local_execution: bool = False
    future_only_supports_offline_mode: bool = False


@dataclass(frozen=True)
class ProviderCredentialRequirement:
    """Describe a provider secret requirement without carrying the secret value."""

    secret_alias_or_logical_name: str
    secret_kind: str
    required_for_modes: list[str] = field(default_factory=list)
    secret_binding_scope: ProviderSecretBindingScope = "provider"
    provider_credential_binding_id_optional: str | None = None
    app_secret_grant_id_optional: str | None = None
    rotation_policy_optional: str | None = None
    redaction_required: bool = True
    resolution_stage: ProviderSecretResolutionStage = "execution_only"


@dataclass(frozen=True)
class ProviderNetworkRequirement:
    """Describe a provider's outbound network needs as redaction-safe metadata."""

    outbound_required: bool
    allowed_hosts: list[str] = field(default_factory=list)
    transport: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class ProviderExecutionContract:
    """Describe how a model provider can be executed by a Maverick-owned adapter."""

    adapter_type: str | None = None
    request_shape: str | None = None
    streaming_supported: bool = False
    non_streaming_supported: bool = False
    timeout_policy: str | None = None
    error_mapping: dict[str, str] = field(default_factory=dict)
    secret_alias_or_logical_name: str | None = None
    transport_test_mode: str | None = None


@dataclass(frozen=True)
class ProviderDefinition:
    """Canonical provider definition owned by the platform core."""

    provider_id: str
    label: str
    description: str
    kind: ProviderKind
    status: ProviderStatus
    capabilities: ProviderCapabilitySet
    default_model_family: str | None
    requires_credentials: bool
    supported_execution_modes: list[ExecutionMode]
    created_at: datetime
    updated_at: datetime
    model_options: list[ProviderModelOption] = field(default_factory=list)
    provider_role: ProviderRole = "runtime_engine"
    credential_requirements: list[ProviderCredentialRequirement] = field(default_factory=list)
    network_requirements: list[ProviderNetworkRequirement] = field(default_factory=list)
    execution_contract: ProviderExecutionContract | None = None
    cost_metadata: dict[str, object] = field(default_factory=dict)
    latency_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderCredentialBinding:
    """Reference one operator-managed secret binding for one provider."""

    binding_id: str
    provider_id: str
    workspace_id: str | None
    secret_ref: str
    label: str | None
    status: ProviderBindingStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ProviderSelection:
    """Persist the selected provider for one workspace execution context."""

    selection_id: str
    workspace_id: str
    provider_id: str
    binding_id: str | None
    selection_scope: ProviderSelectionScope
    selection_reason: str
    created_at: datetime
    updated_at: datetime
    model_id: str | None = None
    model_reasoning_effort: str | None = None


@dataclass(frozen=True)
class ProviderHostedSelection:
    """Persist the hosted text provider/model selection for one workspace profile."""

    selection_id: str
    workspace_id: str
    profile: ProviderHostedSelectionProfile
    provider_id: str
    selection_reason: str
    created_at: datetime
    updated_at: datetime
    model_id: str | None = None


@dataclass(frozen=True)
class WorkspaceProviderStatus:
    """Resolved provider state for one workspace."""

    workspace_id: str
    configured: bool
    active_provider: ProviderDefinition | None
    selection: ProviderSelection | None
    available_providers: list[ProviderDefinition]
    blocked_reason: ProviderBlockedReason | None = None
    blocked_detail: str | None = None


@dataclass(frozen=True)
class RuntimeBackendLaunchSpec:
    """Describe how one runtime backend should be launched."""

    provider_id: str
    command: list[str]
    env_overrides: dict[str, str]
    credential_binding_id: str | None
    resolved_secret_refs: list[str]
    working_directory: str
    execution_mode: ExecutionMode
    readable_roots: list[str]
    writable_roots: list[str]


@dataclass(frozen=True)
class WorkspaceProviderPolicy:
    """Minimal workspace policy used by provider routing decisions."""

    workspace_id: str
    allowed_provider_ids: list[str] = field(default_factory=list)
    allowed_model_ids: list[str] = field(default_factory=list)
    plan_or_tier_rules: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    fallback_rules: dict[str, bool] = field(default_factory=dict)
    default_profiles: dict[str, str] = field(default_factory=dict)
    audit_enabled: bool = True
    policy_id_or_version: str = "default"


@dataclass(frozen=True)
class RoutingDecision:
    """Redaction-safe provider routing decision suitable for logs and APIs."""

    request_id: str
    workspace_id: str
    profile: str
    requested_capabilities: list[str]
    candidate_provider_ids: list[str]
    selected_provider_id: str | None
    selected_model_id_or_voice_id: str | None
    selected_runtime_engine_id: str | None
    execution_path: str | None
    policy_id_or_version: str
    credential_authorization_required: bool
    provider_credential_binding_id_optional: str | None
    app_secret_grant_id_optional: str | None
    fallback_used: bool
    reason_codes: list[str]
    created_at: datetime
    provider_secret_binding_id_optional: str | None = None
