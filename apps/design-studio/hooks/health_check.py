"""Health-check hook for Design Studio."""

from __future__ import annotations

from pathlib import Path
import json
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from core.app_sdk.runtime import emit_json, read_entrypoint_payload
from store import ensure_state


def main() -> None:
    payload = read_entrypoint_payload()
    state = ensure_state(payload.data_root)
    if not _declares_protected_store():
        _emit_health({"ok": True, "operational": True, "schema_version": state.get("schema_version")})
        return
    service_root = Path(__file__).resolve().parents[1] / "service"
    sys.path.insert(0, str(service_root))
    try:
        from opendesign_artifact_operations import run_artifact_operation

        artifact = run_artifact_operation("status", data_root=Path(payload.data_root))
    except Exception as error:
        _emit_health(
            {
                "ok": False,
                "operational": False,
                "schema_version": state.get("schema_version"),
                "health": _health_layers(artifact_ready=False),
                "error": getattr(error, "code", "artifact_missing"),
                "phase": getattr(error, "phase", "artifact_status"),
            }
        )
        return
    if payload.raw.get("hook_name") == "install":
        artifact_ready = artifact.get("operational") is True
        _emit_health(
            {
                "ok": artifact_ready,
                "schema_version": state.get("schema_version"),
                "activation_gate": "artifact_ready",
                "health": _health_layers(artifact_ready=artifact_ready),
            }
        )
        return
    launcher = _launcher_status(Path(payload.data_root) / "opendesign" / "launcher-status.json")
    launcher_health = launcher.get("health") if isinstance(launcher.get("health"), dict) else {}
    last_failure = launcher.get("last_failure") if isinstance(launcher.get("last_failure"), dict) else None
    manager = _live_sidecar_status(
        workspace_id=str(payload.workspace_id or "default"),
        app_id=str(payload.app_id or "design-studio"),
    )
    if last_failure is None and manager.get("state") != "ready":
        declared = manager.get("last_failure")
        last_failure = (
            dict(declared)
            if isinstance(declared, dict)
            else {
                "code": "daemon_ready_timeout",
                "phase": str(manager.get("phase") or "sidecar_manager_status"),
                "auto_repairable": False,
            }
        )
    repair = _repair_status(Path(payload.data_root) / "opendesign" / "repair-state.json")
    repair_state = str(repair.get("state") or "idle")
    if repair_state == "failed":
        last_failure = {
            "code": str(repair.get("error_code") or "artifact_repair_failed"),
            "phase": str(repair.get("phase") or "artifact_repair"),
            "observed_at_epoch_ms": repair.get("observed_at_epoch_ms"),
            "auto_repairable": False,
        }
    artifact_ready = artifact.get("operational") is True
    health = _health_layers(
        artifact_ready=artifact_ready,
        launcher_health=launcher_health,
        manager_status=manager,
        repair_state=repair_state,
    )
    browser_ready = (
        artifact_ready
        and repair_state == "idle"
        and health["browser_ready"] is True
        and last_failure is None
    )
    _emit_health(
        {
            "ok": browser_ready,
            "operational": browser_ready,
            "schema_version": state.get("schema_version"),
            "health": health,
            "repair_state": repair_state,
            "last_failure": last_failure,
        }
    )


def _launcher_status(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema_version") != "3":
        return {}
    updated = payload.get("updated_at_epoch_ms")
    observed_seconds = (
        float(updated) / 1000
        if isinstance(updated, (int, float)) and not isinstance(updated, bool)
        else path.stat().st_mtime
    )
    if time.time() - observed_seconds <= 5:
        return payload
    health = payload.get("health") if isinstance(payload.get("health"), dict) else {}
    health.update(
        {
            "sidecar_process_running": False,
            "daemon_ready": False,
            "activation_committed": False,
            "browser_ready": False,
        }
    )
    payload["health"] = health
    payload["last_failure"] = {
        "code": "daemon_ready_timeout",
        "phase": "launcher_heartbeat",
        "startup_id": str(payload.get("startup_id") or ""),
        "auto_repairable": False,
    }
    return payload


def _repair_status(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        return {"state": "idle"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"state": "failed", "error_code": "artifact_repair_failed", "phase": "repair_state"}
    expected = {"schema_version", "state", "observed_at_epoch_ms", "error_code", "phase"}
    if (
        not isinstance(payload, dict)
        or set(payload) != expected
        or payload.get("schema_version") != "1"
        or payload.get("state") not in {"idle", "repairing", "failed"}
    ):
        return {"state": "failed", "error_code": "artifact_repair_failed", "phase": "repair_state"}
    return payload


def _health_layers(
    *,
    artifact_ready: bool,
    launcher_health: dict | None = None,
    manager_status: dict | None = None,
    repair_state: str = "idle",
) -> dict:
    runtime = launcher_health or {}
    manager_ready = (manager_status or {}).get("state") == "ready"
    return {
        "adapter_configured": True,
        "artifact_available": artifact_ready,
        "artifact_verified": artifact_ready,
        "artifact_protected": artifact_ready,
        "repair_state": repair_state,
        "sidecar_process_running": manager_ready and runtime.get("sidecar_process_running") is True,
        "daemon_ready": manager_ready and runtime.get("daemon_ready") is True,
        "activation_committed": manager_ready and runtime.get("activation_committed") is True,
        "browser_ready": manager_ready and runtime.get("browser_ready") is True,
    }


def _live_sidecar_status(*, workspace_id: str, app_id: str) -> dict:
    try:
        from core.api.sidecar_control import request_sidecar_control
        from core.shared.repository import discover_repository_root

        payload = request_sidecar_control(
            discover_repository_root(start_path=Path(__file__)),
            operation="status",
            workspace_id=workspace_id,
            app_id=app_id,
            timeout_seconds=2,
        )
        services = payload.get("services") if isinstance(payload, dict) else None
        if not isinstance(services, list):
            raise ValueError("sidecar status response is invalid")
        matches = [
            item
            for item in services
            if isinstance(item, dict) and item.get("sidecar_id") == "opendesign"
        ]
        if len(matches) != 1:
            raise ValueError("OpenDesign sidecar status is missing")
        return matches[0]
    except Exception as error:
        return {
            "state": "failed",
            "phase": getattr(error, "phase", "sidecar_manager_status"),
            "last_failure": {
                "code": getattr(error, "code", "daemon_ready_timeout"),
                "phase": getattr(error, "phase", "sidecar_manager_status"),
                "auto_repairable": False,
            },
        }


def _emit_health(payload: dict) -> None:
    emit_json(payload)
    operational = payload.get("operational", True)
    if payload.get("ok") is not True or operational is not True:
        raise SystemExit(1)


def _declares_protected_store() -> bool:
    path = Path(__file__).resolve().parents[1] / "app_contract.json"
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
        sidecars = contract["services"]["http_sidecars"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return False
    return any(sidecar.get("artifact_mounts") for sidecar in sidecars if isinstance(sidecar, dict))


if __name__ == "__main__":
    main()
