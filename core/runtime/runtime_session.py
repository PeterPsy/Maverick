"""Runtime session records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from core.execution_policy.models import ExecutionMode
from core.providers.agentic_models import RuntimeDataClass
from core.providers.hosted_text_profiles import (
    HostedTextExecutionBinding,
    hosted_text_binding_from_document,
)
from core.runtime.execution_binding import RuntimeExecutionBinding, execution_binding_from_document


RuntimeSessionStatus = Literal[
    "created",
    "running",
    "stopping",
    "stopped",
    "failed",
    "recovery_required",
]
RuntimeSessionPreparationStatus = Literal["unprepared", "prepared"]
RuntimeApiTokenStatus = Literal["active", "revoked"]
RuntimeSessionGrantOperation = Literal[
    "cleanup",
    "interrupt",
    "restart",
    "inter_agent_root",
    "turn_submit",
    "tool_confirm",
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
LEGACY_DECLARED_REMOTE_DATA_CLASSES = {"public", "workspace_internal_fake"}


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
    preparation_status: RuntimeSessionPreparationStatus = "prepared"
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
    predecessor_session_id: str | None = None
    lineage_root_session_id: str | None = None
    continuation_handoff_id: str | None = None
    continuation_fork_reason: str | None = None
    continuation_successor_session_id: str | None = None
    grants: list[RuntimeSessionGrantRecord | dict[str, str | None]] = field(default_factory=list)
    execution_binding: RuntimeExecutionBinding | None = None
    hosted_text_binding: HostedTextExecutionBinding | None = None
    provider_id: str | None = None
    provider_thread_id: str | None = None
    hosted_provider_id: str | None = None
    hosted_model_id: str | None = None
    declared_remote_data_class: RuntimeDataClass | None = None
    recovery_reason_code: str | None = None
    prepared_session_fingerprint: str | None = None

    authorization_domain: str = "production"
    lab_installation_id: str | None = None


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


def coerce_declared_remote_data_class(value: object | None) -> RuntimeDataClass | None:
    """Normalize legacy stored metadata; this value never grants admission."""
    if value is None or value == "":
        return None
    normalized = str(value).strip()
    if normalized in LEGACY_DECLARED_REMOTE_DATA_CLASSES:
        return normalized  # type: ignore[return-value]
    raise ValueError("Unsupported declared remote data class.")


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
    # Records written before the preparation barrier was introduced were only
    # returned after all initial state writes completed, so they are prepared.
    payload.setdefault("preparation_status", "prepared")
    payload.setdefault("recovery_reason_code", None)
    payload.setdefault("prepared_session_fingerprint", None)
    session_kind, thread_visibility = normalize_runtime_session_visibility(
        payload.get("session_kind"),
        payload.get("thread_visibility"),
    )
    payload["session_kind"] = session_kind
    payload["thread_visibility"] = thread_visibility
    payload["runtime_mode"] = coerce_runtime_mode(payload.get("runtime_mode"))
    payload["skill_activation_mode"] = coerce_skill_activation_mode(payload.get("skill_activation_mode"))
    payload["declared_remote_data_class"] = coerce_declared_remote_data_class(
        payload.get("declared_remote_data_class")
    )
    execution_binding = payload.get("execution_binding")
    if isinstance(execution_binding, dict):
        payload["execution_binding"] = execution_binding_from_document(execution_binding)
    elif execution_binding is not None and not isinstance(execution_binding, RuntimeExecutionBinding):
        raise ValueError("Runtime execution binding must be an object.")
    hosted_text_binding = payload.get("hosted_text_binding")
    if isinstance(hosted_text_binding, Mapping):
        payload["hosted_text_binding"] = hosted_text_binding_from_document(
            hosted_text_binding
        )
    elif hosted_text_binding is not None and not isinstance(
        hosted_text_binding,
        HostedTextExecutionBinding,
    ):
        raise ValueError("Hosted text execution binding must be an object.")
    payload.setdefault("hosted_text_binding", None)
    payload.setdefault("authorization_domain", "production")
    payload.setdefault("lab_installation_id", None)
    binding = payload.get("execution_binding")
    domain = payload["authorization_domain"]
    if domain not in {"production", "certification_lab"} or (
        binding is not None and binding.authorization_domain != domain
    ) or (domain == "production" and payload["lab_installation_id"] is not None):
        raise ValueError("Runtime session authorization domain mismatch.")
    if domain == "certification_lab" and (
        binding is None or payload["lab_installation_id"] != binding.lab_permit_reference.installation_id
        or binding.session_id != payload["session_id"] or binding.workspace_id != payload["workspace_id"]
    ):
        raise ValueError("Runtime lab session identity mismatch.")
    _validate_runtime_family_pins(payload)
    return RuntimeSessionRecord(**payload)


def _validate_runtime_family_pins(payload: Mapping[str, object]) -> None:
    """Prevent one stored session from carrying authority for two families."""
    runtime_mode = payload.get("runtime_mode")
    execution_binding = payload.get("execution_binding")
    hosted_text_binding = payload.get("hosted_text_binding")
    if runtime_mode == "plain_hosted_chat" and execution_binding is not None:
        raise ValueError("Text-only runtime session cannot carry an agentic binding.")
    if runtime_mode == "agentic" and hosted_text_binding is not None:
        raise ValueError("Agentic runtime session cannot carry a text-only binding.")
    if isinstance(hosted_text_binding, HostedTextExecutionBinding):
        if (
            hosted_text_binding.session_id != payload.get("session_id")
            or hosted_text_binding.workspace_id != payload.get("workspace_id")
            or hosted_text_binding.provider_id != payload.get("hosted_provider_id")
            or hosted_text_binding.model_id != payload.get("hosted_model_id")
        ):
            raise ValueError("Hosted text execution binding does not match its session.")


def runtime_session_allows_user_thread(session: RuntimeSessionRecord) -> bool:
    """Return whether this runtime session may be represented by a user-visible thread."""
    if str(
        getattr(session, "continuation_successor_session_id", None) or ""
    ).strip():
        return False
    try:
        _kind, visibility = normalize_runtime_session_visibility(
            getattr(session, "session_kind", None),
            getattr(session, "thread_visibility", None),
        )
    except ValueError:
        return False
    return visibility == "user"
