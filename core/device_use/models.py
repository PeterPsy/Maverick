"""Device-use domain records kept independent from HTTP and WebSocket details."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal


DeviceUseActivationStatus = Literal[
    "awaiting_device",
    "ready",
    "bound",
    "offline",
    "stopped",
    "expired",
]
DeviceUseEffectClass = Literal["read", "control"]
DeviceUseInvocationStatus = Literal[
    "dispatched",
    "accepted",
    "result_received",
    "image_received",
    "completed",
    "failed",
    "execution_unknown",
]


@dataclass(frozen=True)
class DeviceUseSessionBinding:
    """Immutable authority pinned to one Maverick runtime session."""

    activation_id: str
    workspace_id: str
    owner_user_id: str
    protocol_version: str
    executor_contract: str
    tool_contract_digest: str
    initial_app: str
    approved_apps: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True)
class DeviceUseResult:
    """Validated native result, with image bytes kept protocol-private."""

    invocation_id: str
    call_id: str
    result: dict[str, object]
    image_jpeg: bytes | None
    image_sha256: str | None
    native_duration_ms: float | None


@dataclass(frozen=True)
class DeviceUseInvocationJournalRecord:
    """Redaction-safe lifecycle evidence for one physical invocation."""

    invocation_id: str
    activation_id: str
    runtime_session_id: str
    turn_id: str
    call_id: str
    tool_name: str
    action: str
    arguments_digest: str
    effect_class: DeviceUseEffectClass
    status: DeviceUseInvocationStatus
    dispatched_at: datetime
    updated_at: datetime
    accepted_at: datetime | None = None
    result_received_at: datetime | None = None
    completed_at: datetime | None = None
    native_duration_ms: float | None = None
    image_bytes: int = 0
    failure_reason_code: str | None = None


def device_use_binding_from_document(value: object) -> DeviceUseSessionBinding | None:
    """Hydrate a stored binding while rejecting malformed authority."""
    if value is None:
        return None
    if isinstance(value, DeviceUseSessionBinding):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("Device-use session binding must be an object.")
    approved_apps = value.get("approved_apps")
    if not isinstance(approved_apps, (list, tuple)):
        raise ValueError("Device-use approved apps must be a list.")
    created_at = value.get("created_at")
    if not isinstance(created_at, datetime):
        raise ValueError("Device-use binding timestamp is invalid.")
    binding = DeviceUseSessionBinding(
        activation_id=_required_text(value.get("activation_id"), "activation_id"),
        workspace_id=_required_text(value.get("workspace_id"), "workspace_id"),
        owner_user_id=_required_text(value.get("owner_user_id"), "owner_user_id"),
        protocol_version=_required_text(value.get("protocol_version"), "protocol_version"),
        executor_contract=_required_text(value.get("executor_contract"), "executor_contract"),
        tool_contract_digest=_required_text(value.get("tool_contract_digest"), "tool_contract_digest"),
        initial_app=_required_text(value.get("initial_app"), "initial_app"),
        approved_apps=tuple(_required_text(item, "approved_app") for item in approved_apps),
        created_at=created_at,
    )
    if binding.initial_app not in binding.approved_apps:
        raise ValueError("Device-use initial app must be approved.")
    return binding


def _required_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 256:
        raise ValueError(f"Device-use `{field_name}` is invalid.")
    return text
