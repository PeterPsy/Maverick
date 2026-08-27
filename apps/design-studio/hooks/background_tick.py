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

from opendesign_repair_state import failure_identity, write_repair_state  # noqa: E402


AUDIT_INTERVAL_SECONDS = 6 * 60 * 60
AUDIT_FAILURE_BACKOFF_SECONDS = 60 * 60


def run_artifact_operation(*args, **kwargs):
    """Import the full verifier only after the protected marker says audit is due."""
    from opendesign_artifact_operations import run_artifact_operation as operation

    return operation(*args, **kwargs)


def discover_workspace_data_roots(*args, **kwargs):
    """Load the canonical global registry only on audit/recovery paths."""
    from opendesign_artifact_operations import (
        discover_design_studio_workspace_data_roots as discover,
    )

    return discover(*args, **kwargs)


def artifact_reference_coverage(*args, **kwargs):
    """Load the no-content reference scanner only for the scheduler check."""
    from opendesign_artifact_operations import global_artifact_reference_coverage

    return global_artifact_reference_coverage(*args, **kwargs)


def request_sidecar_control(*args, **kwargs):
    """Load live-manager control only on the failed-audit recovery path."""
    from core.api.sidecar_control import request_sidecar_control as request

    return request(*args, **kwargs)


def governed_runtime_smoke(*args, **kwargs):
    """Load the post-repair runtime proof only on the recovery path."""
    from opendesign_artifact_operations import governed_repair_runtime_smoke

    return governed_repair_runtime_smoke(*args, **kwargs)


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
    descriptor = os.open(lock_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            emit_json({"ok": True, "audit": {"status": "deduplicated"}})
            return
        try:
            coverage = artifact_reference_coverage(
                REPOSITORY_ROOT,
                requested_workspace_id=workspace_id,
            )
        except Exception as reference_error:
            if not _audit_due(marker_path, reference_scan_failed=True):
                emit_json(
                    {
                        "ok": True,
                        "audit": {
                            "status": "not_due",
                            "reason": "reference_scan_backoff",
                        },
                    }
                )
                return
            _handle_failed_audit(
                reference_error,
                marker_path=marker_path,
                data_root=data_root,
                workspace_id=workspace_id,
                attempted_at_epoch_ms=int(time.time() * 1000),
            )
            return
        if not _audit_due(
            marker_path,
            expected_reference_sha256=str(
                coverage["workspace_reference_sha256"]
            ),
        ):
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
                auto=True,
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
    # The immutable authority already persisted the redacted audit failure;
    # this process owns only workspace readiness/recovery state.
    failure_identity(
        audit_error,
        default_code="artifact_integrity_mismatch",
        default_phase="artifact_full_verify",
    )
    del marker_path, attempted_at_epoch_ms
    _invalidate_transactional_readiness(data_root)
    try:
        recovery = _recover_failed_audit(
            data_root=data_root,
            workspace_id=workspace_id,
        )
    except Exception as recovery_error:
        recovery_code, recovery_phase = failure_identity(recovery_error)
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
    """Stop every consumer, repair the global store once, then restore consumers."""
    workspace_roots = {workspace_id: data_root}
    write_repair_state(data_root, state="repairing")
    _invalidate_transactional_readiness(data_root)
    affected_workspace_ids: tuple[str, ...] = ()
    try:
        # Stop/revoke globally before trusting the workspace registry.  A
        # malformed or racing registry must never leave another consumer live.
        stopped = request_sidecar_control(
            REPOSITORY_ROOT,
            operation="stop-all-workspaces",
            workspace_id=workspace_id,
            app_id="design-studio",
            timeout_seconds=10,
        )
        affected = stopped.get("affected_workspace_ids")
        if (
            not isinstance(affected, list)
            or any(not isinstance(item, str) for item in affected)
            or len(set(affected)) != len(affected)
        ):
            raise RuntimeError("Global sidecar stop returned an invalid workspace set")
        affected_workspace_ids = tuple(sorted(affected))
        discovered = discover_workspace_data_roots(
            REPOSITORY_ROOT,
            requested_workspace_id=workspace_id,
        )
        discovered[workspace_id] = data_root
        workspace_roots = dict(sorted(discovered.items()))
        if any(item not in workspace_roots for item in affected_workspace_ids):
            raise RuntimeError("A live Design Studio sidecar has no canonical workspace root")
        for candidate_workspace_id, root in workspace_roots.items():
            if candidate_workspace_id != workspace_id:
                write_repair_state(root, state="repairing")
            _invalidate_transactional_readiness(root)
        repair = run_artifact_operation(
            "repair",
            data_root=data_root,
            workspace_id=workspace_id,
            auto=True,
            complete_repair=False,
        )
        if repair.get("status") != "materialized":
            raise RuntimeError("Governed global artifact repair did not materialize")
        for affected_workspace_id in affected_workspace_ids:
            restarted = request_sidecar_control(
                REPOSITORY_ROOT,
                operation="restart",
                workspace_id=affected_workspace_id,
                app_id="design-studio",
                timeout_seconds=20,
            )
            readiness = restarted.get("readiness")
            if (
                restarted.get("status") != "ready"
                or not isinstance(readiness, dict)
                or readiness.get("ready") is not True
            ):
                raise RuntimeError(
                    "Governed background repair did not pass global restart readiness"
                )
            governed_runtime_smoke(
                REPOSITORY_ROOT,
                data_root=workspace_roots[affected_workspace_id],
                workspace_id=affected_workspace_id,
                restarted=restarted,
            )
    except Exception as error:
        try:
            request_sidecar_control(
                REPOSITORY_ROOT,
                operation="stop-all-workspaces",
                workspace_id=workspace_id,
                app_id="design-studio",
                timeout_seconds=10,
            )
        except Exception:
            pass
        code, phase = failure_identity(error)
        for root in workspace_roots.values():
            _invalidate_transactional_readiness(root)
            write_repair_state(
                root,
                state="failed",
                error_code=code,
                phase=phase,
            )
        raise
    for root in workspace_roots.values():
        write_repair_state(root, state="idle")
    return {
        "store_generation": repair["store_generation"],
        "runtime_count": len(repair.get("retained_runtime_artifacts", [])),
        "web_count": len(repair.get("retained_web_overlays", [])),
        "restarted_workspace_ids": list(affected_workspace_ids),
    }


def _invalidate_transactional_readiness(data_root: Path) -> None:
    try:
        (data_root / "opendesign" / "maverick-ready.json").unlink(missing_ok=True)
    except OSError:
        # The Core-owned stop remains the authoritative process gate.
        pass


def _audit_due(
    path: Path,
    *,
    expected_reference_sha256: str | None = None,
    reference_scan_failed: bool = False,
) -> bool:
    if path.is_symlink():
        return True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    if not isinstance(payload, dict):
        return True
    if payload.get("schema_version") != "3":
        return True
    now = time.time() * 1000
    next_attempt = payload.get("next_attempt_at_epoch_ms")
    if reference_scan_failed:
        return not (
            payload.get("status") == "failed"
            and payload.get("workspace_reference_sha256") is None
            and isinstance(next_attempt, int)
            and now < next_attempt
        )
    if (
        expected_reference_sha256 is not None
        and payload.get("workspace_reference_sha256") != expected_reference_sha256
    ):
        return True
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
