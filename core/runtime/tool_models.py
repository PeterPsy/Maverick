"""Persistent tool invocation and one-shot confirmation records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


ToolEffectClass = Literal["read", "mutating", "destructive", "unclassified"]
ToolInvocationState = Literal[
    "proposed",
    "validating",
    "denied",
    "validated",
    "awaiting_confirmation",
    "authorized",
    "executing",
    "succeeded",
    "failed",
    "cancelled",
    "expired",
    "execution_unknown",
]
ToolConfirmationState = Literal["active", "consumed", "denied", "expired", "revoked"]


@dataclass(frozen=True)
class ToolInvocationRecord:
    """Revisioned side-effect ledger entry persisted before any invocation."""

    invocation_id: str
    workspace_id: str
    session_id: str
    turn_id: str
    provider_tool_call_id: str
    resolved_tool_handle: str
    arguments_private_ref: str
    arguments_summary: dict[str, object]
    arguments_digest: str
    idempotency_key: str
    effect_class: ToolEffectClass
    state: ToolInvocationState
    policy_revision: str
    authority_digest: str
    confirmation_grant_id: str | None
    result_private_ref: str | None
    result_summary: dict[str, object] | None
    failure_reason: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ToolConfirmationGrant:
    """Non-transferable one-shot confirmation bound to one exact invocation."""

    grant_id: str
    workspace_id: str
    session_id: str
    turn_id: str
    invocation_id: str
    tool_handle: str
    arguments_digest: str
    confirming_actor_id: str
    policy_revision: str
    expires_at: datetime
    state: ToolConfirmationState
    revision: int
    created_at: datetime
    updated_at: datetime
