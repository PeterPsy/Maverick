"""Microsoft Agent Framework adapter skeleton.

This module intentionally stops at F6 adapter scaffolding. It does not execute
MAF orchestrations, select providers, receive secrets, or own runtime sessions.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
import hashlib
import importlib
import json
import os
import re
from types import ModuleType
from typing import Any

from core.inter_agent.adapters.base import (
    AdapterEventMappingContext,
    InterAgentAdapterUnavailableError,
)
from core.inter_agent.events import (
    InterAgentEventRecord,
    InterAgentEventType,
    InterAgentVisibilityPlane,
    validate_event_record,
    validate_visibility_plane,
)


MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK = "MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK"
_ENABLED_VALUE = "1"
_ORCHESTRATIONS_MODULE = "agent_framework_orchestrations"
_CORE_MODULE = "agent_framework"

_HANDOFF_EVENT_TYPES: dict[str, InterAgentEventType] = {
    "handoff_sent": "inter_agent.handoff.requested",
    "handoff_requested": "inter_agent.handoff.requested",
    "handoff_request": "inter_agent.handoff.requested",
    "handoff_accepted": "inter_agent.handoff.accepted",
    "handoff_accept": "inter_agent.handoff.accepted",
    "handoff_completed": "inter_agent.handoff.completed",
    "handoff_complete": "inter_agent.handoff.completed",
}


@dataclass(frozen=True)
class MafModules:
    """Optional MAF modules imported only after the feature flag is enabled."""

    orchestrations: ModuleType
    core: ModuleType


class MafAdapter:
    """Feature-flagged Microsoft Agent Framework adapter skeleton."""

    adapter_id = "maf"

    def is_enabled(self) -> bool:
        """Return whether the experimental MAF adapter flag is enabled."""
        return os.environ.get(MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK) == _ENABLED_VALUE

    def is_available(self) -> bool:
        """Return whether the flag is enabled and the optional MAF packages import."""
        try:
            self.require_available()
        except InterAgentAdapterUnavailableError:
            return False
        return True

    def require_available(self) -> None:
        """Raise when F6 MAF usage is disabled or optional packages are missing."""
        load_maf_modules()

    def map_events(
        self,
        context: AdapterEventMappingContext,
        events: Iterable[object],
    ) -> list[InterAgentEventRecord]:
        """Project controlled MAF events into Maverick event records."""
        self.require_available()
        return map_maf_events_to_inter_agent_records(context, events)


def load_maf_modules() -> MafModules:
    """Lazy import the selected MAF packages behind the explicit feature flag."""
    if os.environ.get(MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK) != _ENABLED_VALUE:
        raise InterAgentAdapterUnavailableError(
            f"Microsoft Agent Framework adapter requires {MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK}=1."
        )
    try:
        orchestrations = importlib.import_module(_ORCHESTRATIONS_MODULE)
        core = importlib.import_module(_CORE_MODULE)
    except ModuleNotFoundError as error:
        missing = error.name or str(error)
        raise InterAgentAdapterUnavailableError(
            f"Microsoft Agent Framework optional dependency is unavailable: {missing}."
        ) from error
    return MafModules(orchestrations=orchestrations, core=core)


def map_maf_events_to_inter_agent_records(
    context: AdapterEventMappingContext,
    events: Iterable[object],
) -> list[InterAgentEventRecord]:
    """Map controlled MAF handoff observations to safe Maverick event records."""
    visibility_plane = validate_visibility_plane(context.visibility_plane)
    records: list[InterAgentEventRecord] = []
    pending_handoffs: dict[str, str | None] = {}
    for source_index, event in enumerate(events, start=1):
        adapter_event_type = _adapter_event_type(event)
        event_type = _HANDOFF_EVENT_TYPES.get(adapter_event_type)
        if event_type is None:
            derived = _derived_handoff_event(event, adapter_event_type, pending_handoffs, source_index)
            if derived is None:
                continue
            event, event_type, adapter_event_type = derived
        source_participant_id = _clean_optional(
            _value(event, "source_participant_id", "source", "from_agent", "from_participant")
        )
        target_participant_id = _clean_optional(
            _value(event, "target_participant_id", "target", "to_agent", "to_participant")
        )
        if event_type == "inter_agent.handoff.requested" and target_participant_id:
            pending_handoffs[target_participant_id] = source_participant_id
        records.append(
            _handoff_record(
                context,
                event,
                adapter_event_type=adapter_event_type,
                event_type=event_type,
                visibility_plane=visibility_plane,
                mapped_index=len(records) + 1,
            )
        )
    return records


def _derived_handoff_event(
    event: object,
    adapter_event_type: str,
    pending_handoffs: dict[str, str | None],
    source_index: int,
) -> tuple[dict[str, Any], InterAgentEventType, str] | None:
    if adapter_event_type == "executor_invoked":
        target_participant_id = _clean_optional(_value(event, "executor_id", "target_participant_id", "target"))
        if not target_participant_id or target_participant_id not in pending_handoffs:
            return None
        if _value(event, "should_respond") is not True:
            return None
        return (
            {
                "source_event_id": _workflow_source_event_id(event, adapter_event_type, source_index),
                "source_participant_id": pending_handoffs[target_participant_id],
                "target_participant_id": target_participant_id,
                "summary": "MAF invoked the handoff target participant.",
                "correlation_id": _handoff_correlation_id(
                    pending_handoffs[target_participant_id],
                    target_participant_id,
                ),
            },
            "inter_agent.handoff.accepted",
            adapter_event_type,
        )
    if adapter_event_type == "output":
        target_participant_id = _clean_optional(_value(event, "executor_id", "target_participant_id", "target"))
        if not target_participant_id or target_participant_id not in pending_handoffs:
            return None
        return (
            {
                "source_event_id": _workflow_source_event_id(event, adapter_event_type, source_index),
                "source_participant_id": pending_handoffs[target_participant_id],
                "target_participant_id": target_participant_id,
                "summary": _safe_output_summary(event)
                or "MAF handoff target participant produced output.",
                "correlation_id": _handoff_correlation_id(
                    pending_handoffs[target_participant_id],
                    target_participant_id,
                ),
            },
            "inter_agent.handoff.completed",
            adapter_event_type,
        )
    return None


def _handoff_record(
    context: AdapterEventMappingContext,
    event: object,
    *,
    adapter_event_type: str,
    event_type: InterAgentEventType,
    visibility_plane: InterAgentVisibilityPlane,
    mapped_index: int,
) -> InterAgentEventRecord:
    run = context.run
    source_participant_id = _clean_optional(
        _value(event, "source_participant_id", "source", "from_agent", "from_participant")
    )
    target_participant_id = _clean_optional(
        _value(event, "target_participant_id", "target", "to_agent", "to_participant")
    )
    source_event_id = _clean_optional(_value(event, "source_event_id", "event_id", "id"))
    participant_id = source_participant_id
    if event_type in {"inter_agent.handoff.accepted", "inter_agent.handoff.completed"}:
        participant_id = target_participant_id or source_participant_id
    payload = _safe_handoff_payload(
        event,
        adapter_event_type=adapter_event_type,
        source_event_id=source_event_id,
        source_participant_id=source_participant_id,
        target_participant_id=target_participant_id,
    )
    identity_token = _adapter_event_identity_token(
        event,
        adapter_event_type=adapter_event_type,
        source_event_id=source_event_id,
        payload=payload,
    )
    correlation_id = (
        _clean_optional(_value(event, "correlation_id", "workflow_id", "run_id"))
        or source_event_id
        or f"{run.run_id}:maf:{adapter_event_type}:{identity_token}"
    )
    idempotency_key = (
        _clean_optional(_value(event, "idempotency_key"))
        or f"{run.run_id}:maf:{adapter_event_type}:{source_event_id or identity_token}"
    )
    record = InterAgentEventRecord(
        event_id=context.event_id_for(f"{adapter_event_type}-{identity_token}"),
        workspace_id=run.workspace_id,
        run_id=run.run_id,
        thread_id=run.thread_id,
        root_runtime_session_id=run.root_runtime_session_id,
        participant_id=participant_id,
        runtime_session_id=None,
        runtime_turn_id=None,
        runtime_event_id=None,
        event_type=event_type,
        visibility_plane=visibility_plane,
        sequence=context.sequence_start + mapped_index,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        payload=payload,
        created_at=_created_at(context, event),
    )
    return validate_event_record(record)


def _safe_handoff_payload(
    event: object,
    *,
    adapter_event_type: str,
    source_event_id: str | None,
    source_participant_id: str | None,
    target_participant_id: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "adapter": "maf",
        "adapter_event_type": adapter_event_type,
    }
    if source_event_id:
        payload["source_event_id"] = source_event_id
    if source_participant_id:
        payload["source_participant_id"] = source_participant_id
    if target_participant_id:
        payload["target_participant_id"] = target_participant_id
    summary = _clean_optional(_value(event, "summary", "message", "content", "reason", "description"))
    if summary:
        payload["summary"] = summary
    task_id = _clean_optional(_value(event, "task_id", "conversation_id"))
    if task_id:
        payload["task_id"] = task_id
    return payload


def _adapter_event_identity_token(
    event: object,
    *,
    adapter_event_type: str,
    source_event_id: str | None,
    payload: dict[str, Any],
) -> str:
    explicit_idempotency_key = _clean_optional(_value(event, "idempotency_key"))
    if explicit_idempotency_key:
        identity_payload: dict[str, Any] = {"idempotency_key": explicit_idempotency_key}
    elif source_event_id:
        identity_payload = {"source_event_id": source_event_id}
    else:
        identity_payload = {
            "correlation_id": _clean_optional(_value(event, "correlation_id", "workflow_id", "run_id")),
            "payload": payload,
        }
    encoded = json.dumps(
        {"adapter_event_type": adapter_event_type, **identity_payload},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _adapter_event_type(event: object) -> str:
    explicit = _clean_optional(_value(event, "event_type", "type", "kind", "name", "event_name"))
    if explicit:
        return _normalize_event_type(explicit)
    return _normalize_event_type(type(event).__name__)


def _created_at(context: AdapterEventMappingContext, event: object) -> datetime | None:
    value = _value(event, "created_at", "timestamp")
    if isinstance(value, datetime):
        return value
    return context.created_at


def _workflow_source_event_id(event: object, adapter_event_type: str, source_index: int) -> str:
    explicit = _clean_optional(_value(event, "source_event_id", "event_id", "id", "request_id"))
    if explicit:
        return explicit
    executor_id = _clean_optional(_value(event, "executor_id")) or "workflow"
    iteration = _clean_optional(_value(event, "iteration")) or "0"
    return f"maf-workflow:{source_index}:{adapter_event_type}:{executor_id}:{iteration}"


def _handoff_correlation_id(
    source_participant_id: str | None,
    target_participant_id: str,
) -> str:
    source = source_participant_id or "unknown"
    return f"maf-handoff:{source}:{target_participant_id}"


def _safe_output_summary(event: object) -> str | None:
    data = _value(event, "data")
    text = _clean_optional(_value(data, "text")) if data is not None else None
    if text:
        return text[:500]
    return _clean_optional(_value(event, "summary", "message", "content", "description"))


def _value(event: object, *names: str) -> Any:
    if isinstance(event, dict):
        for name in names:
            if name in event:
                return event[name]
        data = event.get("data")
        if data is not None:
            return _value(data, *names)
        return None
    missing = object()
    for name in names:
        try:
            value = getattr(event, name, missing)
        except Exception:
            continue
        if value is not missing:
            return value
    data = getattr(event, "data", None)
    if data is not None:
        return _value(data, *names)
    return None


def _normalize_event_type(value: object) -> str:
    text = str(value or "").strip()
    text = text.split(".")[-1]
    text = re.sub(r"(?<!^)(?=[A-Z])", "_", text)
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text)
    return text.strip("_").lower()


def _clean_optional(value: object) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None
