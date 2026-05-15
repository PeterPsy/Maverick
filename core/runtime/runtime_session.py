"""Runtime session records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from core.execution_policy.models import ExecutionMode


RuntimeSessionStatus = Literal["created", "running", "stopping", "stopped", "failed"]
RuntimeApiTokenStatus = Literal["active", "revoked"]
RuntimeSessionGrantOperation = Literal["cleanup", "interrupt", "restart"]
RuntimeSessionGrantPrincipalKind = Literal["user", "app", "runtime_session"]


@dataclass(frozen=True)
class RuntimeSessionGrantRecord:
    """Platform-minted authority grant for one runtime session operation."""

    operation: RuntimeSessionGrantOperation
    grantee_kind: RuntimeSessionGrantPrincipalKind
    grantee_id: str
    issued_by_user_id: str | None = None
    source: Literal["platform"] = "platform"


@dataclass(frozen=True)
class RuntimeSessionRecord:
    """Lifecycle container for one running runtime session."""

    session_id: str
    workspace_id: str
    agent_id: str
    status: RuntimeSessionStatus
    requested_mode: ExecutionMode | None
    effective_mode: ExecutionMode
    workspace_root: str
    workdir: str
    runtime_root: str
    started_at: datetime | None
    updated_at: datetime
    ended_at: datetime | None
    last_progress_at: datetime | None
    system_prompt: str | None = None
    skill_ids: list[str] = field(default_factory=list)
    skill_catalog_app_id: str | None = None
    source_app_id: str | None = None
    owner_user_id: str | None = None
    created_by_user_id: str | None = None
    creator_runtime_session_id: str | None = None
    grants: list[RuntimeSessionGrantRecord | dict[str, str | None]] = field(default_factory=list)
    provider_id: str | None = None
    provider_thread_id: str | None = None


@dataclass(frozen=True)
class RuntimeApiTokenRecord:
    """Store-backed lifecycle state for one runtime bearer token."""

    token_id: str
    session_id: str
    workspace_id: str
    mode: ExecutionMode
    status: RuntimeApiTokenStatus
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
