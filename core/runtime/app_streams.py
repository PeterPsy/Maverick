"""Durable app-owned views over generic runtime turn events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from core.runtime.runtime_events import RuntimeEventRecord


RuntimeAppStreamStatus = Literal[
    "reserving",
    "submitted",
    "running",
    "completed",
    "failed",
    "cancelled",
    "timed-out",
]

RUNTIME_APP_STREAM_EVENT_TYPES = frozenset(
    {
        "runtime.turn.queued",
        "runtime.turn.started",
        "runtime.output.delta",
        "runtime.output.final",
        "runtime.file.changed",
        "runtime.turn.completed",
        "runtime.turn.failed",
        "runtime.turn.cancelled",
        "runtime.turn.timed-out",
    }
)
RUNTIME_APP_STREAM_TERMINAL_TYPES = frozenset(
    {
        "runtime.turn.completed",
        "runtime.turn.failed",
        "runtime.turn.cancelled",
        "runtime.turn.timed-out",
    }
)
MAX_STREAM_TEXT_BYTES = 64 * 1024
MAX_STREAM_FILE_PATH_BYTES = 1024
MAX_STREAM_FILE_SNAPSHOT_ENTRIES = 2_000


@dataclass(frozen=True)
class RuntimeAppStreamRecord:
    """Generic durable correlation between one app request and one runtime turn."""

    stream_id: str
    workspace_id: str
    source_app_id: str
    actor_id: str
    request_id: str
    idempotency_key: str
    request_fingerprint: str
    session_id: str
    turn_id: str
    status: RuntimeAppStreamStatus
    last_sequence: int
    initial_file_state: dict[str, str] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class RuntimeAppStreamEventRecord:
    """One ordered, provider-neutral event in an app runtime stream."""

    stream_id: str
    workspace_id: str
    source_app_id: str
    session_id: str
    turn_id: str
    sequence: int
    event_id: str
    event_type: str
    payload: dict[str, Any]
    terminal: bool
    created_at: datetime


class RuntimeAppStreamError(RuntimeError):
    """Fail-closed runtime stream ownership, identity, or state error."""


def normalized_stream_event(record: RuntimeEventRecord) -> tuple[str, dict[str, Any], bool] | None:
    """Return the bounded public runtime projection for one persisted event."""
    if record.event_type not in RUNTIME_APP_STREAM_EVENT_TYPES:
        return None
    payload: dict[str, Any] = {}
    if record.event_type in {"runtime.output.delta", "runtime.output.final"}:
        text = record.payload.get("text") or record.payload.get("output_text")
        if isinstance(text, str) and text:
            payload["text"] = _bounded_utf8(text, MAX_STREAM_TEXT_BYTES)
    elif record.event_type == "runtime.file.changed":
        path = normalized_project_relative_path(record.payload.get("path"))
        if path is None:
            return None
        payload = {
            "path": path,
            "change": str(record.payload.get("change") or "modified")
            if str(record.payload.get("change") or "modified") in {"created", "modified", "deleted"}
            else "modified",
        }
    elif record.event_type in RUNTIME_APP_STREAM_TERMINAL_TYPES:
        payload["reason"] = record.event_type.removeprefix("runtime.turn.")
    return record.event_type, payload, record.event_type in RUNTIME_APP_STREAM_TERMINAL_TYPES


def stream_status_for_event(event_type: str, current: RuntimeAppStreamStatus) -> RuntimeAppStreamStatus:
    """Derive stream lifecycle without accepting provider-specific states."""
    by_type: dict[str, RuntimeAppStreamStatus] = {
        "runtime.turn.queued": "submitted",
        "runtime.turn.started": "running",
        "runtime.turn.completed": "completed",
        "runtime.turn.failed": "failed",
        "runtime.turn.cancelled": "cancelled",
        "runtime.turn.timed-out": "timed-out",
    }
    return by_type.get(event_type, current)


def snapshot_project_files(root: str | Path) -> dict[str, str]:
    """Return a bounded symlink-free project snapshot without exposing the root."""
    directory = Path(root)
    try:
        if directory.is_symlink() or not directory.is_dir():
            return {}
        resolved_root = directory.resolve(strict=True)
    except OSError:
        return {}
    snapshot: dict[str, str] = {}
    try:
        candidates = sorted(directory.rglob("*"), key=lambda item: item.as_posix())
    except OSError:
        return {}
    for candidate in candidates:
        if len(snapshot) >= MAX_STREAM_FILE_SNAPSHOT_ENTRIES:
            break
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            resolved = candidate.resolve(strict=True)
            relative = resolved.relative_to(resolved_root).as_posix()
            normalized = normalized_project_relative_path(relative)
            if normalized is None:
                continue
            stat_result = candidate.stat()
        except (OSError, ValueError):
            continue
        snapshot[normalized] = f"{stat_result.st_size}:{stat_result.st_mtime_ns}"
    return snapshot


def changed_project_files(before: dict[str, str], after: dict[str, str]) -> list[tuple[str, str]]:
    """Return deterministic created/modified/deleted file changes."""
    changes: list[tuple[str, str]] = []
    for path in sorted(set(before) | set(after)):
        if path not in before:
            changes.append((path, "created"))
        elif path not in after:
            changes.append((path, "deleted"))
        elif before[path] != after[path]:
            changes.append((path, "modified"))
    return changes


def normalized_project_relative_path(value: object) -> str | None:
    """Validate a project-relative path for a generic file-change event."""
    if not isinstance(value, str) or not value.strip() or "\\" in value:
        return None
    candidate = PurePosixPath(value.strip())
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        return None
    normalized = candidate.as_posix()
    if len(normalized.encode("utf-8")) > MAX_STREAM_FILE_PATH_BYTES:
        return None
    return normalized


def _bounded_utf8(value: str, maximum_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return value
    return encoded[:maximum_bytes].decode("utf-8", errors="ignore")
