"""Machine and Maverick workspace snapshot collection."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import time
from typing import Any

from process_sampling import aggregate_processes, process_payloads, read_processes, read_total_cpu_ticks


def collect_snapshot(*, workspace_root: Path, data_root: Path, sample_seconds: float = 0.15) -> dict[str, Any]:
    install_root = _installation_root(workspace_root)
    first_processes = read_processes()
    first_cpu = read_total_cpu_ticks()
    time.sleep(max(0.05, min(sample_seconds, 1.0)))
    second_processes = read_processes()
    second_cpu = read_total_cpu_ticks()
    cpu_delta = max(second_cpu - first_cpu, 1)
    cpu_count = max(os.cpu_count() or 1, 1)

    processes = process_payloads(
        install_root=install_root,
        first=first_processes,
        second=second_processes,
        cpu_delta=cpu_delta,
        cpu_count=cpu_count,
    )
    app_rows = aggregate_processes(processes, "app_id", "unknown")
    workspace_rows = _workspace_rows(install_root=install_root, processes=processes)
    service = _service_payload(install_root)
    machine = _machine_payload(install_root)
    insights = _insights(machine=machine, apps=app_rows, workspaces=workspace_rows, processes=processes, service=service)
    return {
        "schema_version": "1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "workspace_id": workspace_root.name,
        "install_root": str(install_root),
        "data_root": str(data_root),
        "machine": machine,
        "apps": app_rows,
        "workspaces": workspace_rows,
        "processes": processes[:80],
        "service": service,
        "insights": insights,
    }


def _installation_root(workspace_root: Path) -> Path:
    root = workspace_root.resolve()
    if root.parent.name == "workspaces":
        return root.parent.parent
    for parent in root.parents:
        if (parent / "apps").is_dir() and (parent / "workspaces").is_dir() and (parent / "core").is_dir():
            return parent
    return Path.cwd().resolve()


def _workspace_rows(*, install_root: Path, processes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    process_rows = {item["id"]: item for item in aggregate_processes(processes, "workspace_id", "platform")}
    rows: list[dict[str, Any]] = []
    workspaces_root = install_root / "workspaces"
    if not workspaces_root.is_dir():
        return rows
    for workspace in sorted(path for path in workspaces_root.iterdir() if path.is_dir()):
        process = process_rows.get(workspace.name, {"cpu_percent": 0.0, "rss_bytes": 0, "process_count": 0})
        rows.append(
            {
                "id": workspace.name,
                "disk_bytes": _directory_size(workspace),
                "data_bytes": _directory_size(workspace / "data"),
                "runtime_bytes": _directory_size(workspace / "runtime"),
                "generated_bytes": _directory_size(workspace / "storage" / "generated"),
                "uploaded_bytes": _directory_size(workspace / "storage" / "uploaded"),
                "cpu_percent": process["cpu_percent"],
                "rss_bytes": process["rss_bytes"],
                "process_count": process["process_count"],
            }
        )
    rows.sort(key=lambda item: (int(item["rss_bytes"]), int(item["disk_bytes"])), reverse=True)
    return rows


def _directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return total
    for root, dirs, files in os.walk(path):
        dirs[:] = [item for item in dirs if item not in {"node_modules", "__pycache__"}]
        for filename in files:
            try:
                total += (Path(root) / filename).stat().st_size
            except OSError:
                continue
    return total


def _machine_payload(install_root: Path) -> dict[str, Any]:
    mem = _meminfo()
    total = int(mem.get("MemTotal", 0)) * 1024
    available = int(mem.get("MemAvailable", 0)) * 1024
    used = max(total - available, 0)
    disk = shutil.disk_usage(install_root)
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    return {
        "cpu_count": os.cpu_count() or 1,
        "load_average": [round(value, 2) for value in load],
        "memory_total_bytes": total,
        "memory_used_bytes": used,
        "memory_available_bytes": available,
        "memory_used_percent": round((used / total) * 100, 2) if total else 0,
        "disk_total_bytes": disk.total,
        "disk_used_bytes": disk.used,
        "disk_free_bytes": disk.free,
        "disk_used_percent": round((disk.used / disk.total) * 100, 2) if disk.total else 0,
    }


def _meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        lines = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        key, _, raw_value = line.partition(":")
        parts = raw_value.strip().split()
        if parts and parts[0].isdigit():
            values[key] = int(parts[0])
    return values


def _service_payload(install_root: Path) -> dict[str, Any]:
    apps_root = install_root / "apps"
    workspaces_root = install_root / "workspaces"
    app_count = len([path for path in apps_root.iterdir() if path.is_dir() and (path / "app_contract.json").is_file()]) if apps_root.is_dir() else 0
    workspace_count = len([path for path in workspaces_root.iterdir() if path.is_dir()]) if workspaces_root.is_dir() else 0
    log_bytes = _directory_size(install_root / "logs") + sum(_directory_size(path / "logs") for path in workspaces_root.iterdir() if path.is_dir()) if workspaces_root.is_dir() else 0
    runtime_bytes = sum(_directory_size(path / "runtime") for path in workspaces_root.iterdir() if path.is_dir()) if workspaces_root.is_dir() else 0
    return {
        "installed_app_count": app_count,
        "workspace_count": workspace_count,
        "log_bytes": log_bytes,
        "runtime_bytes": runtime_bytes,
        "repo_bytes": _directory_size(install_root / "core") + _directory_size(apps_root),
    }


def _insights(
    *,
    machine: dict[str, Any],
    apps: list[dict[str, Any]],
    workspaces: list[dict[str, Any]],
    processes: list[dict[str, Any]],
    service: dict[str, Any],
) -> list[dict[str, str]]:
    insights: list[dict[str, str]] = []
    if float(machine["memory_used_percent"]) >= 85:
        insights.append({"level": "critical", "title": "RAM alta", "detail": "La memoria disponibile e' sotto la soglia operativa consigliata."})
    if float(machine["disk_used_percent"]) >= 85:
        insights.append({"level": "critical", "title": "Disco alto", "detail": "Il disco della root Maverick sta superando l'85% di utilizzo."})
    if apps:
        top = apps[0]
        insights.append({"level": "info", "title": "App piu' attiva", "detail": f"{top['id']} usa {top['cpu_percent']}% CPU e {top['process_count']} processi."})
    if workspaces:
        top_ws = workspaces[0]
        insights.append({"level": "info", "title": "Workspace piu' pesante", "detail": f"{top_ws['id']} usa {top_ws['rss_bytes']} byte RAM RSS e {top_ws['disk_bytes']} byte su disco."})
    if service["runtime_bytes"] > service["repo_bytes"]:
        insights.append({"level": "warning", "title": "Runtime voluminoso", "detail": "Le directory runtime pesano piu' del codice installato."})
    if not processes:
        insights.append({"level": "warning", "title": "Processi non attribuiti", "detail": "La piattaforma non ha potuto leggere i processi da /proc."})
    return insights[:8]
