"""Provider-domain records for runtime backends and hosted model providers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from core.execution_policy.models import ExecutionMode


ProviderKind = Literal["runtime_backend", "hosted_api"]
ProviderStatus = Literal["active", "disabled", "experimental"]
ProviderBindingStatus = Literal["active", "disabled"]
ProviderSelectionScope = Literal["workspace_default"]


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
