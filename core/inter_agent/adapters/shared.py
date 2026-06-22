"""Shared helpers for Microsoft Agent Framework adapter projections."""

from __future__ import annotations

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


MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK = "MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK"
_ENABLED_VALUE = "1"
_ORCHESTRATIONS_MODULE = "agent_framework_orchestrations"
_CORE_MODULE = "agent_framework"


@dataclass(frozen=True)
class MafModules:
    """Optional MAF modules imported only after the feature flag is enabled."""

    orchestrations: ModuleType
    core: ModuleType


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

def _terminal_status_for_payload_kind(payload_kind: str) -> str:
    if payload_kind == "terminal_cancelled":
        return "cancelled"
    if payload_kind in {"terminal_failure", "budget_exhausted"}:
        return "failed"
    return "completed"

def _workflow_source_event_id(event: object, adapter_event_type: str, source_index: int) -> str:
    explicit = _clean_optional(_value(event, "source_event_id", "event_id", "id", "request_id"))
    if explicit:
        return explicit
    executor_id = _clean_optional(_value(event, "executor_id")) or "workflow"
    iteration = _clean_optional(_value(event, "iteration")) or "0"
    return f"maf-workflow:{source_index}:{adapter_event_type}:{executor_id}:{iteration}"

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
    if text.isupper():
        text = text.lower()
    else:
        text = re.sub(r"(?<!^)(?=[A-Z])", "_", text)
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text)
    return text.strip("_").lower()

def _clean_optional(value: object) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None
