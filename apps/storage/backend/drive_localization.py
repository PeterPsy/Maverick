"""Google Drive file localization and media stream helpers for Storage."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from typing import Any
from urllib.parse import quote, urlencode

from drive_oauth import GOOGLE_DRIVE_CLIENT_ID_SECRET, GOOGLE_DRIVE_CLIENT_SECRET_SECRET, GOOGLE_DRIVE_REFRESH_TOKEN_SECRET
from errors import StorageValidationError
from google_drive_provider import DriveProviderError, GoogleDriveProvider
from storage_provider_model import GOOGLE_DRIVE_PROVIDER


DRIVE_LOCAL_CACHE_DIR = "drive_local_cache"
DRIVE_LOCALIZATION_SCHEMA_VERSION = "1"
DRIVE_LOCALIZE_MAX_BYTES = 2 * 1024 * 1024 * 1024
DRIVE_LOCAL_CACHE_MAX_BYTES = 4 * 1024 * 1024 * 1024
DRIVE_LOCAL_CACHE_MIN_FREE_BYTES = 512 * 1024 * 1024
DRIVE_LOCAL_CACHE_TTL_SECONDS = 14 * 24 * 60 * 60
DRIVE_MEDIA_RANGE_MAX_BYTES = 8 * 1024 * 1024
DRIVE_MEDIA_RANGE_TTL_SECONDS = 60 * 60
STREAMABLE_PREVIEW_KINDS = {"image", "video", "audio", "pdf"}


def localize_drive_file_payload(
    *,
    data_root: Path,
    provider: GoogleDriveProvider,
    connection_id: str,
    drive_file_id: str,
    file_record: dict[str, Any] | None,
    app_id: str,
    max_bytes: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Ensure one Drive binary file is present in Storage's workspace-governed local cache."""
    operation = "file.localize"
    resolved_record = _active_drive_record(provider, drive_file_id=drive_file_id, file_record=file_record, operation=operation)
    if str(resolved_record.get("preview_kind") or "") not in STREAMABLE_PREVIEW_KINDS:
        raise StorageValidationError(
            "Only browser-streamable Drive image, video, audio, and PDF files can be localized for media playback.",
            operation=operation,
            allowed_values={"preview_kind": sorted(STREAMABLE_PREVIEW_KINDS)},
        )
    if connection_id and str(resolved_record.get("connection_id") or "") != connection_id:
        raise StorageValidationError("Google Drive Storage reference does not belong to the requested connection.", operation=operation)
    max_download_bytes = _max_download_bytes(resolved_record, max_bytes=max_bytes, operation=operation)
    target = _target_for_record(data_root=data_root, file_record=resolved_record)
    cleanup_drive_local_cache(data_root=data_root, current_file_record=resolved_record, keep_localization_id=target.localization_id)
    cached = _read_localization_metadata(target)
    if cached and not force and _cache_file_is_ready(target, cached, file_record=resolved_record):
        return _localization_payload(
            app_id=app_id,
            target=target,
            file_record=resolved_record,
            metadata={**cached, "cache_hit": True},
        )

    _ensure_cache_write_budget(data_root=data_root, target=target, incoming_bytes=max_download_bytes, operation=operation, replace_target=True)
    _ensure_disk_space(target.directory, incoming_bytes=max_download_bytes, operation=operation)
    target.directory.mkdir(parents=True, exist_ok=True)
    metadata = _pending_metadata(file_record=resolved_record, localization_id=target.localization_id)
    _atomic_write_json(target.metadata_path, metadata)
    temporary_path = target.content_path.with_name(f".{target.content_path.name}.{os.getpid()}.tmp")
    try:
        if temporary_path.exists():
            temporary_path.unlink()
        progress_writer = _progress_metadata_writer(
            metadata_path=target.metadata_path,
            base_metadata=metadata,
        )
        downloaded_record, size_bytes, sha256, provider_cache_hit = provider.download_binary_to_path(
            drive_file_id=drive_file_id,
            max_bytes=max_download_bytes,
            operation=operation,
            target_path=temporary_path,
            file_record=resolved_record,
            progress_callback=progress_writer,
        )
        resolved_record = {**resolved_record, **downloaded_record}
        temporary_path.replace(target.content_path)
        ready = _ready_metadata(
            file_record=resolved_record,
            localization_id=target.localization_id,
            size_bytes=size_bytes,
            sha256=sha256,
            provider_cache_hit=provider_cache_hit,
        )
        _atomic_write_json(target.metadata_path, ready)
        cleanup_drive_local_cache(data_root=data_root, current_file_record=resolved_record, keep_localization_id=target.localization_id)
    except Exception as error:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        failed = {**metadata, "status": "error", "error": _safe_error(error), "updated_at": _timestamp()}
        _atomic_write_json(target.metadata_path, failed)
        raise

    return _localization_payload(
        app_id=app_id,
        target=target,
        file_record=resolved_record,
        metadata={**ready, "cache_hit": False},
    )


def drive_media_stream_response(
    *,
    data_root: Path,
    file_record: dict[str, Any],
    app_id: str,
    download: bool = False,
    provider: GoogleDriveProvider | None = None,
    localization_id: str = "",
    source_version: str = "",
    range_header: str = "",
) -> dict[str, Any]:
    """Return a core-served file response for a localized or proxied Drive file."""
    operation = "file.media_stream"
    if file_record.get("provider") != GOOGLE_DRIVE_PROVIDER:
        raise StorageValidationError("The requested file is not a Google Drive file.", operation=operation)
    target = _target_for_record(data_root=data_root, file_record=file_record)
    _validate_stream_binding(
        file_record=file_record,
        target=target,
        requested_localization_id=localization_id,
        requested_source_version=source_version,
        operation=operation,
    )
    cleanup_drive_local_cache(data_root=data_root, current_file_record=file_record, keep_localization_id=target.localization_id)
    metadata = _read_localization_metadata(target)
    if metadata and _cache_file_is_ready(target, metadata, file_record=file_record):
        localization = _localization_payload(
            app_id=app_id,
            target=target,
            file_record=file_record,
            metadata={**metadata, "cache_hit": True},
        )["localization"]
        return {
            "file": file_record,
            "localization": localization,
            "file_response": {
                "path": str(target.content_path),
                "content_type": localization["content_type"],
                "file_name": localization["file_name"],
                "etag": localization["etag"],
                "download": download,
                "cache_control": "private, max-age=60",
            },
        }
    if provider is None:
        raise StorageValidationError(
            "Google Drive file is not localized yet and cannot be proxied without Drive secret grants.",
            operation=operation,
            expected_fields=["stable_storage_file_id"],
        )
    return _drive_proxy_media_response(
        data_root=data_root,
        provider=provider,
        target=target,
        file_record=file_record,
        app_id=app_id,
        download=download,
        range_header=range_header,
    )


def stream_url_for_localization(*, app_id: str, file_record: dict[str, Any], localization_id: str, download: bool = False) -> str:
    file_id = str(file_record.get("file_id") or file_record.get("stable_storage_file_id") or file_record.get("id") or "").strip()
    query = {
        "stable_storage_file_id": file_id,
        "localization_id": localization_id,
        "source_version": _source_version(file_record),
        "_app_secret_request": json.dumps(_drive_media_secret_request(file_record), separators=(",", ":"), sort_keys=True),
    }
    if download:
        query["download"] = "1"
    return f"/api/apps/{quote(app_id or 'storage', safe='')}/media?{urlencode(query)}"


def _drive_proxy_media_response(
    *,
    data_root: Path,
    provider: GoogleDriveProvider,
    target: "LocalizedDriveTarget",
    file_record: dict[str, Any],
    app_id: str,
    download: bool,
    range_header: str,
) -> dict[str, Any]:
    operation = "file.media_stream"
    if str(file_record.get("preview_kind") or "") not in STREAMABLE_PREVIEW_KINDS:
        raise StorageValidationError(
            "Only browser-streamable Drive image, video, audio, and PDF files can be proxied through the media route.",
            operation=operation,
            allowed_values={"preview_kind": sorted(STREAMABLE_PREVIEW_KINDS)},
        )
    declared_size = int(file_record.get("size_bytes") or 0)
    if range_header:
        if not target.metadata_path.exists():
            streaming_metadata = {
                **_pending_metadata(file_record=file_record, localization_id=target.localization_id),
                "status": "localizing",
                "progress": {"state": "streaming", "bytes_completed": 0, "bytes_total": declared_size},
            }
            _atomic_write_json(target.metadata_path, streaming_metadata)
        start, end, total_size = _bounded_media_range(range_header, declared_size=declared_size, operation=operation)
        range_path = _range_content_path(target=target, start=start, end=end, total_size=total_size)
        range_metadata_path = range_path.with_suffix(".json")
        cached_range = _read_range_metadata(range_metadata_path)
        if not _range_file_is_ready(range_path, cached_range, start=start, end=end, total_size=total_size, file_record=file_record):
            cleanup_drive_local_cache(data_root=data_root, current_file_record=file_record, keep_localization_id=target.localization_id)
            _ensure_cache_write_budget(data_root=data_root, target=target, incoming_bytes=end - start + 1, operation=operation, replace_target=False)
            _ensure_disk_space(range_path.parent, incoming_bytes=end - start + 1, operation=operation)
            temporary_path = range_path.with_name(f".{range_path.name}.{os.getpid()}.tmp")
            try:
                temporary_path.unlink(missing_ok=True)
                _downloaded_record, size_bytes, sha256 = provider.download_binary_range_to_path(
                    drive_file_id=str(file_record.get("drive_file_id") or ""),
                    operation=operation,
                    target_path=temporary_path,
                    start=start,
                    end=end,
                    total_size=total_size,
                    file_record=file_record,
                )
                temporary_path.replace(range_path)
                cached_range = _range_metadata(
                    file_record=file_record,
                    start=start,
                    end=end,
                    total_size=total_size,
                    size_bytes=size_bytes,
                    sha256=sha256,
                )
                _atomic_write_json(range_metadata_path, cached_range)
            except DriveProviderError as error:
                temporary_path.unlink(missing_ok=True)
                raise StorageValidationError("Google Drive media range request failed.", operation=operation) from error
            except Exception:
                temporary_path.unlink(missing_ok=True)
                raise
        return {
            "file": file_record,
            "localization": _streaming_localization(target=target, file_record=file_record, metadata=cached_range or {}),
            "file_response": {
                "path": str(range_path),
                "content_type": str(file_record.get("content_type") or "application/octet-stream"),
                "file_name": str(file_record.get("name") or "drive-file"),
                "etag": _range_etag(target=target, start=start, end=end, source_version=_source_version(file_record)),
                "download": download,
                "cache_control": "private, max-age=60",
                "served_range": {"start": start, "end": end, "size": total_size},
            },
        }

    max_download_bytes = _max_download_bytes(file_record, max_bytes=None, operation=operation)
    _ensure_cache_write_budget(data_root=data_root, target=target, incoming_bytes=max_download_bytes, operation=operation, replace_target=True)
    _ensure_disk_space(target.directory, incoming_bytes=max_download_bytes, operation=operation)
    temporary_path = target.content_path.with_name(f".{target.content_path.name}.{os.getpid()}.tmp")
    metadata = _pending_metadata(file_record=file_record, localization_id=target.localization_id)
    _atomic_write_json(target.metadata_path, metadata)
    try:
        temporary_path.unlink(missing_ok=True)
        progress_writer = _progress_metadata_writer(metadata_path=target.metadata_path, base_metadata=metadata)
        downloaded_record, size_bytes, sha256, provider_cache_hit = provider.download_binary_to_path(
            drive_file_id=str(file_record.get("drive_file_id") or ""),
            max_bytes=max_download_bytes,
            operation=operation,
            target_path=temporary_path,
            file_record=file_record,
            progress_callback=progress_writer,
        )
        file_record = {**file_record, **downloaded_record}
        temporary_path.replace(target.content_path)
        ready = _ready_metadata(
            file_record=file_record,
            localization_id=target.localization_id,
            size_bytes=size_bytes,
            sha256=sha256,
            provider_cache_hit=provider_cache_hit,
        )
        _atomic_write_json(target.metadata_path, ready)
        cleanup_drive_local_cache(data_root=data_root, current_file_record=file_record, keep_localization_id=target.localization_id)
    except DriveProviderError as error:
        temporary_path.unlink(missing_ok=True)
        failed = {**metadata, "status": "error", "error": _safe_error(error), "updated_at": _timestamp()}
        _atomic_write_json(target.metadata_path, failed)
        raise StorageValidationError("Google Drive media stream request failed.", operation=operation) from error
    except Exception as error:
        temporary_path.unlink(missing_ok=True)
        failed = {**metadata, "status": "error", "error": _safe_error(error), "updated_at": _timestamp()}
        _atomic_write_json(target.metadata_path, failed)
        raise
    localization = _localization_payload(
        app_id=app_id,
        target=target,
        file_record=file_record,
        metadata={**ready, "cache_hit": False},
    )["localization"]
    return {
        "file": file_record,
        "localization": localization,
        "file_response": {
            "path": str(target.content_path),
            "content_type": localization["content_type"],
            "file_name": localization["file_name"],
            "etag": localization["etag"],
            "download": download,
            "cache_control": "private, max-age=60",
        },
    }


class LocalizedDriveTarget:
    def __init__(self, *, localization_id: str, directory: Path, content_path: Path, metadata_path: Path) -> None:
        self.localization_id = localization_id
        self.directory = directory
        self.content_path = content_path
        self.metadata_path = metadata_path


def _active_drive_record(
    provider: GoogleDriveProvider,
    *,
    drive_file_id: str,
    file_record: dict[str, Any] | None,
    operation: str,
) -> dict[str, Any]:
    if file_record and _source_version(file_record):
        return file_record
    return provider.metadata(drive_file_id=drive_file_id)


def _target_for_record(*, data_root: Path, file_record: dict[str, Any]) -> LocalizedDriveTarget:
    localization_id = _localization_id(file_record)
    directory = data_root / DRIVE_LOCAL_CACHE_DIR / localization_id[:2] / localization_id
    return LocalizedDriveTarget(
        localization_id=localization_id,
        directory=directory,
        content_path=directory / "content.bin",
        metadata_path=directory / "metadata.json",
    )


def _localization_id(file_record: dict[str, Any]) -> str:
    material = "\0".join(
        [
            str(file_record.get("connection_id") or ""),
            str(file_record.get("drive_file_id") or ""),
            _source_version(file_record),
            str(file_record.get("content_type") or "application/octet-stream"),
        ]
    )
    if not material.strip("\0"):
        raise StorageValidationError("Google Drive Storage reference is missing localization identity.", operation="file.localize")
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _source_version(file_record: dict[str, Any]) -> str:
    return str(file_record.get("etag_or_version") or file_record.get("source_version") or file_record.get("modified_at") or "").strip()


def _validate_stream_binding(
    *,
    file_record: dict[str, Any],
    target: LocalizedDriveTarget,
    requested_localization_id: str,
    requested_source_version: str,
    operation: str,
) -> None:
    if requested_localization_id and requested_localization_id != target.localization_id:
        raise StorageValidationError(
            "Media stream URL localization_id does not match the current Storage file record.",
            operation=operation,
            expected_fields=["stable_storage_file_id", "localization_id"],
        )
    current_source_version = _source_version(file_record)
    if requested_source_version and requested_source_version != current_source_version:
        raise StorageValidationError(
            "Media stream URL source_version is stale; refresh the Storage file record and retry.",
            operation=operation,
            expected_fields=["stable_storage_file_id", "source_version"],
        )


def _bounded_media_range(value: str, *, declared_size: int, operation: str) -> tuple[int, int, int]:
    if declared_size <= 0:
        raise StorageValidationError("Drive media Range streaming requires Drive file size metadata.", operation=operation)
    normalized = str(value or "").strip()
    if not normalized.startswith("bytes=") or "," in normalized:
        raise StorageValidationError("Drive media supports exactly one byte range.", operation=operation)
    spec = normalized.removeprefix("bytes=").strip()
    start_text, separator, end_text = spec.partition("-")
    if not separator:
        raise StorageValidationError("Drive media Range header is invalid.", operation=operation)
    try:
        if start_text:
            start = int(start_text)
            requested_end = int(end_text) if end_text else declared_size - 1
        else:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                raise ValueError
            start = max(0, declared_size - suffix_length)
            requested_end = declared_size - 1
    except ValueError as error:
        raise StorageValidationError("Drive media Range header is invalid.", operation=operation) from error
    if start < 0 or start >= declared_size:
        raise StorageValidationError("Drive media Range header is not satisfiable for this file.", operation=operation)
    requested_end = min(requested_end, declared_size - 1)
    if requested_end < start:
        raise StorageValidationError("Drive media Range header is invalid.", operation=operation)
    end = min(requested_end, start + DRIVE_MEDIA_RANGE_MAX_BYTES - 1)
    return start, end, declared_size


def _range_content_path(*, target: LocalizedDriveTarget, start: int, end: int, total_size: int) -> Path:
    material = f"{target.localization_id}\0{start}\0{end}\0{total_size}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return target.directory / "ranges" / f"{digest}.bin"


def _range_etag(*, target: LocalizedDriveTarget, start: int, end: int, source_version: str) -> str:
    digest = hashlib.sha256(f"{target.localization_id}\0{start}\0{end}\0{source_version}".encode("utf-8")).hexdigest()
    return f"drive-range-{digest[:32]}"


def _range_metadata(
    *,
    file_record: dict[str, Any],
    start: int,
    end: int,
    total_size: int,
    size_bytes: int,
    sha256: str,
) -> dict[str, Any]:
    now = _timestamp()
    return {
        "schema_version": DRIVE_LOCALIZATION_SCHEMA_VERSION,
        "status": "ready",
        "provider": GOOGLE_DRIVE_PROVIDER,
        "stable_storage_file_id": str(file_record.get("file_id") or file_record.get("stable_storage_file_id") or file_record.get("id") or ""),
        "connection_id": str(file_record.get("connection_id") or ""),
        "drive_file_id": str(file_record.get("drive_file_id") or ""),
        "source_version": _source_version(file_record),
        "content_type": str(file_record.get("content_type") or "application/octet-stream"),
        "file_name": str(file_record.get("name") or "drive-file"),
        "start": start,
        "end": end,
        "total_size": total_size,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "created_at": now,
        "updated_at": now,
    }


def _read_range_metadata(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _range_file_is_ready(
    path: Path,
    metadata: dict[str, Any] | None,
    *,
    start: int,
    end: int,
    total_size: int,
    file_record: dict[str, Any],
) -> bool:
    if not metadata or metadata.get("status") != "ready" or not path.is_file():
        return False
    return (
        int(metadata.get("start") or -1) == start
        and int(metadata.get("end") or -1) == end
        and int(metadata.get("total_size") or -1) == total_size
        and int(metadata.get("size_bytes") or -1) == path.stat().st_size
        and str(metadata.get("source_version") or "") == _source_version(file_record)
    )


def _streaming_localization(*, target: LocalizedDriveTarget, file_record: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    size_bytes = int(metadata.get("size_bytes") or 0)
    total_size = int(metadata.get("total_size") or file_record.get("size_bytes") or 0)
    return {
        "id": target.localization_id,
        "status": "localizing",
        "source_version": metadata.get("source_version") or _source_version(file_record),
        "content_type": metadata.get("content_type") or file_record.get("content_type") or "application/octet-stream",
        "file_name": metadata.get("file_name") or file_record.get("name") or "drive-file",
        "size_bytes": total_size,
        "sha256": metadata.get("sha256") or "",
        "etag": _range_etag(
            target=target,
            start=int(metadata.get("start") or 0),
            end=int(metadata.get("end") or max(0, size_bytes - 1)),
            source_version=_source_version(file_record),
        ),
        "progress": {"state": "streaming", "bytes_completed": size_bytes, "bytes_total": total_size},
        "retry_count": 0,
        "cache_hit": bool(metadata),
        "created_at": metadata.get("created_at") or "",
        "updated_at": metadata.get("updated_at") or "",
    }


def _drive_media_secret_request(file_record: dict[str, Any]) -> dict[str, Any]:
    connection_id = str(file_record.get("connection_id") or "").strip()
    selectors: list[dict[str, Any]] = [{"logical_names": [GOOGLE_DRIVE_CLIENT_ID_SECRET, GOOGLE_DRIVE_CLIENT_SECRET_SECRET]}]
    if connection_id:
        selectors.append(
            {
                "logical_names": [GOOGLE_DRIVE_REFRESH_TOKEN_SECRET],
                "resource_type": "drive_connection",
                "resource_id": connection_id,
            }
        )
    return {
        "required": True,
        "selectors": selectors,
    }


def _max_download_bytes(file_record: dict[str, Any], *, max_bytes: int | None, operation: str) -> int:
    declared_size = int(file_record.get("size_bytes") or 0)
    budget = max_bytes or declared_size or DRIVE_LOCALIZE_MAX_BYTES
    if budget > DRIVE_LOCALIZE_MAX_BYTES:
        raise StorageValidationError(
            f"Drive localization is limited to {DRIVE_LOCALIZE_MAX_BYTES} bytes per request.",
            operation=operation,
            allowed_values={"max_bytes": [str(DRIVE_LOCALIZE_MAX_BYTES)]},
        )
    return budget


def _pending_metadata(*, file_record: dict[str, Any], localization_id: str) -> dict[str, Any]:
    return {
        "schema_version": DRIVE_LOCALIZATION_SCHEMA_VERSION,
        "id": localization_id,
        "status": "localizing",
        "provider": GOOGLE_DRIVE_PROVIDER,
        "connection_id": str(file_record.get("connection_id") or ""),
        "drive_file_id": str(file_record.get("drive_file_id") or ""),
        "stable_storage_file_id": str(file_record.get("file_id") or file_record.get("stable_storage_file_id") or file_record.get("id") or ""),
        "source_version": _source_version(file_record),
        "content_type": str(file_record.get("content_type") or "application/octet-stream"),
        "file_name": str(file_record.get("name") or "drive-file"),
        "size_bytes": int(file_record.get("size_bytes") or 0),
        "sha256": "",
        "etag": "",
        "progress": {"state": "localizing", "bytes_completed": 0, "bytes_total": int(file_record.get("size_bytes") or 0)},
        "retry_count": 0,
        "error": "",
        "created_at": _timestamp(),
        "updated_at": _timestamp(),
    }


def _ready_metadata(
    *,
    file_record: dict[str, Any],
    localization_id: str,
    size_bytes: int,
    sha256: str,
    provider_cache_hit: bool,
) -> dict[str, Any]:
    now = _timestamp()
    return {
        **_pending_metadata(file_record=file_record, localization_id=localization_id),
        "status": "ready",
        "size_bytes": size_bytes,
        "sha256": sha256,
        "etag": f"drive-local-{localization_id[:24]}-{sha256[:16]}",
        "progress": {"state": "complete", "bytes_completed": size_bytes, "bytes_total": size_bytes},
        "provider_cache_hit": provider_cache_hit,
        "error": "",
        "created_at": now,
        "updated_at": now,
    }


def _localization_payload(
    *,
    app_id: str,
    target: LocalizedDriveTarget,
    file_record: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    stream_url = stream_url_for_localization(app_id=app_id, file_record=file_record, localization_id=target.localization_id)
    download_url = stream_url_for_localization(app_id=app_id, file_record=file_record, localization_id=target.localization_id, download=True)
    payload = {
        "status": "ready",
        "provider": GOOGLE_DRIVE_PROVIDER,
        "connection_id": str(file_record.get("connection_id") or ""),
        "drive_file_id": str(file_record.get("drive_file_id") or ""),
        "stable_storage_file_id": str(file_record.get("file_id") or file_record.get("stable_storage_file_id") or file_record.get("id") or ""),
        "file": file_record,
        "localization": {
            "id": target.localization_id,
            "status": metadata.get("status") or "ready",
            "source_version": metadata.get("source_version") or _source_version(file_record),
            "content_type": metadata.get("content_type") or file_record.get("content_type") or "application/octet-stream",
            "file_name": metadata.get("file_name") or file_record.get("name") or "drive-file",
            "size_bytes": int(metadata.get("size_bytes") or 0),
            "sha256": metadata.get("sha256") or "",
            "etag": metadata.get("etag") or "",
            "progress": metadata.get("progress") if isinstance(metadata.get("progress"), dict) else {},
            "retry_count": int(metadata.get("retry_count") or 0),
            "cache_hit": bool(metadata.get("cache_hit")),
            "created_at": metadata.get("created_at") or "",
            "updated_at": metadata.get("updated_at") or "",
        },
        "stream_url": stream_url,
        "download_url": download_url,
    }
    return payload


def _read_localization_metadata(target: LocalizedDriveTarget) -> dict[str, Any] | None:
    try:
        payload = json.loads(target.metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _cache_file_is_ready(target: LocalizedDriveTarget, metadata: dict[str, Any], *, file_record: dict[str, Any] | None = None) -> bool:
    if metadata.get("status") != "ready" or metadata.get("id") != target.localization_id or not target.content_path.is_file():
        return False
    if int(metadata.get("size_bytes") or -1) != target.content_path.stat().st_size:
        return False
    if file_record is None:
        return True
    stable_id = str(file_record.get("file_id") or file_record.get("stable_storage_file_id") or file_record.get("id") or "")
    return (
        str(metadata.get("stable_storage_file_id") or "") == stable_id
        and str(metadata.get("source_version") or "") == _source_version(file_record)
        and str(metadata.get("content_type") or "") == str(file_record.get("content_type") or "application/octet-stream")
    )


def cleanup_drive_local_cache(
    *,
    data_root: Path,
    current_file_record: dict[str, Any] | None = None,
    keep_localization_id: str = "",
) -> None:
    cache_root = data_root / DRIVE_LOCAL_CACHE_DIR
    if not cache_root.exists():
        return
    now = time.time()
    entries: list[tuple[float, int, str, Path]] = []
    for metadata_path in cache_root.glob("*/*/metadata.json"):
        directory = metadata_path.parent
        metadata = _read_json_file(metadata_path)
        localization_id = str(metadata.get("id") or directory.name)
        _cleanup_range_files(directory / "ranges", now=now)
        if _cache_entry_should_be_removed(
            directory=directory,
            metadata=metadata,
            current_file_record=current_file_record,
            keep_localization_id=keep_localization_id,
            now=now,
        ):
            shutil.rmtree(directory, ignore_errors=True)
            continue
        entries.append((_metadata_sort_time(metadata, metadata_path), _directory_size(directory), localization_id, directory))
    total_bytes = sum(size for _updated_at, size, _localization_id, _directory in entries)
    for _updated_at, size, localization_id, directory in sorted(entries):
        if total_bytes <= DRIVE_LOCAL_CACHE_MAX_BYTES:
            break
        if localization_id == keep_localization_id:
            continue
        shutil.rmtree(directory, ignore_errors=True)
        total_bytes -= size


def _ensure_cache_write_budget(
    *,
    data_root: Path,
    target: LocalizedDriveTarget,
    incoming_bytes: int,
    operation: str,
    replace_target: bool,
) -> None:
    if incoming_bytes > DRIVE_LOCAL_CACHE_MAX_BYTES:
        raise StorageValidationError(
            f"Drive local cache budget is {DRIVE_LOCAL_CACHE_MAX_BYTES} bytes; requested media is too large to cache.",
            operation=operation,
            allowed_values={"cache_max_bytes": [str(DRIVE_LOCAL_CACHE_MAX_BYTES)]},
        )
    cleanup_drive_local_cache(data_root=data_root, keep_localization_id=target.localization_id)
    cache_root = data_root / DRIVE_LOCAL_CACHE_DIR
    current_size = _directory_size(target.directory) if replace_target and target.directory.exists() else 0
    projected_size = max(0, _directory_size(cache_root) - current_size) + incoming_bytes
    if projected_size > DRIVE_LOCAL_CACHE_MAX_BYTES:
        cleanup_drive_local_cache(data_root=data_root, keep_localization_id=target.localization_id)
        projected_size = max(0, _directory_size(cache_root) - current_size) + incoming_bytes
    if projected_size > DRIVE_LOCAL_CACHE_MAX_BYTES:
        raise StorageValidationError(
            "Drive local cache does not have enough budget for this media file after eviction.",
            operation=operation,
            allowed_values={"cache_max_bytes": [str(DRIVE_LOCAL_CACHE_MAX_BYTES)]},
        )


def _ensure_disk_space(directory: Path, *, incoming_bytes: int, operation: str) -> None:
    probe = directory
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    if usage.free - incoming_bytes < DRIVE_LOCAL_CACHE_MIN_FREE_BYTES:
        raise StorageValidationError(
            "Drive local cache does not have enough free disk space for this media file.",
            operation=operation,
            allowed_values={"min_free_bytes": [str(DRIVE_LOCAL_CACHE_MIN_FREE_BYTES)]},
        )


def _cache_entry_should_be_removed(
    *,
    directory: Path,
    metadata: dict[str, Any],
    current_file_record: dict[str, Any] | None,
    keep_localization_id: str,
    now: float,
) -> bool:
    localization_id = str(metadata.get("id") or directory.name)
    if localization_id == keep_localization_id:
        return False
    content_path = directory / "content.bin"
    if metadata.get("status") == "ready" and (not content_path.is_file() or int(metadata.get("size_bytes") or -1) != content_path.stat().st_size):
        return True
    if now - _metadata_sort_time(metadata, directory / "metadata.json") > DRIVE_LOCAL_CACHE_TTL_SECONDS:
        return True
    if current_file_record is None:
        return False
    stable_id = str(current_file_record.get("file_id") or current_file_record.get("stable_storage_file_id") or current_file_record.get("id") or "")
    if stable_id and str(metadata.get("stable_storage_file_id") or "") == stable_id:
        return str(metadata.get("source_version") or "") != _source_version(current_file_record)
    return False


def _cleanup_range_files(range_root: Path, *, now: float) -> None:
    if not range_root.exists():
        return
    for path in range_root.iterdir():
        if not path.is_file():
            continue
        try:
            if now - path.stat().st_mtime > DRIVE_MEDIA_RANGE_TTL_SECONDS:
                path.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        if not any(range_root.iterdir()):
            range_root.rmdir()
    except OSError:
        pass


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def _metadata_sort_time(metadata: dict[str, Any], path: Path) -> float:
    for key in ("updated_at", "created_at"):
        value = str(metadata.get(key) or "").strip()
        if not value:
            continue
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary_path.replace(path)


def _progress_metadata_writer(*, metadata_path: Path, base_metadata: dict[str, Any]):
    last_update = {"at": 0.0}

    def write_progress(bytes_completed: int, bytes_total: int) -> None:
        now = time.monotonic()
        if bytes_completed < bytes_total and now - last_update["at"] < 1.0:
            return
        last_update["at"] = now
        _atomic_write_json(
            metadata_path,
            {
                **base_metadata,
                "progress": {
                    "state": "localizing",
                    "bytes_completed": bytes_completed,
                    "bytes_total": bytes_total,
                },
                "updated_at": _timestamp(),
            },
        )

    return write_progress


def _safe_error(error: Exception) -> str:
    text = str(error)
    lowered = text.lower()
    if any(marker in lowered for marker in ("secret", "token", "authorization", "client")):
        return error.__class__.__name__
    return text[:300]


def _timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()
