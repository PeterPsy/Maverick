"""Adapter-only JSON state for Design Studio.

OpenDesign owns projects, conversations, runs, and project files.  This store is
deliberately limited to Maverick view state plus import/export lifecycle
metadata.  The pre-OpenDesign ``state.json`` is a sealed migration input and is
never opened for writing here.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Callable

from core.app_sdk.storage import ensure_json_state, read_json_state, update_json_state, write_json_state


STATE_FILE = "adapter-state.json"
SCHEMA_VERSION = "3"
MAX_JOB_RECORDS = 1000
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
        "view_state": {
            "query": "",
            "selected_project_id": "",
        },
        "opendesign_app_config": {
            "onboardingCompleted": True,
            "agentId": "maverick",
            "skillId": None,
            "designSystemId": None,
            "disabledSkills": [],
            "disabledDesignSystems": [],
            "telemetry": {
                "metrics": False,
                "content": False,
                "artifactManifest": False,
            },
            "allowSilentUpdates": False,
        },
        "import_jobs": [],
        "export_jobs": [],
        "lifecycle": {
            "legacy_project_map": "opendesign/legacy-project-map.json",
            "legacy_state": "state.json",
            "legacy_state_writable": False,
        },
        "route_policy": {
            "pass_through": [
                "/index.html",
                "/_next",
                "/assets",
                "/favicon.ico",
                "/api/health",
                "/api/maverick-ready",
                "/api/ready",
                "/api/version",
                "/api/media/models",
            ],
            "blocked": [
                "/api/import/folder",
                "/api/dialog/open-folder",
                "/api/system/open-external",
                "/api/chat",
                "/api/agents",
                "/api/mcp",
                "/api/plugins/upload-folder",
                "/api/orbit",
                "/api/research",
                "/api/deploy",
                "/api/live-artifacts",
                "/api/tools/live-artifacts",
            ],
            "handled_by_core": [
                "/api/provider",
                "/api/media/config",
                "/api/app-config",
                "/api/attribution/claim",
                "/api/import/storage",
                "/api/export/storage",
                "/api/runs",
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
        "opendesign/web-activations",
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
    if not isinstance(state.get("view_state"), dict):
        state["view_state"] = default_state()["view_state"]
    if not isinstance(state.get("opendesign_app_config"), dict):
        state["opendesign_app_config"] = defaults["opendesign_app_config"]
    else:
        state["opendesign_app_config"] = {
            **defaults["opendesign_app_config"],
            **{
                key: value
                for key, value in state["opendesign_app_config"].items()
                if key in defaults["opendesign_app_config"]
            },
        }
    for key in ("import_jobs", "export_jobs"):
        if not isinstance(state.get(key), list):
            state[key] = []
        else:
            state[key] = [item for item in state[key] if isinstance(item, dict)][-MAX_JOB_RECORDS:]
    state["lifecycle"] = defaults["lifecycle"]
    return state
