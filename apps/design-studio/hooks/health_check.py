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
        emit_json({"ok": True, "operational": True, "schema_version": state.get("schema_version")})
        return
    service_root = Path(__file__).resolve().parents[1] / "service"
    sys.path.insert(0, str(service_root))
    try:
        from opendesign_artifact_operations import run_artifact_operation

        artifact = run_artifact_operation("status", data_root=Path(payload.data_root))
    except Exception as error:
        emit_json(
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
    launcher = _launcher_status(Path(payload.data_root) / "opendesign" / "launcher-status.json")
    launcher_health = launcher.get("health") if isinstance(launcher.get("health"), dict) else {}
    last_failure = launcher.get("last_failure") if isinstance(launcher.get("last_failure"), dict) else None
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
    browser_ready = (
        artifact_ready
        and repair_state == "idle"
        and launcher_health.get("browser_ready") is True
        and last_failure is None
    )
    emit_json(
        {
            "ok": browser_ready,
            "operational": browser_ready,
            "schema_version": state.get("schema_version"),
            "health": _health_layers(
                artifact_ready=artifact_ready,
                launcher_health=launcher_health,
                repair_state=repair_state,
            ),
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
    repair_state: str = "idle",
) -> dict:
    runtime = launcher_health or {}
    return {
        "adapter_configured": True,
        "artifact_available": artifact_ready,
        "artifact_verified": artifact_ready,
        "artifact_protected": artifact_ready,
        "repair_state": repair_state,
        "sidecar_process_running": runtime.get("sidecar_process_running") is True,
        "daemon_ready": runtime.get("daemon_ready") is True,
        "activation_committed": runtime.get("activation_committed") is True,
        "browser_ready": runtime.get("browser_ready") is True,
    }


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
