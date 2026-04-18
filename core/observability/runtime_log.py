"""Filesystem-backed runtime and platform log helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from core.observability.models import LogPlane, RuntimeLogRecord
from core.observability.redaction import redact_payload
from core.shared.repository import installation_paths
from core.workspaces.paths import workspace_paths


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def ensure_log_roots(*, workspace_id: str | None = None, app_id: str | None = None, start_path: Path | None = None) -> dict[str, Path]:
    """Create canonical installation-level and workspace log roots."""
    installation = installation_paths(start_path=start_path)
    installation.platform_logs_root.mkdir(parents=True, exist_ok=True)
    installation.runtime_logs_root.mkdir(parents=True, exist_ok=True)
    roots = {
        "platform": installation.platform_logs_root,
        "runtime": installation.runtime_logs_root,
    }
    if workspace_id is not None:
        workspace = workspace_paths(workspace_id=workspace_id, start_path=start_path)
        workspace.logs.mkdir(parents=True, exist_ok=True)
        workspace_workspace_root = workspace.logs / "workspace"
        workspace_apps_root = workspace.logs / "apps"
        workspace_workspace_root.mkdir(parents=True, exist_ok=True)
        workspace_apps_root.mkdir(parents=True, exist_ok=True)
        roots["workspace"] = workspace_workspace_root
        roots["workspace_apps"] = workspace_apps_root
        if app_id is not None:
            app_root = workspace_apps_root / app_id
            app_root.mkdir(parents=True, exist_ok=True)
            roots["app"] = app_root
    return roots


def _log_file_for_plane(
    *,
    log_plane: LogPlane,
    workspace_id: str | None = None,
    app_id: str | None = None,
    timestamp: datetime,
    start_path: Path | None = None,
) -> Path:
    roots = ensure_log_roots(workspace_id=workspace_id, app_id=app_id, start_path=start_path)
    suffix = timestamp.strftime("%Y%m%d")
    if log_plane == "platform":
        return roots["platform"] / f"platform-{suffix}.jsonl"
    if log_plane == "runtime":
        return roots["runtime"] / f"runtime-{suffix}.jsonl"
    if log_plane == "workspace":
        return roots["workspace"] / f"workspace-{suffix}.jsonl"
    if log_plane == "app":
        return roots["app"] / f"app-{suffix}.jsonl"
    raise ValueError(f"Unsupported log plane `{log_plane}`.")


def apply_retention(*, log_root: Path, max_files: int = 20) -> None:
    """Retain only the newest log files inside one log root."""
    files = sorted([path for path in log_root.iterdir() if path.is_file()], key=lambda item: item.stat().st_mtime, reverse=True)
    for stale in files[max_files:]:
        stale.unlink(missing_ok=True)


def append_runtime_log(
    *,
    log_plane: LogPlane,
    message: str,
    payload: dict,
    workspace_id: str | None = None,
    app_id: str | None = None,
    runtime_session_id: str | None = None,
    provider_id: str | None = None,
    start_path: Path | None = None,
    now: datetime | None = None,
) -> RuntimeLogRecord:
    """Append one redacted JSON log line to the canonical log root for the target plane."""
    timestamp = now or utcnow()
    log_path = _log_file_for_plane(
        log_plane=log_plane,
        workspace_id=workspace_id,
        app_id=app_id,
        timestamp=timestamp,
        start_path=start_path,
    )
    redacted_payload = redact_payload(payload)
    entry = {
        "occurred_at": timestamp.isoformat(),
        "workspace_id": workspace_id,
        "app_id": app_id,
        "runtime_session_id": runtime_session_id,
        "provider_id": provider_id,
        "message": message,
        "payload": redacted_payload,
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    apply_retention(log_root=log_path.parent)
    return RuntimeLogRecord(
        log_id=str(uuid4()),
        log_plane=log_plane,
        workspace_id=workspace_id,
        app_id=app_id,
        runtime_session_id=runtime_session_id,
        provider_id=provider_id,
        log_path=str(log_path),
        message=message,
        occurred_at=timestamp,
    )
