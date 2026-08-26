"""Run a deduplicated, low-priority protected-store audit outside launch."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from core.app_sdk.runtime import emit_json, read_entrypoint_payload
from core.apps.artifact_mounts import platform_artifact_store_root


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
REPOSITORY_ROOT = SERVICE_ROOT.parents[2]
sys.path.insert(0, str(SERVICE_ROOT))

from opendesign_artifact import write_canonical_json  # noqa: E402
from opendesign_repair_state import failure_identity, write_repair_state  # noqa: E402


AUDIT_INTERVAL_SECONDS = 6 * 60 * 60
AUDIT_FAILURE_BACKOFF_SECONDS = 60 * 60


def run_artifact_operation(*args, **kwargs):
    """Import the full verifier only after the protected marker says audit is due."""
    from opendesign_artifact_operations import run_artifact_operation as operation

    return operation(*args, **kwargs)


def request_sidecar_control(*args, **kwargs):
    """Load live-manager control only on the failed-audit recovery path."""
    from core.api.sidecar_control import request_sidecar_control as request

    return request(*args, **kwargs)


def main() -> None:
    payload = read_entrypoint_payload()
    data_root = Path(payload.data_root)
    workspace_id = str(payload.workspace_id or "default")
    namespace = (
        platform_artifact_store_root(REPOSITORY_ROOT)
        / "design-studio"
        / "opendesign"
    )
    lock_path = namespace / ".locks/background-full-audit.lock"
    marker_path = namespace / "audit/background-full-audit.json"
    if _under_pressure():
        emit_json({"ok": True, "audit": {"status": "suspended", "reason": "system_pressure"}})
        return
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o640)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            emit_json({"ok": True, "audit": {"status": "deduplicated"}})
            return
        if not _audit_due(marker_path):
            emit_json({"ok": True, "audit": {"status": "not_due"}})
            return
        _lower_io_and_cpu_priority()
        attempted_at = int(time.time() * 1000)
        try:
            result = run_artifact_operation(
                "verify",
                data_root=data_root,
                workspace_id=workspace_id,
                audit_workers=_adaptive_audit_workers(),
            )
        except Exception as audit_error:
            _handle_failed_audit(
                audit_error,
                marker_path=marker_path,
                data_root=data_root,
                workspace_id=workspace_id,
                attempted_at_epoch_ms=attempted_at,
            )
            return
        _write_audit_marker(
            marker_path,
            {
                "schema_version": "2",
                "status": "passed",
                "attempted_at_epoch_ms": attempted_at,
                "verified_at_epoch_ms": int(time.time() * 1000),
                "next_attempt_at_epoch_ms": attempted_at + AUDIT_INTERVAL_SECONDS * 1000,
                "store_generation": result["store_generation"],
                "runtime_count": len(result["audited_runtime"]),
                "web_count": len(result["audited_web"]),
                "auto_repair_requested": False,
                "audit_error_code": None,
                "audit_phase": None,
                "recovery_error_code": None,
                "recovery_phase": None,
            },
        )
        emit_json(
            {
                "ok": True,
                "audit": {
                    "status": "passed",
                    "runtime_count": len(result["audited_runtime"]),
                    "web_count": len(result["audited_web"]),
                },
            }
        )
    finally:
        os.close(descriptor)


def _handle_failed_audit(
    audit_error: BaseException,
    *,
    marker_path: Path,
    data_root: Path,
    workspace_id: str,
    attempted_at_epoch_ms: int,
) -> None:
    audit_code, audit_phase = failure_identity(
        audit_error,
        default_code="artifact_integrity_mismatch",
        default_phase="artifact_full_verify",
    )
    _invalidate_transactional_readiness(data_root)
    _write_audit_marker(
        marker_path,
        {
            "schema_version": "2",
            "status": "repairing",
            "attempted_at_epoch_ms": attempted_at_epoch_ms,
            "verified_at_epoch_ms": None,
            "next_attempt_at_epoch_ms": (
                attempted_at_epoch_ms + AUDIT_FAILURE_BACKOFF_SECONDS * 1000
            ),
            "store_generation": None,
            "runtime_count": 0,
            "web_count": 0,
            "auto_repair_requested": True,
            "audit_error_code": audit_code,
            "audit_phase": audit_phase,
            "recovery_error_code": None,
            "recovery_phase": None,
        },
    )
    try:
        recovery = _recover_failed_audit(
            data_root=data_root,
            workspace_id=workspace_id,
        )
    except Exception as recovery_error:
        recovery_code, recovery_phase = failure_identity(recovery_error)
        _write_audit_marker(
            marker_path,
            {
                "schema_version": "2",
                "status": "failed",
                "attempted_at_epoch_ms": attempted_at_epoch_ms,
                "verified_at_epoch_ms": None,
                "next_attempt_at_epoch_ms": (
                    attempted_at_epoch_ms + AUDIT_FAILURE_BACKOFF_SECONDS * 1000
                ),
                "store_generation": None,
                "runtime_count": 0,
                "web_count": 0,
                "auto_repair_requested": True,
                "audit_error_code": audit_code,
                "audit_phase": audit_phase,
                "recovery_error_code": recovery_code,
                "recovery_phase": recovery_phase,
            },
        )
        emit_json(
            {
                "ok": False,
                "audit": {
                    "status": "failed_closed",
                    "error_code": recovery_code,
                    "phase": recovery_phase,
                    "retry_after_seconds": AUDIT_FAILURE_BACKOFF_SECONDS,
                },
            }
        )
        raise SystemExit(1) from None

    verified_at = int(time.time() * 1000)
    _write_audit_marker(
        marker_path,
        {
            "schema_version": "2",
            "status": "recovered",
            "attempted_at_epoch_ms": attempted_at_epoch_ms,
            "verified_at_epoch_ms": verified_at,
            "next_attempt_at_epoch_ms": verified_at + AUDIT_INTERVAL_SECONDS * 1000,
            "store_generation": recovery["store_generation"],
            "runtime_count": recovery["runtime_count"],
            "web_count": recovery["web_count"],
            "auto_repair_requested": True,
            "audit_error_code": audit_code,
            "audit_phase": audit_phase,
            "recovery_error_code": None,
            "recovery_phase": None,
        },
    )
    emit_json(
        {
            "ok": True,
            "audit": {
                "status": "recovered",
                "runtime_count": recovery["runtime_count"],
                "web_count": recovery["web_count"],
            },
        }
    )


def _recover_failed_audit(*, data_root: Path, workspace_id: str) -> dict[str, object]:
    """Revoke readiness, stop the invalid daemon, repair once, and restart directly."""
    write_repair_state(data_root, state="repairing")
    try:
        _invalidate_transactional_readiness(data_root)
        request_sidecar_control(
            REPOSITORY_ROOT,
            operation="stop",
            workspace_id=workspace_id,
            app_id="design-studio",
            timeout_seconds=10,
        )
        repair = run_artifact_operation(
            "repair",
            data_root=data_root,
            workspace_id=workspace_id,
            auto=True,
        )
        restarted = request_sidecar_control(
            REPOSITORY_ROOT,
            operation="restart",
            workspace_id=workspace_id,
            app_id="design-studio",
            timeout_seconds=20,
        )
        readiness = restarted.get("readiness")
        if (
            repair.get("status") != "ready"
            or restarted.get("status") != "ready"
            or not isinstance(readiness, dict)
            or readiness.get("ready") is not True
        ):
            raise RuntimeError("Governed background repair did not pass restart readiness")
    except Exception as error:
        code, phase = failure_identity(error)
        write_repair_state(
            data_root,
            state="failed",
            error_code=code,
            phase=phase,
        )
        raise
    write_repair_state(data_root, state="idle")
    return {
        "store_generation": repair["store_generation"],
        "runtime_count": len(repair.get("retained_runtime_artifacts", [])),
        "web_count": len(repair.get("retained_web_overlays", [])),
    }


def _invalidate_transactional_readiness(data_root: Path) -> None:
    try:
        (data_root / "opendesign" / "maverick-ready.json").unlink(missing_ok=True)
    except OSError:
        # The Core-owned stop remains the authoritative process gate.
        pass


def _write_audit_marker(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o750, exist_ok=True)
    path.parent.chmod(0o750)
    write_canonical_json(path, payload)
    path.chmod(0o640)


def _audit_due(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    if not isinstance(payload, dict):
        return True
    now = time.time() * 1000
    next_attempt = payload.get("next_attempt_at_epoch_ms")
    if isinstance(next_attempt, int):
        return now >= next_attempt
    observed = payload.get("verified_at_epoch_ms")
    return not isinstance(observed, int) or now - observed >= AUDIT_INTERVAL_SECONDS * 1000


def _under_pressure() -> bool:
    try:
        load = os.getloadavg()[0]
    except OSError:
        load = 0.0
    cpus = max(1, os.cpu_count() or 1)
    if load > cpus * 1.5:
        return True
    if _pressure_average(Path("/sys/fs/cgroup/cpu.pressure"), resource="some") >= 10.0:
        return True
    if _pressure_average(Path("/sys/fs/cgroup/io.pressure"), resource="some") >= 5.0:
        return True
    try:
        memory = Path("/proc/meminfo").read_text(encoding="utf-8")
        available_line = next(line for line in memory.splitlines() if line.startswith("MemAvailable:"))
        available_kib = int(available_line.split()[1])
    except (OSError, StopIteration, ValueError, IndexError):
        return False
    return available_kib < 1024 * 1024


def _adaptive_audit_workers() -> int:
    cpus = max(1, os.cpu_count() or 1)
    try:
        load = os.getloadavg()[0]
    except OSError:
        load = float(cpus)
    if load >= cpus or _pressure_average(Path("/sys/fs/cgroup/cpu.pressure"), resource="some") >= 2.0:
        return 1
    return max(1, min(2, cpus // 2))


def _pressure_average(path: Path, *, resource: str) -> float:
    try:
        lines = path.read_text(encoding="ascii").splitlines()
        fields = next(line.split() for line in lines if line.startswith(f"{resource} "))
        value = next(field.split("=", 1)[1] for field in fields[1:] if field.startswith("avg10="))
        return max(0.0, float(value))
    except (OSError, UnicodeDecodeError, StopIteration, ValueError, IndexError):
        return 0.0


def _lower_io_and_cpu_priority() -> None:
    try:
        os.nice(19)
    except OSError:
        pass
    try:
        subprocess.run(
            ["/usr/bin/ionice", "-c", "3", "-p", str(os.getpid())],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        pass


if __name__ == "__main__":
    main()
