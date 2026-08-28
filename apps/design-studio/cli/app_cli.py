"""CLI entrypoint for native Design Studio delegation and inspection."""

from __future__ import annotations

import json
from pathlib import Path
import stat
import sys

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "backend"))
sys.path.insert(0, str(APP_ROOT / "service"))

from core.app_sdk.runtime import emit_json, read_entrypoint_payload
from core.apps.artifact_mounts import create_artifact_namespace
from core.shared.repository import discover_repository_root
from delegation_errors import DelegationError
from native_official_update import OfficialUpdateError, perform_official_update
from official_opendesign_release import OfficialReleaseError
from official_release_selection import read_release_selection
from official_update_state import read_update_state
from surface_service import SurfaceService, app_events_for_action


def main() -> None:
    payload = read_entrypoint_payload()
    if str(payload.raw.get("command_id") or "").endswith(".design-studio-update"):
        _official_update(payload)
        return
    arguments = dict(payload.arguments)
    action = str(arguments.pop("action", "") or "state")
    try:
        result = SurfaceService(payload).dispatch(action, arguments)
    except DelegationError as error:
        emit_json({
            "status_code": error.status_code,
            "ok": False,
            "error": error.code,
            "detail": error.detail,
        })
        return
    emit_json({
        "status_code": 200,
        "ok": True,
        **result,
        "app_events": app_events_for_action(action),
    })


def _official_update(payload) -> None:
    arguments = dict(payload.arguments)
    action = str(arguments.get("action") or "status")
    data_root = Path(payload.data_root)
    if action == "status":
        try:
            selection = read_release_selection(data_root)
            update = read_update_state(data_root)
        except (OfficialReleaseError, OfficialUpdateError) as error:
            emit_json({"ok": False, "error": "official_update_state_invalid", "detail": str(error)})
            return
        emit_json(
            {
                "ok": True,
                "selected_release": {
                    "version": selection.release.version,
                    "manifest_digest": selection.release.manifest_digest,
                    "selected_at": selection.selected_at,
                },
                "last_update": update,
            }
        )
        return
    if action != "apply":
        emit_json({"ok": False, "error": "official_update_action_invalid"})
        return
    try:
        descriptor = _workspace_descriptor(
            Path(payload.workspace_root),
            arguments.get("release_descriptor"),
        )
        namespace = create_artifact_namespace(
            repository_root=discover_repository_root(start_path=APP_ROOT),
            app_id="design-studio",
            artifact_id="opendesign",
        )
        result = perform_official_update(
            data_root,
            namespace,
            descriptor,
            workspace_id=str(payload.workspace_id or "default"),
            confirmed=arguments.get("confirm") is True,
        )
    except (OfficialReleaseError, OfficialUpdateError, OSError, ValueError) as error:
        emit_json({"ok": False, "error": "official_update_failed", "detail": str(error)})
        return
    emit_json({"ok": result.get("update_applied") is True, **result})


def _workspace_descriptor(workspace_root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("release_descriptor is required")
    root = workspace_root.resolve(strict=True)
    candidate = Path(value)
    path = candidate if candidate.is_absolute() else root / candidate
    metadata = path.lstat()
    resolved = path.resolve(strict=True)
    if root not in resolved.parents or stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("release_descriptor must be a regular file inside the workspace")
    if metadata.st_size > 1024 * 1024:
        raise ValueError("release_descriptor exceeds the 1 MiB safety limit")
    json.loads(path.read_text(encoding="utf-8"))
    return resolved


if __name__ == "__main__":
    main()
