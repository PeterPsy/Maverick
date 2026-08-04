"""JSON state store for Design Studio."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Callable

from core.app_sdk.storage import ensure_json_state, read_json_state, update_json_state, write_json_state


STATE_FILE = "state.json"
SCHEMA_VERSION = "1"
_OPENDESIGN_MANIFEST_PATH = Path(__file__).resolve().parents[1] / "service" / "opendesign_bundle.json"


def _opendesign_identity() -> tuple[str, str]:
    payload = json.loads(_OPENDESIGN_MANIFEST_PATH.read_text(encoding="utf-8"))
    upstream = payload["upstream"]
    return str(upstream["release_version"]), str(upstream["commit"])


OPENDESIGN_VERSION, OPENDESIGN_COMMIT = _opendesign_identity()
OPENDESIGN_MODE = "curated-open-design-daemon"


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
            "mode": OPENDESIGN_MODE,
            "provider_mode": "maverick-proxy",
        },
        "projects": [],
        "view_state": {
            "query": "",
            "selected_project_id": "",
        },
        "route_policy": {
            "pass_through": [
                "/index.html",
                "/_next",
                "/assets",
                "/favicon.ico",
                "/api/health",
                "/api/ready",
                "/api/version",
                "/api/media/models",
            ],
            "blocked": [
                "/api/import/folder",
                "/api/dialog/open-folder",
                "/api/system/open-external",
                "/api/runs",
                "/api/chat",
                "/api/agents",
                "/api/mcp",
                "/api/plugins/upload-folder",
                "/api/app-config",
                "/api/orbit",
                "/api/research",
                "/api/deploy",
                "/api/live-artifacts",
                "/api/tools/live-artifacts",
            ],
            "handled_by_core": [
                "/api/provider",
                "/api/media/config",
                "/api/projects",
                "/api/import/storage",
                "/api/export/storage",
            ],
        },
        "updated_at": utc_now(),
    }


def _ensure_layout(data_root: str | Path) -> None:
    root = Path(data_root)
    for relative in (
        "opendesign/instances",
        "opendesign/backups",
        "opendesign/migrations",
        "imports",
        "exports",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)


def ensure_state(data_root: str | Path) -> dict[str, Any]:
    """Create state and sidecar working directories if needed, then return state."""
    _ensure_layout(data_root)
    ensure_json_state(data_root, STATE_FILE, default_state())
    return read_state(data_root)


def read_state(data_root: str | Path) -> dict[str, Any]:
    """Read current Design Studio state."""
    state = read_json_state(data_root, STATE_FILE, default_state())
    migrated = migrate_state_payload(state)
    if migrated != state:
        write_json_state(data_root, STATE_FILE, migrated)
    return migrated


def update_state(data_root: str | Path, updater: Callable[[dict[str, Any]], dict[str, Any] | None]) -> dict[str, Any]:
    """Update Design Studio state atomically."""
    _ensure_layout(data_root)

    def wrapped(payload: dict[str, Any]) -> dict[str, Any]:
        state = migrate_state_payload(payload)
        next_state = updater(state) or state
        next_state["updated_at"] = utc_now()
        return next_state

    return update_json_state(data_root, STATE_FILE, wrapped, default_state())


def migrate_state_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Migrate a state payload to the current schema."""
    defaults = default_state()
    state = defaults.copy()
    state.update({key: value for key, value in payload.items() if key in state})
    state["schema_version"] = SCHEMA_VERSION
    state["opendesign"] = defaults["opendesign"]
    state["route_policy"] = defaults["route_policy"]
    if not isinstance(state.get("projects"), list):
        state["projects"] = []
    if not isinstance(state.get("view_state"), dict):
        state["view_state"] = default_state()["view_state"]
    return state
