"""Storage-owned state for chunked local uploads."""

from __future__ import annotations

from base64 import b64decode
import binascii
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets
from typing import Any

from errors import StorageValidationError
from inventory import upsert_file_record
from limits import LOCAL_UPLOAD_SESSION_CHUNK_BYTES, MAX_STORAGE_FILE_TRANSFER_BYTES
from store_files_paths import (
    enforce_storage_budget,
    hash_file,
    normalize_write_mode,
    prepare_write_target,
    resolve_storage_folder,
    safe_file_name,
    storage_root_for_role,
    storage_write_lock,
    write_audit_payload,
    write_confirmed,
)


LOCAL_UPLOAD_SESSIONS_DIR = "local_upload_sessions"
LOCAL_UPLOAD_SESSION_PARTS_DIR = "run/local_upload_sessions"
LOCAL_UPLOAD_SESSION_TTL_SECONDS = 24 * 60 * 60


def create_local_upload_session(
    *,
    data_root: Path,
    role: str,
    folder_relative_path: object,
    file_name: object,
    content_type: object,
    size_bytes: int,
    mode: object = "create",
    confirm: object = False,
    uploaded_root: Path,
    generated_root: Path,
) -> dict[str, Any]:
    if size_bytes < 0:
        raise StorageValidationError("size_bytes must not be negative.", operation="local_upload_session.start")
    if size_bytes > MAX_STORAGE_FILE_TRANSFER_BYTES:
        raise StorageValidationError(
            f"Local uploads are limited to {MAX_STORAGE_FILE_TRANSFER_BYTES} bytes.",
            operation="local_upload_session.start",
        )
    with storage_write_lock(data_root):
        prune_local_upload_sessions(data_root=data_root)
        write_mode = normalize_write_mode(mode, operation="local_upload_session.start")
        root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
        folder = resolve_storage_folder(
            role=role,
            relative_path=folder_relative_path,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
        requested_target = (folder / safe_file_name(file_name)).resolve()
        target = prepare_write_target(
            root=root,
            requested_target=requested_target,
            mode=write_mode,
            operation="local_upload_session.start",
            confirm=confirm,
        )
        reserved_bytes = _active_session_reserved_bytes(data_root=data_root)
        _enforce_reserved_upload_budget(
            uploaded_root=uploaded_root,
            generated_root=generated_root,
            target=target,
            payload_size=size_bytes,
            reserved_bytes=reserved_bytes,
            operation="local_upload_session.start",
        )
        session_id = f"local_upload_{secrets.token_hex(16)}"
        part_path = _part_path(data_root, session_id)
        part_path.parent.mkdir(parents=True, exist_ok=True)
        part_path.write_bytes(b"")
        record = {
            "schema_version": "1",
            "id": session_id,
            "status": "uploading",
            "provider": "local",
            "role": role,
            "mode": write_mode,
            "confirm": write_confirmed(confirm),
            "folder_relative_path": "" if folder == root else folder.relative_to(root).as_posix(),
            "requested_relative_path": requested_target.relative_to(root).as_posix(),
            "relative_path": target.relative_to(root).as_posix(),
            "file_name": target.name,
            "content_type": str(content_type or "application/octet-stream").strip() or "application/octet-stream",
            "size_bytes": size_bytes,
            "bytes_uploaded": 0,
            "error": "",
            "file": None,
            "created_at": _timestamp(),
            "updated_at": _timestamp(),
            "expires_at": (datetime.now(tz=UTC) + timedelta(seconds=LOCAL_UPLOAD_SESSION_TTL_SECONDS)).isoformat(),
        }
        try:
            _write_session(data_root, record)
        except Exception:
            part_path.unlink(missing_ok=True)
            raise
        return public_local_upload_session(record)


def get_local_upload_session(*, data_root: Path, session_id: str) -> dict[str, Any]:
    record = _read_session(data_root, session_id)
    if _is_expired(record):
        _remove_session_files(data_root, session_id)
        raise StorageValidationError("Local upload session has expired. Start the upload again.", operation="local_upload_session.status")
    return record


def cancel_local_upload_session(*, data_root: Path, session_id: str) -> dict[str, Any]:
    with storage_write_lock(data_root):
        record = get_local_upload_session(data_root=data_root, session_id=session_id)
        updated = {**record, "status": "canceled", "error": "", "updated_at": _timestamp()}
        _write_session(data_root, updated)
        _part_path(data_root, session_id).unlink(missing_ok=True)
        return public_local_upload_session(updated)


def append_local_upload_chunk(
    *,
    data_root: Path,
    session_id: str,
    chunk_offset: int,
    content_base64: object,
    uploaded_root: Path,
    generated_root: Path,
) -> dict[str, Any]:
    if chunk_offset < 0:
        raise StorageValidationError("chunk_offset must not be negative.", operation="local_upload_session.chunk")
    chunk = _decode_chunk(content_base64)
    if len(chunk) > LOCAL_UPLOAD_SESSION_CHUNK_BYTES:
        raise StorageValidationError(
            f"Local upload chunks are limited to {LOCAL_UPLOAD_SESSION_CHUNK_BYTES} bytes.",
            operation="local_upload_session.chunk",
        )
    with storage_write_lock(data_root):
        session = get_local_upload_session(data_root=data_root, session_id=session_id)
        status = str(session.get("status") or "")
        if status == "complete":
            return {
                "status": "uploaded",
                "provider": "local",
                "upload_session": public_local_upload_session(session),
                "file": session.get("file"),
                "audit": session.get("audit", {}),
            }
        if status == "canceled":
            raise StorageValidationError("Local upload session was canceled.", operation="local_upload_session.chunk")
        expected_offset = int(session.get("bytes_uploaded") or 0)
        if chunk_offset < expected_offset:
            return {
                "status": "uploading",
                "provider": "local",
                "upload_session": public_local_upload_session(session),
                "expected_offset": expected_offset,
            }
        if chunk_offset > expected_offset:
            raise StorageValidationError(
                "Local upload chunk offset is ahead of the current session offset.",
                operation="local_upload_session.chunk",
            )
        total_size = int(session.get("size_bytes") or 0)
        next_offset = chunk_offset + len(chunk)
        if next_offset > total_size:
            raise StorageValidationError("Local upload chunk exceeds declared size.", operation="local_upload_session.chunk")
        part_path = _part_path(data_root, session_id)
        if part_path.exists() and part_path.stat().st_size != expected_offset:
            raise StorageValidationError("Local upload session bytes are inconsistent. Restart the upload.", operation="local_upload_session.chunk")
        part_path.parent.mkdir(parents=True, exist_ok=True)
        with part_path.open("ab") as handle:
            handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if next_offset < total_size:
            updated = _update_session(data_root, session, {"bytes_uploaded": next_offset, "status": "uploading", "error": ""})
            return {
                "status": "uploading",
                "provider": "local",
                "upload_session": public_local_upload_session(updated),
                "expected_offset": next_offset,
            }
        completed = _complete_upload(
            data_root=data_root,
            session=session,
            part_path=part_path,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
        return {
            "status": "uploaded",
            "provider": "local",
            "upload_session": public_local_upload_session(completed),
            "file": completed["file"],
            "audit": completed.get("audit", {}),
        }


def public_local_upload_session(record: dict[str, Any]) -> dict[str, Any]:
    public = dict(record)
    total = int(public.get("size_bytes") or 0)
    uploaded = int(public.get("bytes_uploaded") or 0)
    public["progress"] = {
        "state": "complete" if public.get("status") == "complete" else str(public.get("status") or "uploading"),
        "bytes_completed": uploaded,
        "bytes_total": total,
    }
    return public


def prune_local_upload_sessions(*, data_root: Path) -> None:
    root = data_root / LOCAL_UPLOAD_SESSIONS_DIR
    if not root.exists():
        return
    for path in root.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            _remove_session_files(data_root, path.stem)
            continue
        if not isinstance(record, dict) or _is_expired(record):
            _remove_session_files(data_root, str(record.get("id") or path.stem))


def _complete_upload(
    *,
    data_root: Path,
    session: dict[str, Any],
    part_path: Path,
    uploaded_root: Path,
    generated_root: Path,
) -> dict[str, Any]:
    role = str(session.get("role") or "")
    relative_path = str(session.get("requested_relative_path") or session.get("relative_path") or "")
    write_mode = str(session.get("mode") or "create")
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    requested_target = (root / relative_path).resolve()
    target = prepare_write_target(
        root=root,
        requested_target=requested_target,
        mode=write_mode,
        operation="local_upload_session.chunk",
        confirm=bool(session.get("confirm")),
    )
    if part_path.stat().st_size != int(session.get("size_bytes") or 0):
        raise StorageValidationError("Local upload session did not receive the declared number of bytes.", operation="local_upload_session.chunk")
    reserved_bytes = _active_session_reserved_bytes(data_root=data_root, exclude_session_id=str(session.get("id") or ""))
    _enforce_reserved_upload_budget(
        uploaded_root=uploaded_root,
        generated_root=generated_root,
        target=target,
        payload_size=part_path.stat().st_size,
        reserved_bytes=reserved_bytes,
        operation="local_upload_session.chunk",
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    previous_path = requested_target if requested_target.exists() and requested_target.is_file() else None
    previous_sha256 = hash_file(previous_path) if previous_path else ""
    sha256 = _hash_file(part_path)
    part_path.replace(target)
    record = upsert_file_record(data_root=data_root, role=role, root=root, path=target, sha256=sha256)
    audit = write_audit_payload(
        operation="local_upload_session.complete",
        requested_mode=write_mode,
        role=role,
        root=root,
        requested_target=requested_target,
        target=target,
        previous_sha256=previous_sha256,
        sha256=sha256,
        bytes_written=int(session.get("size_bytes") or 0),
    )
    return _update_session(
        data_root,
        session,
        {
            "status": "complete",
            "bytes_uploaded": int(session.get("size_bytes") or 0),
            "error": "",
            "file": record,
            "relative_path": record["relative_path"],
            "file_name": record["name"],
            "audit": audit,
        },
    )


def _decode_chunk(content_base64: object) -> bytes:
    if content_base64 is None:
        raise StorageValidationError("content_base64 is required.", operation="local_upload_session.chunk")
    try:
        chunk = b64decode(str(content_base64), validate=True)
    except (ValueError, binascii.Error) as error:
        raise StorageValidationError("content_base64 must be valid base64.", operation="local_upload_session.chunk") from error
    if not chunk:
        raise StorageValidationError("content_base64 chunk must not be empty.", operation="local_upload_session.chunk")
    return chunk


def _active_session_reserved_bytes(*, data_root: Path, exclude_session_id: str = "") -> int:
    root = data_root / LOCAL_UPLOAD_SESSIONS_DIR
    if not root.exists():
        return 0
    excluded = str(exclude_session_id or "").strip()
    total = 0
    for path in root.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        if str(record.get("id") or path.stem) == excluded:
            continue
        if str(record.get("status") or "") != "uploading" or _is_expired(record):
            continue
        try:
            size_bytes = int(record.get("size_bytes") or 0)
        except (TypeError, ValueError):
            size_bytes = 0
        try:
            uploaded_bytes = int(record.get("bytes_uploaded") or 0)
        except (TypeError, ValueError):
            uploaded_bytes = 0
        total += max(0, size_bytes, uploaded_bytes)
    return total


def _enforce_reserved_upload_budget(
    *,
    uploaded_root: Path,
    generated_root: Path,
    target: Path,
    payload_size: int,
    reserved_bytes: int,
    operation: str,
) -> None:
    try:
        enforce_storage_budget(
            uploaded_root=uploaded_root,
            generated_root=generated_root,
            target=target,
            payload_size=max(0, payload_size) + max(0, reserved_bytes),
        )
    except StorageValidationError as error:
        raise StorageValidationError(error.detail, operation=operation) from error


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _update_session(data_root: Path, record: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    updated = {**record, **updates, "updated_at": _timestamp()}
    _write_session(data_root, updated)
    return updated


def _read_session(data_root: Path, session_id: str) -> dict[str, Any]:
    session_id = _required_session_id(session_id)
    path = _session_path(data_root, session_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise StorageValidationError("Local upload session was not found.", operation="local_upload_session.status") from error
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise StorageValidationError("Local upload session metadata is not readable.", operation="local_upload_session.status") from error
    if not isinstance(payload, dict):
        raise StorageValidationError("Local upload session metadata is invalid.", operation="local_upload_session.status")
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
    return data_root / LOCAL_UPLOAD_SESSIONS_DIR / f"{_required_session_id(session_id)}.json"


def _part_path(data_root: Path, session_id: str) -> Path:
    return data_root / LOCAL_UPLOAD_SESSION_PARTS_DIR / f"{_required_session_id(session_id)}.part"


def _remove_session_files(data_root: Path, session_id: str) -> None:
    try:
        normalized = _required_session_id(session_id)
    except StorageValidationError:
        normalized = Path(str(session_id or "")).name
    (data_root / LOCAL_UPLOAD_SESSIONS_DIR / f"{normalized}.json").unlink(missing_ok=True)
    (data_root / LOCAL_UPLOAD_SESSION_PARTS_DIR / f"{normalized}.part").unlink(missing_ok=True)


def _required_session_id(session_id: str) -> str:
    normalized = str(session_id or "").strip()
    if not normalized.startswith("local_upload_") or "/" in normalized or "\\" in normalized or ".." in normalized:
        raise StorageValidationError("local_upload_session_id is required.", operation="local_upload_session.status")
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
