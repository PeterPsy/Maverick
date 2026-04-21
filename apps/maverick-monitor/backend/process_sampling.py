"""Process sampling and Maverick ownership attribution."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

CLK_TCK = os.sysconf(os.sysconf_names.get("SC_CLK_TCK", "SC_CLK_TCK"))
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")


@dataclass(frozen=True)
class ProcessSample:
    pid: int
    command: str
    cwd: str
    rss_bytes: int
    cpu_time_ticks: int


def read_total_cpu_ticks() -> int:
    try:
        first_line = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
    except OSError:
        return 1
    return sum(int(value) for value in first_line.split()[1:] if value.isdigit())


def read_processes() -> dict[int, ProcessSample]:
    processes: dict[int, ProcessSample] = {}
    proc = Path("/proc")
    if not proc.is_dir():
        return processes
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        sample = _read_process(int(entry.name))
        if sample is not None:
            processes[sample.pid] = sample
    return processes


def process_payloads(
    *,
    install_root: Path,
    first: dict[int, ProcessSample],
    second: dict[int, ProcessSample],
    cpu_delta: int,
    cpu_count: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pid, current in second.items():
        previous = first.get(pid)
        proc_delta = max(current.cpu_time_ticks - previous.cpu_time_ticks, 0) if previous else 0
        cpu_percent = round((proc_delta / cpu_delta) * cpu_count * 100, 2)
        rows.append(
            {
                "pid": pid,
                "command": current.command[:220],
                "cwd": current.cwd,
                "app_id": classify_app_id(install_root, current.command, current.cwd),
                "workspace_id": classify_workspace_id(install_root, current.command, current.cwd),
                "rss_bytes": current.rss_bytes,
                "cpu_percent": cpu_percent,
                "cpu_time_seconds": round(current.cpu_time_ticks / CLK_TCK, 2),
            }
        )
    rows.sort(key=lambda item: (float(item["cpu_percent"]), int(item["rss_bytes"])), reverse=True)
    return rows


def aggregate_processes(processes: list[dict[str, Any]], key: str, excluded: str) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = defaultdict(lambda: {"cpu_percent": 0.0, "rss_bytes": 0, "process_count": 0})
    for process in processes:
        group_id = str(process.get(key) or excluded)
        if group_id == excluded:
            continue
        totals[group_id]["cpu_percent"] += float(process["cpu_percent"])
        totals[group_id]["rss_bytes"] += int(process["rss_bytes"])
        totals[group_id]["process_count"] += 1
    rows = [
        {"id": group_id, **values, "cpu_percent": round(values["cpu_percent"], 2)}
        for group_id, values in totals.items()
    ]
    rows.sort(key=lambda item: (float(item["cpu_percent"]), int(item["rss_bytes"])), reverse=True)
    return rows


def classify_app_id(install_root: Path, command: str, cwd: str) -> str:
    text = f"{command} {cwd}"
    app_roots = [install_root / "apps"]
    workspace_apps = install_root / "workspaces"
    if workspace_apps.is_dir():
        app_roots.extend(path / "apps" for path in workspace_apps.iterdir() if path.is_dir())
    for root in app_roots:
        root_marker = str(root.resolve()) + os.sep if root.exists() else str(root) + os.sep
        if root_marker not in text:
            continue
        suffix = text.split(root_marker, 1)[1]
        app_id = suffix.split(os.sep, 1)[0].split(" ", 1)[0]
        if app_id and app_id not in {".", ".."}:
            return app_id
    return "unattributed"


def classify_workspace_id(install_root: Path, command: str, cwd: str) -> str:
    marker = str((install_root / "workspaces").resolve()) + os.sep
    text = f"{command} {cwd}"
    if marker not in text:
        return "platform"
    suffix = text.split(marker, 1)[1]
    workspace_id = suffix.split(os.sep, 1)[0].split(" ", 1)[0]
    return workspace_id or "platform"


def _read_process(pid: int) -> ProcessSample | None:
    proc_dir = Path("/proc") / str(pid)
    try:
        stat_parts = (proc_dir / "stat").read_text(encoding="utf-8").split()
        rss_pages = int(stat_parts[23])
        cpu_time_ticks = int(stat_parts[13]) + int(stat_parts[14])
    except (OSError, IndexError, ValueError):
        return None
    try:
        cmdline = (proc_dir / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
    except OSError:
        cmdline = ""
    try:
        command = (proc_dir / "comm").read_text(encoding="utf-8").strip()
    except OSError:
        command = ""
    try:
        cwd = str((proc_dir / "cwd").resolve())
    except OSError:
        cwd = ""
    return ProcessSample(
        pid=pid,
        command=cmdline or command or f"pid:{pid}",
        cwd=cwd,
        rss_bytes=max(rss_pages, 0) * PAGE_SIZE,
        cpu_time_ticks=cpu_time_ticks,
    )
