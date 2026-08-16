"""Runtime session records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from core.execution_policy.models import ExecutionMode


RuntimeSessionStatus = Literal["created", "running", "stopping", "stopped", "failed"]
RuntimeApiTokenStatus = Literal["active", "revoked"]
RuntimeSessionGrantOperation = Literal[
    "cleanup",
    "interrupt",
    "restart",
    "inter_agent_root",
    "turn_submit",
    "read_transcript",
]
RuntimeSessionGrantPrincipalKind = Literal["user", "app", "runtime_session"]
RuntimeSessionKind = Literal["chat_root", "inter_agent_participant", "system"]
RuntimeThreadVisibility = Literal["user", "hidden"]
RuntimeMode = Literal["agentic", "plain_hosted_chat"]
SkillActivationMode = Literal["implicit", "explicit"]

RUNTIME_SESSION_KINDS = {"chat_root", "inter_agent_participant", "system"}
RUNTIME_THREAD_VISIBILITIES = {"user", "hidden"}
RUNTIME_MODES = {"agentic", "plain_hosted_chat"}
SKILL_ACTIVATION_MODES = {"implicit", "explicit"}


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
    session_kind: RuntimeSessionKind = "chat_root"
    thread_visibility: RuntimeThreadVisibility = "user"
    runtime_mode: RuntimeMode = "agentic"
    system_prompt: str | None = None
    skill_ids: list[str] = field(default_factory=list)
    skill_catalog_app_id: str | None = None
    skill_activation_mode: SkillActivationMode = "implicit"
    source_app_id: str | None = None
    thread_title: str = ""
    agent_label: str = ""
    agent_type_id: str = ""
    agent_role_id: str = ""
    project_id: str | None = None
    owner_user_id: str | None = None
    created_by_user_id: str | None = None
    creator_runtime_session_id: str | None = None
    grants: list[RuntimeSessionGrantRecord | dict[str, str | None]] = field(default_factory=list)
    provider_id: str | None = None
    provider_thread_id: str | None = None
    hosted_provider_id: str | None = None
    hosted_model_id: str | None = None


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


def coerce_runtime_session_kind(value: object | None) -> RuntimeSessionKind:
    """Return a supported runtime session kind, defaulting only for omitted legacy data."""
    if value is None or value == "":
        return "chat_root"
    normalized = str(value).strip()
    if normalized in RUNTIME_SESSION_KINDS:
        return normalized  # type: ignore[return-value]
    raise ValueError(f"Unsupported runtime session kind `{normalized}`.")


def coerce_runtime_thread_visibility(value: object | None) -> RuntimeThreadVisibility:
    """Return a supported runtime thread visibility, defaulting only for omitted legacy data."""
    if value is None or value == "":
        return "user"
    normalized = str(value).strip()
    if normalized in RUNTIME_THREAD_VISIBILITIES:
        return normalized  # type: ignore[return-value]
    raise ValueError(f"Unsupported runtime thread visibility `{normalized}`.")


def coerce_runtime_mode(value: object | None) -> RuntimeMode:
    """Return a supported runtime mode, defaulting only for omitted legacy data."""
    if value is None or value == "":
        return "agentic"
    normalized = str(value).strip()
    if normalized in RUNTIME_MODES:
        return normalized  # type: ignore[return-value]
    raise ValueError(f"Unsupported runtime mode `{normalized}`.")


def coerce_skill_activation_mode(value: object | None) -> SkillActivationMode:
    """Return a supported skill mode, preserving implicit behavior for legacy records."""
    if value is None or value == "":
        return "implicit"
    normalized = str(value).strip()
    if normalized in SKILL_ACTIVATION_MODES:
        return normalized  # type: ignore[return-value]
    raise ValueError(f"Unsupported skill activation mode `{normalized}`.")


def normalize_runtime_session_visibility(
    session_kind: object | None,
    thread_visibility: object | None,
) -> tuple[RuntimeSessionKind, RuntimeThreadVisibility]:
    """Return a valid session kind and thread visibility pair.

    Legacy records may omit both fields and remain user-visible chat roots. Once
    a record is explicitly an inter-agent participant, the only safe visibility
    is hidden.
    """
    kind = coerce_runtime_session_kind(session_kind)
    if kind == "inter_agent_participant" and (thread_visibility is None or thread_visibility == ""):
        return kind, "hidden"
    visibility = coerce_runtime_thread_visibility(thread_visibility)
    if kind == "inter_agent_participant" and visibility != "hidden":
        raise ValueError("inter_agent_participant runtime sessions must use hidden thread visibility.")
    return kind, visibility


def runtime_session_from_document(document: Mapping[str, object]) -> RuntimeSessionRecord:
    """Hydrate and validate one runtime session document."""
    payload = dict(document)
    session_kind, thread_visibility = normalize_runtime_session_visibility(
        payload.get("session_kind"),
        payload.get("thread_visibility"),
    )
    payload["session_kind"] = session_kind
    payload["thread_visibility"] = thread_visibility
    payload["runtime_mode"] = coerce_runtime_mode(payload.get("runtime_mode"))
    payload["skill_activation_mode"] = coerce_skill_activation_mode(payload.get("skill_activation_mode"))
    return RuntimeSessionRecord(**payload)


def runtime_session_allows_user_thread(session: RuntimeSessionRecord) -> bool:
    """Return whether this runtime session may be represented by a user-visible thread."""
    try:
        _kind, visibility = normalize_runtime_session_visibility(
            getattr(session, "session_kind", None),
            getattr(session, "thread_visibility", None),
        )
    except ValueError:
        return False
    return visibility == "user"
