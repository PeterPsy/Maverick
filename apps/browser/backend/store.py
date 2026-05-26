"""Browser app JSON storage."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from core.app_sdk.storage import read_json_state, update_json_state, write_json_state

from models import STATE_FILE, STATE_SCHEMA_VERSION


MAX_AUDIT_RECORDS = 200
MAX_SESSION_LOG_RECORDS = 200


def default_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "broker": {
            "status": "unconfigured",
            "provider": "playwright_lab",
            "detail": "Set MAVERICK_BROWSER_BROKER_URL to the local Browser broker sidecar.",
        },
        "sessions": {},
        "audit": [],
    }


def load_state(data_root: str) -> dict[str, Any]:
    state = read_json_state(data_root, STATE_FILE, default_state())
    return normalize_state(state)


def save_state(data_root: str, state: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_state(state)
    write_json_state(data_root, STATE_FILE, normalized)
    return normalized


def update_state(data_root: str, updater: Callable[[dict[str, Any]], dict[str, Any] | None]) -> dict[str, Any]:
    def normalized_updater(current: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_state(current)
        updated = updater(normalized)
        return normalize_state(updated or normalized)

    return update_json_state(data_root, STATE_FILE, normalized_updater, default_state())


def append_audit_record(data_root: str, record: dict[str, Any]) -> dict[str, Any]:
    timestamped = {"timestamp": datetime.now(tz=UTC).isoformat(), **record}

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        audit = state.get("audit")
        records = audit if isinstance(audit, list) else []
        state["audit"] = [*records, timestamped][-MAX_AUDIT_RECORDS:]
        return state

    update_state(data_root, updater)
    return timestamped


def upsert_session_record(data_root: str, session_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    record = {
        "session_id": session_id,
        "status": "active",
        "mode": "read_only",
        "url": "about:blank",
        "tabs": [],
        "console": [],
        "network": [],
        "updated_at": datetime.now(tz=UTC).isoformat(),
        **updates,
    }

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        sessions = state.get("sessions")
        session_records = sessions if isinstance(sessions, dict) else {}
        existing = session_records.get(session_id)
        if isinstance(existing, dict):
            record.update(existing)
            record.update(updates)
            record["updated_at"] = datetime.now(tz=UTC).isoformat()
        session_records[session_id] = normalize_session_record(record)
        state["sessions"] = session_records
        return state

    state = update_state(data_root, updater)
    return state["sessions"][session_id]


def remove_session_record(data_root: str, session_id: str) -> None:
    def updater(state: dict[str, Any]) -> dict[str, Any]:
        sessions = state.get("sessions")
        session_records = sessions if isinstance(sessions, dict) else {}
        session_records.pop(session_id, None)
        state["sessions"] = session_records
        return state

    update_state(data_root, updater)


def normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(default_state())
    if isinstance(state, dict):
        normalized.update(state)
    normalized["schema_version"] = STATE_SCHEMA_VERSION
    if not isinstance(normalized.get("broker"), dict):
        normalized["broker"] = default_state()["broker"]
    if not isinstance(normalized.get("sessions"), dict):
        normalized["sessions"] = {}
    normalized["sessions"] = {
        str(session_id): normalize_session_record(record)
        for session_id, record in normalized["sessions"].items()
        if isinstance(record, dict)
    }
    if not isinstance(normalized.get("audit"), list):
        normalized["audit"] = []
    normalized["audit"] = normalized["audit"][-MAX_AUDIT_RECORDS:]
    return normalized


def normalize_session_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    session_id = str(normalized.get("session_id") or "")[:120]
    normalized["session_id"] = session_id
    mode = str(normalized.get("mode") or "read_only")
    normalized["mode"] = mode if mode in {"read_only", "maverick_dev_inspector"} else "read_only"
    normalized["status"] = str(normalized.get("status") or "active")[:80]
    normalized["url"] = str(normalized.get("url") or "about:blank")[:2048]
    normalized["title"] = str(normalized.get("title") or "")[:500]
    for field in ("tabs", "console", "network"):
        records = normalized.get(field)
        normalized[field] = records[-MAX_SESSION_LOG_RECORDS:] if isinstance(records, list) else []
    return normalized
