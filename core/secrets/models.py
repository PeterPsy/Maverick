"""Secret-domain records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


SecretStatus = Literal["active", "disabled", "revoked"]
SecretBindingStatus = Literal["active", "disabled"]
SecretBindingScope = Literal["workspace", "app", "provider"]
SecretRefKind = Literal["secret_id", "alias"]
SecretKind = Literal["generic", "password", "api_key", "oauth_token", "private_key"]
SecretGrantStatus = Literal["active", "revoked"]


@dataclass(frozen=True)
class SecretRecord:
    """Platform-owned secret metadata without the raw secret value."""

    secret_id: str
    alias: str | None
    label: str
    description: str | None
    status: SecretStatus
    created_at: datetime
    updated_at: datetime
    kind: SecretKind = "generic"


@dataclass(frozen=True)
class SecretBindingRecord:
    """Bind one platform secret reference to one workspace, app, or provider use."""

    binding_id: str
    scope: SecretBindingScope
    workspace_id: str | None
    app_id: str | None
    provider_id: str | None
    secret_ref: str
    logical_name: str
    status: SecretBindingStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SecretRef:
    """Normalized parsed representation of one secret reference string."""

    raw_ref: str
    kind: SecretRefKind
    value: str


@dataclass(frozen=True)
class SecretResolutionContext:
    """Caller context used to authorize one secret resolution request."""

    workspace_id: str | None
    app_id: str | None = None
    provider_id: str | None = None
    runtime_session_id: str | None = None
    operator_request: bool = False
    allow_unbound_secret_refs: bool = False
    platform_delivery: bool = False
    action: str | None = None
    target: str | None = None
    actor_user_id: str | None = None
    request_context: dict[str, str] | None = None


@dataclass(frozen=True)
class ResolvedSecretLease:
    """Short-lived secret resolution result for runtime use."""

    lease_id: str
    secret_id: str
    secret_ref: str
    source_binding_id: str | None
    value: str
    redacted_value: str
    issued_at: datetime
    source_grant_id: str | None = None


@dataclass(frozen=True)
class SecretGrantRecord:
    """Authorize one app to use a platform secret for scoped actions and targets."""

    grant_id: str
    workspace_id: str
    app_id: str
    secret_ref: str
    logical_name: str
    actions: list[str]
    target_patterns: list[str]
    status: SecretGrantStatus
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    created_by_user_id: str | None = None
    reason: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
