"""Storage-owned state for Google Drive resumable uploads."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import os
import secrets
from typing import Any

from errors import StorageValidationError
from storage_provider_model import GOOGLE_DRIVE_PROVIDER


DRIVE_UPLOAD_SESSIONS_DIR = "drive_upload_sessions"
DRIVE_UPLOAD_SESSION_TTL_SECONDS = 24 * 60 * 60


def create_drive_upload_session(
    *,
    data_root: Path,
    connection_id: str,
    parent_drive_file_id: str,
    file_name: str,
    content_type: str,
    size_bytes: int,
    session_uri: str,
    parent_display_path: str,
) -> dict[str, Any]:
    prune_drive_upload_sessions(data_root=data_root)
    session_id = f"drive_upload_{secrets.token_hex(16)}"
    now = _timestamp()
    record = {
        "schema_version": "1",
        "id": session_id,
        "status": "uploading",
        "provider": GOOGLE_DRIVE_PROVIDER,
        "connection_id": connection_id,
        "parent_drive_file_id": parent_drive_file_id,
        "parent_display_path": parent_display_path,
        "file_name": file_name,
        "content_type": content_type,
        "size_bytes": size_bytes,
        "bytes_uploaded": 0,
        "retry_count": 0,
        "error": "",
        "session_uri": session_uri,
        "file": None,
        "created_at": now,
        "updated_at": now,
        "expires_at": (datetime.now(tz=UTC) + timedelta(seconds=DRIVE_UPLOAD_SESSION_TTL_SECONDS)).isoformat(),
    }
    _write_session(data_root, record)
    return public_drive_upload_session(record)


def get_drive_upload_session(*, data_root: Path, session_id: str) -> dict[str, Any]:
    record = _read_session(data_root, session_id)
    if _is_expired(record):
        _session_path(data_root, session_id).unlink(missing_ok=True)
        raise StorageValidationError("Drive upload session has expired. Start the upload again.", operation="drive_upload_session.status")
    return record


def update_drive_upload_session(*, data_root: Path, session_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    record = get_drive_upload_session(data_root=data_root, session_id=session_id)
    updated = {**record, **updates, "updated_at": _timestamp()}
    _write_session(data_root, updated)
    return public_drive_upload_session(updated)


def public_drive_upload_session(record: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in record.items() if key != "session_uri"}
    total = int(public.get("size_bytes") or 0)
    uploaded = int(public.get("bytes_uploaded") or 0)
    public["progress"] = {
        "state": "complete" if public.get("status") == "complete" else str(public.get("status") or "uploading"),
        "bytes_completed": uploaded,
        "bytes_total": total,
    }
    return public


def prune_drive_upload_sessions(*, data_root: Path) -> None:
    root = data_root / DRIVE_UPLOAD_SESSIONS_DIR
    if not root.exists():
        return
    for path in root.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            path.unlink(missing_ok=True)
            continue
        if not isinstance(record, dict) or _is_expired(record):
            path.unlink(missing_ok=True)


def _read_session(data_root: Path, session_id: str) -> dict[str, Any]:
    session_id = _required_session_id(session_id)
    path = _session_path(data_root, session_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise StorageValidationError("Drive upload session was not found.", operation="drive_upload_session.status") from error
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise StorageValidationError("Drive upload session metadata is not readable.", operation="drive_upload_session.status") from error
    if not isinstance(payload, dict):
        raise StorageValidationError("Drive upload session metadata is invalid.", operation="drive_upload_session.status")
    return payload


def _write_session(data_root: Path, record: dict[str, Any]) -> None:
    path = _session_path(data_root, str(record.get("id") or ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary_path.open("w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary_path.replace(path)
    path.chmod(0o600)


def _session_path(data_root: Path, session_id: str) -> Path:
    return data_root / DRIVE_UPLOAD_SESSIONS_DIR / f"{_required_session_id(session_id)}.json"


def _required_session_id(session_id: str) -> str:
    normalized = str(session_id or "").strip()
    if not normalized.startswith("drive_upload_") or "/" in normalized or "\\" in normalized or ".." in normalized:
        raise StorageValidationError("drive_upload_session_id is required.", operation="drive_upload_session.status")
    return normalized


def _is_expired(record: dict[str, Any]) -> bool:
    value = str(record.get("expires_at") or "").strip()
    if not value:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) <= datetime.now(tz=UTC)
    except ValueError:
        return True


def _timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()
