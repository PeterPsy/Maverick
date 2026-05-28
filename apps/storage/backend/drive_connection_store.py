"""Google Drive connection state for Storage."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.app_sdk.storage import read_json_state, update_json_state


STATE_FILE = "drive_connections.json"
SCHEMA_VERSION = "1"


def now_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "connections": [],
        "oauth_flows": [],
        "audit_log": [],
    }


def read_state(data_root: Path) -> dict[str, Any]:
    return normalize_state(read_json_state(data_root, STATE_FILE, empty_state()))


def update_state(data_root: Path, updater) -> dict[str, Any]:
    def wrapped(payload: dict[str, Any]) -> dict[str, Any]:
        return normalize_state(updater(normalize_state(payload)))

    return update_json_state(data_root, STATE_FILE, wrapped, empty_state())


def list_connections(data_root: Path) -> list[dict[str, Any]]:
    return [public_connection(item) for item in read_state(data_root).get("connections", [])]


def get_connection(data_root: Path, connection_id: str) -> dict[str, Any]:
    for item in read_state(data_root).get("connections", []):
        if str(item.get("id") or "") == connection_id:
            return normalize_connection(item)
    raise ValueError(f"Drive connection `{connection_id}` was not found.")


def replace_connection(data_root: Path, connection: dict[str, Any]) -> dict[str, Any]:
    connection = normalize_connection(connection)

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        state["connections"] = [
            item for item in state["connections"] if str(item.get("id") or "") != connection["id"]
        ]
        state["connections"].append(connection)
        return state

    update_state(data_root, updater)
    return connection


def sync_state_for_connection(data_root: Path, connection_id: str) -> dict[str, Any]:
    return normalize_sync_state(get_connection(data_root, connection_id).get("sync_state"))


def update_connection_sync_state(data_root: Path, connection_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        next_connections: list[dict[str, Any]] = []
        found = False
        for item in state.get("connections", []):
            connection = normalize_connection(item)
            if connection["id"] != connection_id:
                next_connections.append(connection)
                continue
            found = True
            sync_state = normalize_sync_state({**connection.get("sync_state", {}), **updates})
            connection["sync_state"] = sync_state
            connection["updated_at"] = now_timestamp()
            captured.update(sync_state)
            next_connections.append(connection)
        if not found:
            raise ValueError(f"Drive connection `{connection_id}` was not found.")
        state["connections"] = next_connections
        return state

    update_state(data_root, updater)
    return captured


def append_audit(data_root: Path, action: str, target_type: str, target_id: str, detail: dict[str, Any] | None = None) -> None:
    event = {
        "id": f"audit_{uuid4().hex[:16]}",
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "detail": _redaction_safe_detail(detail or {}),
        "created_at": now_timestamp(),
    }

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        state["audit_log"] = [*state.get("audit_log", []), event][-500:]
        return state

    update_state(data_root, updater)


def public_connection(connection: dict[str, Any]) -> dict[str, Any]:
    item = normalize_connection(connection)
    external_refs = dict(item.get("external_refs") or {})
    for key in ("oauth_state_hash", "oauth_state_expires_at", "oauth_redirect_uri"):
        external_refs.pop(key, None)
    item["external_refs"] = external_refs
    return item


def normalize_state(payload: dict[str, Any]) -> dict[str, Any]:
    connections = payload.get("connections") if isinstance(payload.get("connections"), list) else []
    oauth_flows = payload.get("oauth_flows") if isinstance(payload.get("oauth_flows"), list) else []
    audit_log = payload.get("audit_log") if isinstance(payload.get("audit_log"), list) else []
    return {
        "schema_version": SCHEMA_VERSION,
        "connections": [normalize_connection(item) for item in connections if isinstance(item, dict)],
        "oauth_flows": [dict(item) for item in oauth_flows if isinstance(item, dict)],
        "audit_log": [_redaction_safe_detail(item) for item in audit_log if isinstance(item, dict)],
    }


def normalize_connection(payload: dict[str, Any]) -> dict[str, Any]:
    connection_id = str(payload.get("id") or payload.get("connection_id") or "").strip()
    if not connection_id:
        raise ValueError("Drive connection id is required.")
    status = str(payload.get("status") or "connected").strip().lower()
    if status not in {"pending", "connected", "disconnected", "error"}:
        status = "error"
    scopes = payload.get("scopes") if isinstance(payload.get("scopes"), list) else []
    external_refs = payload.get("external_refs") if isinstance(payload.get("external_refs"), dict) else {}
    credential = payload.get("credential") if isinstance(payload.get("credential"), dict) else {}
    return {
        "id": connection_id,
        "resource_type": "drive_connection",
        "provider": "google_drive",
        "account_email": str(payload.get("account_email") or payload.get("email_address") or "").strip(),
        "display_name": str(payload.get("display_name") or payload.get("account_email") or "").strip(),
        "status": status,
        "access_mode": str(payload.get("access_mode") or "full_rw").strip(),
        "scopes": [str(scope).strip() for scope in scopes if str(scope or "").strip()],
        "created_at": str(payload.get("created_at") or ""),
        "updated_at": str(payload.get("updated_at") or ""),
        "connected_at": str(payload.get("connected_at") or ""),
        "disconnected_at": str(payload.get("disconnected_at") or ""),
        "credential": {
            "secret_ref": str(credential.get("secret_ref") or payload.get("secret_ref") or ""),
            "grant_id": str(credential.get("grant_id") or payload.get("grant_id") or ""),
            "status": str(credential.get("status") or payload.get("credential_status") or ""),
            "oauth_metadata": _redaction_safe_detail(credential.get("oauth_metadata") if isinstance(credential.get("oauth_metadata"), dict) else {}),
        },
        "external_refs": _redaction_safe_detail(external_refs),
        "sync_state": normalize_sync_state(payload.get("sync_state")),
    }


def normalize_sync_state(payload: object) -> dict[str, Any]:
    value = payload if isinstance(payload, dict) else {}
    status = str(value.get("status") or "not_started").strip().lower()
    if status not in {"not_started", "healthy", "syncing", "error"}:
        status = "error"
    return {
        "start_page_token": str(value.get("start_page_token") or ""),
        "last_processed_page_token": str(value.get("last_processed_page_token") or ""),
        "last_sync_at": str(value.get("last_sync_at") or ""),
        "status": status,
        "error": str(value.get("error") or ""),
    }


def _redaction_safe_detail(value: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, raw in value.items():
        normalized_key = str(key)
        lowered = normalized_key.lower()
        if any(marker in lowered for marker in ("token", "secret", "authorization", "raw_value")):
            if lowered in {"token_type", "expires_in", "scope", "scopes"}:
                safe[normalized_key] = raw
            continue
        if isinstance(raw, dict):
            safe[normalized_key] = _redaction_safe_detail(raw)
        elif isinstance(raw, list):
            safe[normalized_key] = [
                _redaction_safe_detail(item) if isinstance(item, dict) else item
                for item in raw
            ]
        elif isinstance(raw, (str, int, float, bool)) or raw is None:
            safe[normalized_key] = raw
        else:
            safe[normalized_key] = str(raw)
    return safe
