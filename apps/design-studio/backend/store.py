"""JSON state store for Design Studio."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from core.app_sdk.storage import ensure_json_state, read_json_state, update_json_state, write_json_state


STATE_FILE = "state.json"
SCHEMA_VERSION = "1"
OPENDESIGN_VERSION = "0.10.1"
OPENDESIGN_COMMIT = "eb245799adf07e7727ad5f970485d809bad5780e"


def utc_now() -> str:
    """Return one UTC timestamp."""
    return datetime.now(tz=UTC).isoformat()


def default_state() -> dict[str, Any]:
    """Return the default persisted Design Studio state."""
    return {
        "schema_version": SCHEMA_VERSION,
        "opendesign": {
            "version": OPENDESIGN_VERSION,
            "commit": OPENDESIGN_COMMIT,
            "mode": "governed-sidecar-stub",
            "provider_mode": "maverick-proxy",
        },
        "projects": [],
        "view_state": {
            "query": "",
            "selected_project_id": "",
        },
        "route_policy": {
            "blocked": ["/api/import/folder", "/api/terminal", "/api/terminals"],
            "handled_by_core": ["/api/provider", "/api/media/config", "/api/import/storage", "/api/export/storage"],
        },
        "updated_at": utc_now(),
    }


def ensure_state(data_root: str | Path) -> dict[str, Any]:
    """Create state and sidecar working directories if needed, then return state."""
    root = Path(data_root)
    for relative in ("opendesign/db", "opendesign/projects", "opendesign/media-config", "opendesign/temp", "imports", "exports"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    ensure_json_state(data_root, STATE_FILE, default_state())
    return read_state(data_root)


def read_state(data_root: str | Path) -> dict[str, Any]:
    """Read current Design Studio state."""
    state = read_json_state(data_root, STATE_FILE, default_state())
    if state.get("schema_version") != SCHEMA_VERSION:
        state = migrate_state_payload(state)
        write_json_state(data_root, STATE_FILE, state)
    return state


def update_state(data_root: str | Path, updater: Callable[[dict[str, Any]], dict[str, Any] | None]) -> dict[str, Any]:
    """Update Design Studio state atomically."""
    def wrapped(payload: dict[str, Any]) -> dict[str, Any]:
        state = migrate_state_payload(payload)
        next_state = updater(state) or state
        next_state["updated_at"] = utc_now()
        return next_state

    return update_json_state(data_root, STATE_FILE, wrapped, default_state())


def migrate_state_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Migrate a state payload to the current schema."""
    state = default_state()
    state.update({key: value for key, value in payload.items() if key in state})
    state["schema_version"] = SCHEMA_VERSION
    if not isinstance(state.get("projects"), list):
        state["projects"] = []
    if not isinstance(state.get("view_state"), dict):
        state["view_state"] = default_state()["view_state"]
    return state
