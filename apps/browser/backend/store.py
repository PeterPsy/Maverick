"""Browser app JSON storage."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from core.app_sdk.storage import read_json_state, update_json_state, write_json_state

from models import STATE_FILE, STATE_SCHEMA_VERSION


MAX_AUDIT_RECORDS = 200


def default_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "broker": {
            "status": "unconfigured",
            "provider": "playwright_lab",
            "detail": "Playwright broker is not connected in the Passo 3 app scaffold.",
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


def normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(default_state())
    if isinstance(state, dict):
        normalized.update(state)
    normalized["schema_version"] = STATE_SCHEMA_VERSION
    if not isinstance(normalized.get("broker"), dict):
        normalized["broker"] = default_state()["broker"]
    if not isinstance(normalized.get("sessions"), dict):
        normalized["sessions"] = {}
    if not isinstance(normalized.get("audit"), list):
        normalized["audit"] = []
    normalized["audit"] = normalized["audit"][-MAX_AUDIT_RECORDS:]
    return normalized
