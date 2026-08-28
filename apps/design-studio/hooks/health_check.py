"""Health check for the native package host and its optional bridges."""

from __future__ import annotations

import json
from pathlib import Path
import stat
import sys
from typing import Any

from core.app_sdk.runtime import emit_json, read_entrypoint_payload
from core.apps.artifact_mounts import create_artifact_namespace
from core.shared.repository import discover_repository_root


APP_ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = APP_ROOT / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from official_opendesign_release import (  # noqa: E402
    OfficialReleaseError,
    load_official_release,
    verify_official_installation,
)
from official_release_selection import ensure_release_selection  # noqa: E402


def main() -> None:
    payload = read_entrypoint_payload()
    release = ensure_release_selection(
        Path(payload.data_root),
        load_official_release(),
    ).release
    try:
        data_dir = _real_directory(Path(payload.data_root) / "opendesign-native")
        namespace = create_artifact_namespace(
            repository_root=discover_repository_root(start_path=APP_ROOT),
            app_id="design-studio",
            artifact_id="opendesign",
        )
        installation = verify_official_installation(
            namespace / "official" / release.digest_key,
            expected_release=release,
            verify_contents=False,
        )
    except (OSError, OfficialReleaseError, RuntimeError) as error:
        _emit_health(
            {
                "ok": False,
                "operational": False,
                "mode": "official-native",
                "error": "official_release_unavailable",
                "detail": str(error),
            }
        )
        return

    install_probe = payload.raw.get("hook_name") == "install"
    manager = (
        {"state": "not_required", "phase": "install_artifact_gate"}
        if install_probe
        else _live_sidecar_status(
            workspace_id=str(payload.workspace_id or "default"),
            app_id=str(payload.app_id or "design-studio"),
        )
    )
    native_ready = install_probe or manager.get("state") == "ready"
    host = _read_json(Path(payload.data_root) / "native-host-status.json")
    bridges = _read_json(Path(payload.data_root) / "bridge-capabilities.json")
    _emit_health(
        {
            "ok": native_ready,
            "operational": native_ready,
            "mode": "official-native",
            "official_release": {
                "version": release.version,
                "manifest_digest": release.manifest_digest,
                "rootfs_snapshot_sha256": installation.rootfs_snapshot_sha256,
                "customizations": [],
            },
            "data_directory": data_dir.name,
            "native": {
                "available": native_ready,
                "sidecar": manager,
                "host": host,
            },
            "bridges": {
                "model_access": _bridge_status(bridges, "model_access"),
                "delegation": _bridge_status(bridges, "delegation"),
            },
        }
    )


def _bridge_status(payload: dict[str, Any], name: str) -> dict[str, Any]:
    candidate = payload.get(name)
    if isinstance(candidate, dict) and candidate.get("state") in {"ready", "degraded", "disabled"}:
        return candidate
    return {"state": "disabled", "reason": "not_configured"}


def _real_directory(path: Path) -> Path:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise OfficialReleaseError("native OpenDesign data directory is unsafe")
    return path.resolve(strict=True)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _live_sidecar_status(*, workspace_id: str, app_id: str) -> dict[str, Any]:
    try:
        from core.api.sidecar_control import request_sidecar_control

        response = request_sidecar_control(
            discover_repository_root(start_path=APP_ROOT),
            operation="status",
            workspace_id=workspace_id,
            app_id=app_id,
            timeout_seconds=2,
        )
        services = response.get("services") if isinstance(response, dict) else None
        matches = [
            item
            for item in services or []
            if isinstance(item, dict) and item.get("sidecar_id") == "opendesign"
        ]
        if len(matches) != 1:
            raise ValueError("native OpenDesign sidecar status is missing")
        return matches[0]
    except Exception as error:
        return {
            "state": "failed",
            "phase": getattr(error, "phase", "sidecar_manager_status"),
            "last_failure": {
                "code": getattr(error, "code", "daemon_ready_timeout"),
                "phase": getattr(error, "phase", "sidecar_manager_status"),
            },
        }


def _emit_health(payload: dict[str, Any]) -> None:
    emit_json(payload)
    if payload.get("ok") is not True or payload.get("operational") is not True:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
