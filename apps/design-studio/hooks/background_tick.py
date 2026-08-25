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
from opendesign_artifact_operations import run_artifact_operation  # noqa: E402


AUDIT_INTERVAL_SECONDS = 6 * 60 * 60


def main() -> None:
    payload = read_entrypoint_payload()
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
        result = run_artifact_operation(
            "verify",
            data_root=Path(payload.data_root),
            workspace_id=str(payload.workspace_id or "default"),
            audit_workers=_adaptive_audit_workers(),
        )
        marker_path.parent.mkdir(mode=0o750, exist_ok=True)
        marker_path.parent.chmod(0o750)
        write_canonical_json(
            marker_path,
            {
                "schema_version": "1",
                "verified_at_epoch_ms": int(time.time() * 1000),
                "store_generation": result["store_generation"],
                "runtime_count": len(result["audited_runtime"]),
                "web_count": len(result["audited_web"]),
            },
        )
        marker_path.chmod(0o640)
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


def _audit_due(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    observed = payload.get("verified_at_epoch_ms") if isinstance(payload, dict) else None
    return not isinstance(observed, int) or time.time() * 1000 - observed >= AUDIT_INTERVAL_SECONDS * 1000


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
