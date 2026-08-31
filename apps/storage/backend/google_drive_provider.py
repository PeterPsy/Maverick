"""Google Drive remote provider for Storage."""

from __future__ import annotations

from base64 import b64decode, b64encode
from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from drive_oauth import (
    GOOGLE_DRIVE_CLIENT_ID_SECRET,
    GOOGLE_DRIVE_CLIENT_SECRET_SECRET,
    GOOGLE_DRIVE_REFRESH_TOKEN_SECRET,
    GOOGLE_TOKEN_URL,
    default_transport,
)
from errors import StorageValidationError
from inventory import preview_kind
from storage_provider_model import GOOGLE_DRIVE_PROVIDER, normalize_capabilities
from storage_mime import normalize_content_type


DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API_BASE = "https://www.googleapis.com/upload/drive/v3"
DRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
SHARED_WITH_ME_ROOT_ID = "sharedWithMe"
MAX_DRIVE_PAGE_SIZE = 2000
MAX_DRIVE_QUERY_CHARS = 500
GOOGLE_EXPORT_LIMIT_BYTES = 10 * 1024 * 1024
DRIVE_TEMP_CACHE_TTL_SECONDS = 15 * 60
DRIVE_TEMP_CACHE_MAX_BYTES = 32 * 1024 * 1024
DRIVE_TEMP_CACHE_MAX_ITEM_BYTES = GOOGLE_EXPORT_LIMIT_BYTES
DRIVE_ACCESS_TOKEN_CACHE_TTL_SECONDS = 5 * 60
DRIVE_ACCESS_TOKEN_EXPIRY_SKEW_SECONDS = 30
DRIVE_STREAM_CHUNK_BYTES = 1024 * 1024
DRIVE_RESUMABLE_CHUNK_BYTES = 8 * 1024 * 1024

GOOGLE_NATIVE_PREVIEW_KINDS = {
    "application/vnd.google-apps.document": "document",
    "application/vnd.google-apps.spreadsheet": "spreadsheet",
    "application/vnd.google-apps.presentation": "presentation",
    "application/vnd.google-apps.drawing": "image",
}

GOOGLE_NATIVE_EXPORTS = {
    "application/vnd.google-apps.document": {
        "readable_text": "text/plain",
        "preview": "text/plain",
        "text": "text/plain",
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
    "application/vnd.google-apps.spreadsheet": {
        "readable_text": "text/csv",
        "preview": "text/csv",
        "text": "text/csv",
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pdf": "application/pdf",
    },
    "application/vnd.google-apps.presentation": {
        "readable_text": "text/plain",
        "preview": "text/plain",
        "text": "text/plain",
        "pdf": "application/pdf",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    },
}

DRIVE_FILE_FIELDS = (
    "id,name,mimeType,trashed,explicitlyTrashed,parents,driveId,webViewLink,iconLink,"
    "size,modifiedTime,createdTime,md5Checksum,version,headRevisionId,capabilities("
    "canDownload,canEdit,canModifyContent,canRename,canMoveItemWithinDrive,"
    "canMoveItemOutOfDrive,canMoveChildrenWithinDrive,canAddChildren,canDelete,canTrash),shared,ownedByMe"
)
DRIVE_CHANGE_FIELDS = f"nextPageToken,newStartPageToken,changes(fileId,removed,file({DRIVE_FILE_FIELDS}))"

HttpTransport = Callable[[str, str, dict[str, Any]], tuple[int, dict[str, Any] | bytes]]


@dataclass(frozen=True)
class DriveProviderError(Exception):
    """HTTP-level Drive API failure."""

    status_code: int
    detail: str


@dataclass
class PreparedDriveBinaryStream:
    """One Drive media response opened before HTTP streaming headers are emitted."""

    file_record: dict[str, Any]
    target_path: Path
    declared_size: int
    max_bytes: int
    operation: str
    provider_cache_hit: bool = False
    payload: bytes | None = None
    response: Any | None = None
    handle: BinaryIO | None = None
    first_chunk: bytes = b""

    def close(self) -> None:
        if self.response is not None:
            self.response.close()
            self.response = None
        if self.handle is not None:
            self.handle.close()
            self.handle = None


class GoogleDriveProvider:
    """Storage-owned Google Drive provider using Vault-delivered secrets only."""

    def __init__(
        self,
        *,
        connection: dict[str, Any],
        app_secrets: dict[str, object],
        transport: HttpTransport | None = None,
        cache_root: Path | None = None,
    ) -> None:
        self.connection = connection
        self.connection_id = str(connection.get("id") or connection.get("connection_id") or "").strip()
        if not self.connection_id:
            raise StorageValidationError("connection_id is required.", operation="drive")
        if str(connection.get("status") or "") != "connected":
            raise StorageValidationError("Drive connection is not connected.", operation="drive")
        self.app_secrets = app_secrets
        self.transport = transport or default_transport
        self.cache_root = cache_root
        self._access_token: str | None = None

    def list_roots(self, *, limit: int | None = None, page_token: str | None = None) -> dict[str, Any]:
        current_token = str(page_token or "").strip()
        roots = [
            self._root_folder(
                drive_file_id="root",
                name="My Drive",
                display_path="/My Drive",
                root_kind="my_drive",
                capabilities={"can_read": True},
            ),
            self._root_folder(
                drive_file_id=SHARED_WITH_ME_ROOT_ID,
                name="Shared with me",
                display_path="/Shared with me",
                root_kind="shared_with_me",
                capabilities={"can_read": True},
            ),
        ]
        page_size = _bounded_limit(limit, default=100)
        static_roots = [] if current_token else roots
        shared_drive_page_size = min(page_size, 100)
        next_page_token = ""
        try:
            params: dict[str, Any] = {
                "pageSize": shared_drive_page_size,
                "fields": "nextPageToken,drives(id,name,capabilities(canDeleteDrive,canRenameDrive))",
            }
            if current_token:
                params["pageToken"] = current_token
            payload = self._drive_request(
                "GET",
                "/drives",
                params=params,
            )
            next_page_token = str(payload.get("nextPageToken") or "")
        except DriveProviderError as error:
            if error.status_code in {400, 403, 404}:
                payload = {"drives": []}
            else:
                raise
        shared_roots: list[dict[str, Any]] = []
        for drive in payload.get("drives") if isinstance(payload.get("drives"), list) else []:
            if not isinstance(drive, dict):
                continue
            drive_id = str(drive.get("id") or "").strip()
            name = str(drive.get("name") or "Shared drive").strip()
            if not drive_id:
                continue
            shared_roots.append(
                self._root_folder(
                    drive_file_id=drive_id,
                    name=name,
                    display_path=f"/Shared drives/{name}",
                    root_kind="shared_drive",
                    capabilities={"can_read": True, "can_move": True},
                )
            )
        folders = static_roots + shared_roots
        return {
            "provider": GOOGLE_DRIVE_PROVIDER,
            "connection_id": self.connection_id,
            "folders": folders,
            "pagination": {"limit": page_size, "total": len(folders), "has_more": bool(next_page_token), "next_page_token": next_page_token},
        }

    def list_children(self, *, parent_drive_file_id: str, limit: int | None = None, page_token: str | None = None) -> dict[str, Any]:
        parent_id = _required_drive_file_id(parent_drive_file_id, operation="drive_list_children")
        page_size = _bounded_limit(limit)
        parent_display_path, list_scope, breadcrumbs = self._parent_list_context(parent_id)
        if parent_id == SHARED_WITH_ME_ROOT_ID:
            query = "sharedWithMe = true and trashed = false"
        else:
            query = f"'{_drive_query_literal(parent_id)}' in parents and trashed = false"
        items, next_page_token = self._list_files(query=query, limit=page_size, page_token=page_token, list_scope=list_scope)
        payload = self._split_items(items, parent_display_path=parent_display_path, limit=page_size, next_page_token=next_page_token)
        payload["breadcrumbs"] = breadcrumbs
        return payload

    def search(
        self,
        *,
        query: str = "",
        parent_drive_file_id: str = "",
        limit: int | None = None,
    ) -> dict[str, Any]:
        page_size = _bounded_limit(limit)
        drive_query = _search_query(query)
        parent_id = str(parent_drive_file_id or "").strip()
        parent_display_path = ""
        list_scope = _drive_list_scope()
        if parent_id:
            parent_display_path, list_scope, _breadcrumbs = self._parent_list_context(parent_id)
            if parent_id == SHARED_WITH_ME_ROOT_ID:
                drive_query = f"({drive_query}) and sharedWithMe = true"
            else:
                drive_query = f"({drive_query}) and '{_drive_query_literal(parent_id)}' in parents"
        items, next_page_token = self._list_files(query=drive_query, limit=page_size, page_token=None, list_scope=list_scope)
        return self._split_items(items, parent_display_path=parent_display_path, limit=page_size, next_page_token=next_page_token)

    def start_page_token(self) -> str:
        payload = self._drive_request("GET", "/changes/startPageToken", params={"supportsAllDrives": "true"})
        token = str(payload.get("startPageToken") or "").strip()
        if not token:
            raise DriveProviderError(502, "Google Drive did not return a start page token.")
        return token

    def list_changes(self, *, page_token: str, limit: int | None = None) -> dict[str, Any]:
        token = str(page_token or "").strip()
        if not token:
            raise StorageValidationError("Google Drive change feed requires a page token.", operation="drive_sync")
        max_changes = _bounded_limit(limit)
        files: list[dict[str, Any]] = []
        removed_files: list[dict[str, Any]] = []
        changes_processed = 0
        next_page_token = ""
        new_start_page_token = ""
        current_token = token
        while changes_processed < max_changes:
            payload = self._drive_request(
                "GET",
                "/changes",
                params={
                    "pageToken": current_token,
                    "pageSize": min(max_changes - changes_processed, MAX_DRIVE_PAGE_SIZE),
                    "fields": DRIVE_CHANGE_FIELDS,
                    "supportsAllDrives": "true",
                    "includeItemsFromAllDrives": "true",
                },
            )
            changes = payload.get("changes") if isinstance(payload.get("changes"), list) else []
            for change in changes:
                if not isinstance(change, dict):
                    continue
                changes_processed += 1
                normalized = self._normalize_change(change)
                if normalized.get("status") == "active":
                    files.append(normalized)
                else:
                    removed_files.append(normalized)
            next_page_token = str(payload.get("nextPageToken") or "")
            new_start_page_token = str(payload.get("newStartPageToken") or "")
            if not next_page_token or changes_processed >= max_changes:
                break
            current_token = next_page_token
        cursor_token = next_page_token if next_page_token else new_start_page_token or token
        return {
            "provider": GOOGLE_DRIVE_PROVIDER,
            "connection_id": self.connection_id,
            "files": files,
            "removed_files": removed_files,
            "changes_processed": changes_processed,
            "next_page_token": next_page_token,
            "new_start_page_token": new_start_page_token,
            "last_processed_page_token": cursor_token,
            "has_more": bool(next_page_token),
            "sync_mode": "change_feed",
        }

    def metadata(self, *, drive_file_id: str) -> dict[str, Any]:
        file_id = _required_drive_file_id(drive_file_id, operation="drive_metadata")
        try:
            item = self._drive_request(
                "GET",
                f"/files/{quote(file_id, safe='')}",
                params={"fields": DRIVE_FILE_FIELDS, "supportsAllDrives": "true"},
            )
        except DriveProviderError as error:
            status = "inaccessible" if error.status_code == 403 else "removed"
            stable_id = stable_storage_file_id(self.connection_id, file_id)
            return {
                "id": stable_id,
                "file_id": stable_id,
                "provider": GOOGLE_DRIVE_PROVIDER,
                "connection_id": self.connection_id,
                "drive_file_id": file_id,
                "remote_locator": {"drive_file_id": file_id},
                "stable_storage_file_id": stable_id,
                "status": status,
                "sync_status": status,
                "role": "",
                "relative_path": "",
                "workspace_relative_path": "",
                "display_path": "",
                "capabilities": normalize_capabilities({}, provider=GOOGLE_DRIVE_PROVIDER),
            }
        return self._normalize_item(item, display_path=self._display_path_for_item(item))

    def read(self, *, drive_file_id: str, max_bytes: int, file_record: dict[str, Any] | None = None) -> dict[str, Any]:
        """Read bounded Drive file bytes; Google-native files are exported as readable text."""
        file_record = self._active_metadata(drive_file_id=drive_file_id, operation="drive_read", file_record=file_record)
        if _is_google_native(file_record["content_type"]):
            return self.export(
                drive_file_id=drive_file_id,
                export_mime_type="readable_text",
                max_bytes=min(max_bytes, GOOGLE_EXPORT_LIMIT_BYTES),
                file_record=file_record,
            )
        self._require_download_capability(file_record, operation="drive_read")
        payload, cache_hit = self._download_binary(file_record=file_record, max_bytes=max_bytes, operation="drive_read")
        return _content_payload(file_record=file_record, payload=payload, content_type=file_record["content_type"], cache_hit=cache_hit)

    def preview(
        self,
        *,
        drive_file_id: str,
        max_bytes: int,
        max_chars: int | None = None,
        file_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a bounded preview through Storage without exposing Google-specific rules."""
        file_record = self._active_metadata(drive_file_id=drive_file_id, operation="drive_preview", file_record=file_record)
        if _is_google_native(file_record["content_type"]):
            exported = self.export(
                drive_file_id=drive_file_id,
                export_mime_type="preview",
                max_bytes=min(max_bytes, GOOGLE_EXPORT_LIMIT_BYTES),
                file_record=file_record,
            )
            text_payload = _decode_preview_text_payload(b64decode(exported["content_base64"]), max_chars=max_chars)
            return {
                "file": file_record,
                "preview_text": text_payload["preview_text"],
                "export_mime_type": exported["content_type"],
                "bytes_read": exported["bytes_read"],
                "cache_hit": exported["cache_hit"],
                "preview_truncated": text_payload["preview_truncated"],
                "truncated": bool(exported["truncated"] or text_payload["preview_truncated"]),
            }
        self._require_download_capability(file_record, operation="drive_preview")
        payload, cache_hit = self._download_binary(file_record=file_record, max_bytes=max_bytes, operation="drive_preview")
        result = _content_payload(file_record=file_record, payload=payload, content_type=file_record["content_type"], cache_hit=cache_hit)
        if file_record.get("preview_kind") in {"text", "markdown"} or str(file_record.get("content_type") or "").startswith("text/"):
            text_payload = _decode_preview_text_payload(payload, max_chars=max_chars)
            result["preview_text"] = text_payload["preview_text"]
            result["preview_truncated"] = text_payload["preview_truncated"]
            result["truncated"] = bool(result.get("truncated") or text_payload["preview_truncated"])
        return result

    def export(
        self,
        *,
        drive_file_id: str,
        export_mime_type: str,
        max_bytes: int,
        file_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Export or download a Drive file in a bounded Storage-owned format."""
        file_record = self._active_metadata(drive_file_id=drive_file_id, operation="drive_export", file_record=file_record)
        requested_mime = _select_export_mime(file_record["content_type"], export_mime_type)
        if not _is_google_native(file_record["content_type"]):
            if requested_mime and requested_mime != file_record["content_type"]:
                raise StorageValidationError(
                    "Binary Drive files can only be downloaded as their original content type; conversion is available only for Google Docs, Sheets, and Slides.",
                    operation="drive_export",
                    allowed_values={"export_mime_type": [file_record["content_type"]]},
                )
            self._require_download_capability(file_record, operation="drive_export")
            payload, cache_hit = self._download_binary(file_record=file_record, max_bytes=max_bytes, operation="drive_export")
            return _content_payload(file_record=file_record, payload=payload, content_type=file_record["content_type"], cache_hit=cache_hit)
        self._require_download_capability(file_record, operation="drive_export")
        if max_bytes > GOOGLE_EXPORT_LIMIT_BYTES:
            raise StorageValidationError(
                f"Google Drive files.export is limited to {GOOGLE_EXPORT_LIMIT_BYTES} bytes; request a smaller export or a different format.",
                operation="drive_export",
                allowed_values={"max_bytes": [str(GOOGLE_EXPORT_LIMIT_BYTES)]},
            )
        payload, cache_hit = self._export_native(file_record=file_record, export_mime_type=requested_mime, max_bytes=max_bytes)
        return _content_payload(file_record=file_record, payload=payload, content_type=requested_mime, cache_hit=cache_hit)

    def download_binary_content(
        self,
        *,
        drive_file_id: str,
        max_bytes: int,
        operation: str,
        file_record: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bytes, bool]:
        """Download one binary Drive file without converting it to a JSON/base64 payload."""
        file_record = self._active_metadata(drive_file_id=drive_file_id, operation=operation, file_record=file_record)
        if _is_google_native(file_record["content_type"]):
            raise StorageValidationError(
                "Google-native Docs, Sheets, and Slides must be exported through drive_export; they cannot be localized as original binary media.",
                operation=operation,
            )
        self._require_download_capability(file_record, operation=operation)
        payload, cache_hit = self._download_binary(file_record=file_record, max_bytes=max_bytes, operation=operation)
        return file_record, payload, cache_hit

    def download_binary_to_path(
        self,
        *,
        drive_file_id: str,
        max_bytes: int,
        operation: str,
        target_path: Path,
        file_record: dict[str, Any] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[dict[str, Any], int, str, bool]:
        """Download one binary Drive file to a local path without base64 or browser token exposure."""
        file_record = self._active_metadata(drive_file_id=drive_file_id, operation=operation, file_record=file_record)
        if _is_google_native(file_record["content_type"]):
            raise StorageValidationError(
                "Google-native Docs, Sheets, and Slides must be exported through drive_export; they cannot be localized as original binary media.",
                operation=operation,
            )
        self._require_download_capability(file_record, operation=operation)
        declared_size = _int_value(file_record.get("size_bytes"))
        if declared_size and declared_size > max_bytes:
            raise StorageValidationError(f"Drive file is too large to read through Storage with max_bytes={max_bytes}.", operation=operation)
        cache_key = self._cache_key(file_record=file_record, content_mime_type=file_record["content_type"], purpose="download", max_bytes=max_bytes)
        cached = self._read_cache(cache_key)
        if cached is not None:
            _validate_declared_stream_size(actual_size=len(cached), declared_size=declared_size, operation=operation)
            sha256 = hashlib.sha256(cached).hexdigest()
            _write_payload_to_path(target_path, cached)
            progress_callback and progress_callback(len(cached), len(cached))
            return file_record, len(cached), sha256, True
        if self.transport is not default_transport:
            payload, cache_hit = self._download_binary(file_record=file_record, max_bytes=max_bytes, operation=operation, validate_declared_size=True)
            sha256 = hashlib.sha256(payload).hexdigest()
            _write_payload_to_path(target_path, payload)
            progress_callback and progress_callback(len(payload), len(payload))
            return file_record, len(payload), sha256, cache_hit
        size_bytes, sha256 = self._drive_bytes_to_path(
            "GET",
            f"/files/{quote(file_record['drive_file_id'], safe='')}",
            params={"alt": "media", "supportsAllDrives": "true"},
            max_bytes=max_bytes,
            operation=operation,
            target_path=target_path,
            declared_size=declared_size,
            progress_callback=progress_callback,
        )
        return file_record, size_bytes, sha256, False

    def stream_binary_to_path_and_handle(
        self,
        *,
        drive_file_id: str,
        max_bytes: int,
        operation: str,
        target_path: Path,
        output_handle: BinaryIO,
        file_record: dict[str, Any] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[dict[str, Any], int, str, bool]:
        """Stream one binary Drive file to an output handle while writing the local cache."""
        prepared = self.prepare_binary_stream_to_path(
            drive_file_id=drive_file_id,
            max_bytes=max_bytes,
            operation=operation,
            target_path=target_path,
            file_record=file_record,
        )
        return self.finish_binary_stream_to_path_and_handle(
            prepared,
            output_handle=output_handle,
            progress_callback=progress_callback,
        )

    def prepare_binary_stream_to_path(
        self,
        *,
        drive_file_id: str,
        max_bytes: int,
        operation: str,
        target_path: Path,
        file_record: dict[str, Any] | None = None,
    ) -> PreparedDriveBinaryStream:
        """Open and validate one Drive media response before stream headers are emitted."""
        file_record = self._active_metadata(drive_file_id=drive_file_id, operation=operation, file_record=file_record)
        if _is_google_native(file_record["content_type"]):
            raise StorageValidationError(
                "Google-native Docs, Sheets, and Slides must be exported through drive_export; they cannot be streamed as original binary media.",
                operation=operation,
            )
        self._require_download_capability(file_record, operation=operation)
        declared_size = _int_value(file_record.get("size_bytes"))
        if declared_size and declared_size > max_bytes:
            raise StorageValidationError(f"Drive file is too large to read through Storage with max_bytes={max_bytes}.", operation=operation)
        cache_key = self._cache_key(file_record=file_record, content_mime_type=file_record["content_type"], purpose="download", max_bytes=max_bytes)
        cached = self._read_cache(cache_key)
        if cached is not None:
            _validate_declared_stream_size(actual_size=len(cached), declared_size=declared_size, operation=operation)
            return PreparedDriveBinaryStream(
                file_record=file_record,
                target_path=target_path,
                declared_size=declared_size,
                max_bytes=max_bytes,
                operation=operation,
                provider_cache_hit=True,
                payload=cached,
            )
        if self.transport is not default_transport:
            payload, cache_hit = self._download_binary(file_record=file_record, max_bytes=max_bytes, operation=operation, validate_declared_size=True)
            return PreparedDriveBinaryStream(
                file_record=file_record,
                target_path=target_path,
                declared_size=declared_size,
                max_bytes=max_bytes,
                operation=operation,
                provider_cache_hit=cache_hit,
                payload=payload,
            )
        return self._prepare_drive_bytes_to_path(
            "GET",
            f"/files/{quote(file_record['drive_file_id'], safe='')}",
            params={"alt": "media", "supportsAllDrives": "true"},
            max_bytes=max_bytes,
            operation=operation,
            target_path=target_path,
            declared_size=declared_size,
            file_record=file_record,
        )

    def finish_binary_stream_to_path_and_handle(
        self,
        prepared: PreparedDriveBinaryStream,
        *,
        output_handle: BinaryIO,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[dict[str, Any], int, str, bool]:
        """Finish a prepared Drive media stream into the output handle and cache path."""
        if prepared.payload is not None:
            sha256 = hashlib.sha256(prepared.payload).hexdigest()
            _write_payload_to_path_and_handle(
                prepared.target_path,
                prepared.payload,
                output_handle,
                progress_callback=progress_callback,
            )
            return prepared.file_record, len(prepared.payload), sha256, prepared.provider_cache_hit
        size_bytes, sha256 = self._finish_prepared_drive_bytes_to_path_and_handle(
            prepared,
            output_handle=output_handle,
            progress_callback=progress_callback,
        )
        return prepared.file_record, size_bytes, sha256, prepared.provider_cache_hit

    def download_binary_range_to_path(
        self,
        *,
        drive_file_id: str,
        operation: str,
        target_path: Path,
        start: int,
        end: int,
        total_size: int,
        file_record: dict[str, Any] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[dict[str, Any], int, str]:
        """Download one Drive byte range to a local path without base64 materialization."""
        file_record = self._active_metadata(drive_file_id=drive_file_id, operation=operation, file_record=file_record)
        if _is_google_native(file_record["content_type"]):
            raise StorageValidationError(
                "Google-native Docs, Sheets, and Slides must be exported through drive_export; they cannot be streamed as original binary media.",
                operation=operation,
            )
        self._require_download_capability(file_record, operation=operation)
        declared_size = _int_value(file_record.get("size_bytes"))
        if start < 0 or end < start:
            raise StorageValidationError("Drive media Range header is invalid.", operation=operation)
        if declared_size and total_size and declared_size != total_size:
            raise StorageValidationError("Drive media source size changed; refresh the Storage file record and retry.", operation=operation)
        if declared_size and end >= declared_size:
            raise StorageValidationError("Drive media Range header exceeds the file size.", operation=operation)
        if self.transport is not default_transport:
            payload = self._drive_bytes_request(
                "GET",
                f"/files/{quote(file_record['drive_file_id'], safe='')}",
                params={"alt": "media", "supportsAllDrives": "true"},
                max_bytes=max(declared_size, end + 1),
                operation=operation,
            )
            selected = payload[start : end + 1]
            if len(selected) != end - start + 1:
                raise StorageValidationError("Drive did not return enough bytes for the requested media range.", operation=operation)
            _write_payload_to_path(target_path, selected)
            progress_callback and progress_callback(len(selected), len(selected))
            return file_record, len(selected), hashlib.sha256(selected).hexdigest()
        size_bytes, sha256 = self._drive_byte_range_to_path(
            "GET",
            f"/files/{quote(file_record['drive_file_id'], safe='')}",
            params={"alt": "media", "supportsAllDrives": "true"},
            operation=operation,
            target_path=target_path,
            start=start,
            end=end,
            total_size=total_size or declared_size,
            progress_callback=progress_callback,
        )
        return file_record, size_bytes, sha256

    def upload(
        self,
        *,
        parent_drive_file_id: str,
        file_name: str,
        content: bytes,
        content_type: str,
    ) -> dict[str, Any]:
        """Upload a new binary file into a Drive folder after folder capability checks."""
        parent_id = _required_drive_file_id(parent_drive_file_id, operation="drive_write")
        name = _required_file_name(file_name, operation="drive_write")
        payload = _required_content(content, operation="drive_write")
        normalized_content_type = _content_type(content_type)
        parent_record = self._active_metadata(drive_file_id=parent_id, operation="drive_write")
        if parent_record.get("content_type") != DRIVE_FOLDER_MIME_TYPE:
            raise StorageValidationError("Google Drive uploads require a target Drive folder.", operation="drive_write")
        self._require_capability(
            parent_record,
            capability="can_write",
            operation="drive_write",
            detail="Google Drive did not grant permission to add files to the target folder.",
        )
        boundary = f"maverick-storage-{hashlib.sha256(f'{self.connection_id}:{name}:{time.time()}'.encode('utf-8')).hexdigest()[:24]}"
        metadata = {"name": name, "parents": [parent_id]}
        response = self._drive_upload_request(
            "POST",
            "/files",
            params={"uploadType": "multipart", "fields": DRIVE_FILE_FIELDS, "supportsAllDrives": "true"},
            data=_multipart_related_payload(boundary=boundary, metadata=metadata, content=payload, content_type=normalized_content_type),
            content_type=f"multipart/related; boundary={boundary}",
            operation="drive_write",
        )
        file_record = self._normalize_item(response, display_path=_join_display_path(parent_record.get("display_path", ""), name))
        return {"status": "uploaded", "provider": GOOGLE_DRIVE_PROVIDER, "connection_id": self.connection_id, "file": file_record}

    def start_resumable_upload(
        self,
        *,
        parent_drive_file_id: str,
        file_name: str,
        content_type: str,
        size_bytes: int,
    ) -> dict[str, Any]:
        """Create a Drive resumable upload session after validating the target folder."""
        parent_id = _required_drive_file_id(parent_drive_file_id, operation="drive_upload_session.start")
        name = _required_file_name(file_name, operation="drive_upload_session.start")
        if size_bytes < 0:
            raise StorageValidationError("size_bytes must not be negative.", operation="drive_upload_session.start")
        normalized_content_type = _content_type(content_type)
        parent_record = self._active_metadata(drive_file_id=parent_id, operation="drive_upload_session.start")
        if parent_record.get("content_type") != DRIVE_FOLDER_MIME_TYPE:
            raise StorageValidationError("Google Drive uploads require a target Drive folder.", operation="drive_upload_session.start")
        self._require_capability(
            parent_record,
            capability="can_write",
            operation="drive_upload_session.start",
            detail="Google Drive did not grant permission to add files to the target folder.",
        )
        metadata = {"name": name, "parents": [parent_id]}
        session_uri = self._start_drive_resumable_session(
            metadata=metadata,
            content_type=normalized_content_type,
            size_bytes=size_bytes,
        )
        return {
            "status": "uploading",
            "provider": GOOGLE_DRIVE_PROVIDER,
            "connection_id": self.connection_id,
            "session_uri": session_uri,
            "parent_drive_file_id": parent_id,
            "parent_display_path": str(parent_record.get("display_path") or ""),
            "file_name": name,
            "content_type": normalized_content_type,
            "size_bytes": size_bytes,
        }

    def upload_resumable_chunk(
        self,
        *,
        session_uri: str,
        file_name: str,
        content_type: str,
        parent_display_path: str,
        chunk: bytes,
        start: int,
        total_size: int,
    ) -> dict[str, Any]:
        """Forward one chunk to a Storage-owned Drive resumable upload session."""
        if start < 0:
            raise StorageValidationError("chunk_offset must not be negative.", operation="drive_upload_session.chunk")
        if total_size <= 0:
            raise StorageValidationError("size_bytes must be positive for chunked Drive uploads.", operation="drive_upload_session.chunk")
        if not chunk:
            raise StorageValidationError("content_base64 chunk must not be empty.", operation="drive_upload_session.chunk")
        if len(chunk) > DRIVE_RESUMABLE_CHUNK_BYTES:
            raise StorageValidationError(
                f"Drive upload chunks are limited to {DRIVE_RESUMABLE_CHUNK_BYTES} bytes.",
                operation="drive_upload_session.chunk",
            )
        if start + len(chunk) > total_size:
            raise StorageValidationError("Drive upload chunk exceeds the declared file size.", operation="drive_upload_session.chunk")
        if start + len(chunk) < total_size and len(chunk) % (256 * 1024) != 0:
            raise StorageValidationError(
                "Non-final Drive upload chunks must be a multiple of 256 KiB.",
                operation="drive_upload_session.chunk",
            )
        response = self._drive_resumable_chunk_request(
            session_uri=session_uri,
            content_type=_content_type(content_type),
            chunk=chunk,
            start=start,
            total_size=total_size,
        )
        if response["status"] == "uploading":
            return {
                "status": "uploading",
                "provider": GOOGLE_DRIVE_PROVIDER,
                "connection_id": self.connection_id,
                "bytes_uploaded": response["bytes_uploaded"],
            }
        file_record = self._normalize_item(response["file"], display_path=_join_display_path(parent_display_path, file_name))
        return {
            "status": "uploaded",
            "provider": GOOGLE_DRIVE_PROVIDER,
            "connection_id": self.connection_id,
            "bytes_uploaded": total_size,
            "file": file_record,
        }

    def query_resumable_upload(
        self,
        *,
        session_uri: str,
        file_name: str,
        content_type: str,
        parent_display_path: str,
        total_size: int,
    ) -> dict[str, Any]:
        """Ask Google Drive which bytes are committed for a resumable upload session."""
        if total_size <= 0:
            raise StorageValidationError("size_bytes must be positive for chunked Drive uploads.", operation="drive_upload_session.status")
        response = self._drive_resumable_query_request(session_uri=session_uri, total_size=total_size)
        if response["status"] == "uploading":
            uploaded = min(max(0, int(response.get("bytes_uploaded") or 0)), total_size)
            return {
                "status": "uploading",
                "provider": GOOGLE_DRIVE_PROVIDER,
                "connection_id": self.connection_id,
                "bytes_uploaded": uploaded,
            }
        file_record = self._normalize_item(response["file"], display_path=_join_display_path(parent_display_path, file_name))
        return {
            "status": "uploaded",
            "provider": GOOGLE_DRIVE_PROVIDER,
            "connection_id": self.connection_id,
            "bytes_uploaded": total_size,
            "file": file_record,
        }

    def cancel_resumable_upload(self, *, session_uri: str) -> None:
        """Best-effort cancellation of a Google Drive resumable upload session."""
        if not str(session_uri or "").strip():
            return
        try:
            self._drive_resumable_cancel_request(session_uri=session_uri)
        except (DriveProviderError, StorageValidationError):
            return

    def update_content(self, *, drive_file_id: str, content: bytes, content_type: str) -> dict[str, Any]:
        """Replace binary Drive file content where the Drive API supports media updates."""
        file_record = self._active_metadata(drive_file_id=drive_file_id, operation="drive_write")
        self._require_capability(
            file_record,
            capability="can_write",
            operation="drive_write",
            detail="Google Drive did not grant permission to update this file's content.",
        )
        if _is_google_native(str(file_record.get("content_type") or "")):
            raise StorageValidationError(
                "Google-native Docs, Sheets, and Slides cannot be content-updated through Drive media upload; export or edit them in their native Google surface.",
                operation="drive_write",
            )
        payload = _required_content(content, operation="drive_write")
        response = self._drive_upload_request(
            "PATCH",
            f"/files/{quote(str(file_record['drive_file_id']), safe='')}",
            params={"uploadType": "media", "fields": DRIVE_FILE_FIELDS, "supportsAllDrives": "true"},
            data=payload,
            content_type=_content_type(content_type or file_record.get("content_type")),
            operation="drive_write",
        )
        return {
            "status": "updated",
            "provider": GOOGLE_DRIVE_PROVIDER,
            "connection_id": self.connection_id,
            "file": self._normalize_item(response, display_path=self._display_path_for_item(response)),
        }

    def rename(self, *, drive_file_id: str, new_name: str) -> dict[str, Any]:
        """Rename one Drive file after validating Drive capabilities."""
        file_record = self._active_metadata(drive_file_id=drive_file_id, operation="drive_rename")
        name = _required_file_name(new_name, operation="drive_rename")
        self._require_capability(
            file_record,
            capability="can_rename",
            operation="drive_rename",
            detail="Google Drive did not grant rename permission for this file.",
        )
        response = self._drive_request(
            "PATCH",
            f"/files/{quote(str(file_record['drive_file_id']), safe='')}",
            params={"fields": DRIVE_FILE_FIELDS, "supportsAllDrives": "true"},
            data=json.dumps({"name": name}, ensure_ascii=True),
            headers={"Content-Type": "application/json"},
        )
        return {
            "status": "renamed",
            "provider": GOOGLE_DRIVE_PROVIDER,
            "connection_id": self.connection_id,
            "file": self._normalize_item(response, display_path=self._display_path_for_item(response)),
        }

    def move(self, *, drive_file_id: str, target_parent_drive_file_id: str) -> dict[str, Any]:
        """Move one Drive file to a target parent after source and target checks."""
        file_record = self._active_metadata(drive_file_id=drive_file_id, operation="drive_move")
        target_id = _required_drive_file_id(target_parent_drive_file_id, operation="drive_move")
        target_record = self._active_metadata(drive_file_id=target_id, operation="drive_move")
        if target_record.get("content_type") != DRIVE_FOLDER_MIME_TYPE:
            raise StorageValidationError("Google Drive moves require a target Drive folder.", operation="drive_move")
        self._require_capability(
            file_record,
            capability="can_move",
            operation="drive_move",
            detail="Google Drive did not grant move permission for this file.",
        )
        self._require_capability(
            target_record,
            capability="can_write",
            operation="drive_move",
            detail="Google Drive did not grant permission to add files to the target folder.",
        )
        parents = file_record.get("remote_parents") if isinstance(file_record.get("remote_parents"), list) else []
        remove_parents = ",".join(str(parent) for parent in parents if str(parent or "").strip())
        params: dict[str, Any] = {
            "addParents": target_id,
            "fields": DRIVE_FILE_FIELDS,
            "supportsAllDrives": "true",
        }
        if remove_parents:
            params["removeParents"] = remove_parents
        response = self._drive_request("PATCH", f"/files/{quote(str(file_record['drive_file_id']), safe='')}", params=params)
        return {
            "status": "moved",
            "provider": GOOGLE_DRIVE_PROVIDER,
            "connection_id": self.connection_id,
            "file": self._normalize_item(response, display_path=self._display_path_for_item(response)),
        }

    def trash(self, *, drive_file_id: str) -> dict[str, Any]:
        """Move one Drive file to trash after delete capability checks."""
        file_record = self._active_metadata(drive_file_id=drive_file_id, operation="drive_trash")
        self._require_capability(
            file_record,
            capability="can_delete",
            operation="drive_trash",
            detail="Google Drive did not grant trash/delete permission for this file.",
        )
        response = self._drive_request(
            "PATCH",
            f"/files/{quote(str(file_record['drive_file_id']), safe='')}",
            params={"fields": DRIVE_FILE_FIELDS, "supportsAllDrives": "true"},
            data=json.dumps({"trashed": True}, ensure_ascii=True),
            headers={"Content-Type": "application/json"},
        )
        return {
            "status": "trashed",
            "provider": GOOGLE_DRIVE_PROVIDER,
            "connection_id": self.connection_id,
            "file": self._normalize_item(response, display_path=self._display_path_for_item(response)),
        }

    def _split_items(self, items: list[dict[str, Any]], *, parent_display_path: str, limit: int, next_page_token: str = "") -> dict[str, Any]:
        files: list[dict[str, Any]] = []
        folders: list[dict[str, Any]] = []
        for item in items:
            display_path = _join_display_path(parent_display_path, str(item.get("name") or ""))
            normalized = self._normalize_item(item, display_path=display_path)
            if item.get("mimeType") == DRIVE_FOLDER_MIME_TYPE:
                folders.append(self._folder_from_item(normalized))
            else:
                files.append(normalized)
        return {
            "provider": GOOGLE_DRIVE_PROVIDER,
            "connection_id": self.connection_id,
            "files": files,
            "folders": folders,
            "pagination": {"limit": limit, "total": len(files) + len(folders), "has_more": bool(next_page_token), "next_page_token": next_page_token},
        }

    def _list_files(
        self,
        *,
        query: str,
        limit: int,
        page_token: str | None,
        list_scope: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str]:
        params: dict[str, Any] = {
            "q": query,
            "pageSize": min(limit, MAX_DRIVE_PAGE_SIZE),
            "fields": f"nextPageToken,files({DRIVE_FILE_FIELDS})",
            "supportsAllDrives": "true",
            **list_scope,
        }
        current_token = str(page_token or "").strip()
        if current_token:
            params["pageToken"] = current_token
        payload = self._drive_request("GET", "/files", params=params)
        items = [item for item in payload.get("files") if isinstance(item, dict)] if isinstance(payload.get("files"), list) else []
        return items[:limit], str(payload.get("nextPageToken") or "")

    def _parent_list_context(self, parent_id: str) -> tuple[str, dict[str, Any], list[dict[str, str]]]:
        if parent_id == "root":
            return "/My Drive", _drive_list_scope(corpora="user"), [self._breadcrumb_target(drive_file_id="root", label="My Drive", display_path="/My Drive")]
        if parent_id == SHARED_WITH_ME_ROOT_ID:
            return "/Shared with me", _drive_list_scope(corpora="user"), [self._breadcrumb_target(drive_file_id=SHARED_WITH_ME_ROOT_ID, label="Shared with me", display_path="/Shared with me")]
        parent = self._parent_item(parent_id)
        if not parent:
            return "", _drive_list_scope(), []
        drive_id = str(parent.get("driveId") or "").strip()
        parent_display_path, breadcrumbs = self._display_context_for_item(parent)
        return parent_display_path, _drive_list_scope(corpora="drive", drive_id=drive_id) if drive_id else _drive_list_scope(corpora="user"), breadcrumbs

    def _parent_item(self, parent_id: str) -> dict[str, Any] | None:
        try:
            return self._drive_request(
                "GET",
                f"/files/{quote(parent_id, safe='')}",
                params={"fields": "id,name,mimeType,parents,driveId,trashed", "supportsAllDrives": "true"},
            )
        except DriveProviderError:
            return None

    def _display_path_for_item(self, item: dict[str, Any]) -> str:
        display_path, _breadcrumbs = self._display_context_for_item(item)
        return display_path

    def _display_context_for_item(self, item: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
        items = [
            {
                "drive_file_id": str(item.get("id") or "").strip(),
                "label": str(item.get("name") or "").strip(),
            }
        ]
        current = item
        seen = {str(item.get("id") or "")}
        for _depth in range(12):
            parents = current.get("parents") if isinstance(current.get("parents"), list) else []
            parent_id = str(parents[0] if parents else "").strip()
            if not parent_id or parent_id in seen:
                break
            if parent_id == "root":
                items.append({"drive_file_id": "root", "label": "My Drive"})
                break
            seen.add(parent_id)
            try:
                current = self._drive_request(
                    "GET",
                    f"/files/{quote(parent_id, safe='')}",
                    params={"fields": "id,name,parents,driveId,trashed", "supportsAllDrives": "true"},
                )
            except DriveProviderError:
                break
            parent_name = str(current.get("name") or "").strip()
            if parent_name:
                items.append({"drive_file_id": str(current.get("id") or "").strip(), "label": parent_name})
        items = [entry for entry in reversed(items) if entry["drive_file_id"] and entry["label"]]
        names = [entry["label"] for entry in items]
        breadcrumbs: list[dict[str, str]] = []
        for index, entry in enumerate(items):
            display_path = "/" + "/".join(names[: index + 1])
            breadcrumbs.append(self._breadcrumb_target(
                drive_file_id=entry["drive_file_id"],
                label=entry["label"],
                display_path=display_path,
            ))
        return "/" + "/".join(names) if names else "", breadcrumbs

    def _breadcrumb_target(self, *, drive_file_id: str, label: str, display_path: str) -> dict[str, str]:
        return {
            "connection_id": self.connection_id,
            "display_path": display_path,
            "drive_file_id": drive_file_id,
            "label": label,
        }

    def _normalize_item(self, item: dict[str, Any], *, display_path: str) -> dict[str, Any]:
        drive_file_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or drive_file_id).strip()
        mime_type = normalize_content_type(item.get("mimeType"), file_name=name)
        status = "removed" if bool(item.get("trashed") or item.get("explicitlyTrashed")) else "active"
        stable_id = stable_storage_file_id(self.connection_id, drive_file_id)
        source_version = str(item.get("headRevisionId") or item.get("version") or "")
        version = source_version or str(item.get("modifiedTime") or "")
        extension = Path(name).suffix.lower()
        return {
            "id": stable_id,
            "file_id": stable_id,
            "stable_storage_file_id": stable_id,
            "path_id": "",
            "provider": GOOGLE_DRIVE_PROVIDER,
            "connection_id": self.connection_id,
            "drive_file_id": drive_file_id,
            "remote_locator": {"drive_file_id": drive_file_id},
            "remote_parents": [str(parent) for parent in item.get("parents", []) if str(parent or "").strip()] if isinstance(item.get("parents"), list) else [],
            "display_path": display_path or f"/{name}",
            "role": "",
            "name": name,
            "relative_path": "",
            "workspace_relative_path": "",
            "extension": extension,
            "size_bytes": _int_value(item.get("size")),
            "modified_at": str(item.get("modifiedTime") or item.get("createdTime") or ""),
            "content_type": mime_type,
            "preview_kind": _drive_preview_kind(mime_type, extension),
            "sha256": "",
            "etag_or_version": version,
            "source_version": source_version,
            "capabilities": _drive_capabilities(item.get("capabilities")),
            "sync_status": "removed" if status == "removed" else "synced",
            "indexed": False,
            "stale": status != "active",
            "index_status": "stale" if status != "active" else "not_indexed",
            "status": status,
            "web_url": str(item.get("webViewLink") or ""),
        }

    def _normalize_change(self, change: dict[str, Any]) -> dict[str, Any]:
        file_payload = change.get("file") if isinstance(change.get("file"), dict) else {}
        drive_file_id = str(change.get("fileId") or file_payload.get("id") or "").strip()
        if bool(change.get("removed")) or not file_payload:
            return self._removed_file_record(drive_file_id=drive_file_id)
        return self._normalize_item(file_payload, display_path=self._display_path_for_item(file_payload))

    def _removed_file_record(self, *, drive_file_id: str) -> dict[str, Any]:
        stable_id = stable_storage_file_id(self.connection_id, drive_file_id)
        return {
            "id": stable_id,
            "file_id": stable_id,
            "stable_storage_file_id": stable_id,
            "path_id": "",
            "provider": GOOGLE_DRIVE_PROVIDER,
            "connection_id": self.connection_id,
            "drive_file_id": drive_file_id,
            "remote_locator": {"drive_file_id": drive_file_id},
            "remote_parents": [],
            "display_path": "",
            "role": "",
            "name": drive_file_id or stable_id,
            "relative_path": "",
            "workspace_relative_path": "",
            "extension": "",
            "size_bytes": 0,
            "modified_at": "",
            "content_type": "application/octet-stream",
            "preview_kind": "file",
            "sha256": "",
            "etag_or_version": "",
            "source_version": "",
            "capabilities": normalize_capabilities({}, provider=GOOGLE_DRIVE_PROVIDER),
            "sync_status": "removed",
            "indexed": False,
            "stale": True,
            "index_status": "stale",
            "status": "removed",
            "web_url": "",
        }

    def _folder_from_item(self, item: dict[str, Any]) -> dict[str, Any]:
        folder_digest = hashlib.sha256(f"{self.connection_id}\0{item['drive_file_id']}".encode("utf-8")).hexdigest()[:32]
        return {
            "id": f"folder_{folder_digest}",
            "provider": GOOGLE_DRIVE_PROVIDER,
            "connection_id": self.connection_id,
            "drive_file_id": item["drive_file_id"],
            "remote_locator": {"drive_file_id": item["drive_file_id"]},
            "display_path": item["display_path"],
            "role": "",
            "name": item["name"],
            "relative_path": "",
            "workspace_relative_path": "",
            "modified_at": item["modified_at"],
            "capabilities": item["capabilities"],
            "sync_status": item["sync_status"],
            "indexed": item["indexed"],
            "stale": item["stale"],
            "index_status": item["index_status"],
            "status": item["status"],
        }

    def _root_folder(
        self,
        *,
        drive_file_id: str,
        name: str,
        display_path: str,
        root_kind: str,
        capabilities: dict[str, bool],
    ) -> dict[str, Any]:
        normalized_capabilities = normalize_capabilities(capabilities, provider=GOOGLE_DRIVE_PROVIDER)
        root_digest = hashlib.sha256(f"{self.connection_id}\0{root_kind}\0{drive_file_id}".encode("utf-8")).hexdigest()[:32]
        return {
            "id": f"folder_{root_digest}",
            "provider": GOOGLE_DRIVE_PROVIDER,
            "connection_id": self.connection_id,
            "drive_file_id": drive_file_id,
            "remote_locator": {"drive_file_id": drive_file_id, "root_kind": root_kind},
            "display_path": display_path,
            "role": "",
            "name": name,
            "relative_path": "",
            "workspace_relative_path": "",
            "modified_at": "",
            "capabilities": normalized_capabilities,
            "sync_status": "synced",
            "indexed": False,
            "stale": False,
            "index_status": "not_indexed",
            "status": "active",
        }

    def _drive_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        query = urlencode({key: value for key, value in (params or {}).items() if value is not None})
        url = f"{DRIVE_API_BASE}{path}" + (f"?{query}" if query else "")
        request_headers = {"Authorization": f"Bearer {self._token()}", "Accept": "application/json", **(headers or {})}
        status, payload = self.transport(
            method,
            url,
            {
                "headers": request_headers,
                "data": data,
            },
        )
        if status >= 400:
            detail = str(payload.get("error", {}).get("message") or payload.get("error") or "Drive request failed") if isinstance(payload, dict) else "Drive request failed"
            raise DriveProviderError(status, detail)
        return payload if isinstance(payload, dict) else {}

    def _drive_upload_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any],
        data: bytes,
        content_type: str,
        operation: str,
    ) -> dict[str, Any]:
        query = urlencode({key: value for key, value in params.items() if value is not None})
        url = f"{DRIVE_UPLOAD_API_BASE}{path}" + (f"?{query}" if query else "")
        status, payload = self.transport(
            method,
            url,
            {
                "headers": {
                    "Authorization": f"Bearer {self._token()}",
                    "Accept": "application/json",
                    "Content-Type": content_type,
                },
                "data": data,
            },
        )
        if status >= 400:
            detail = str(payload.get("error", {}).get("message") or payload.get("error") or "Drive upload request failed") if isinstance(payload, dict) else "Drive upload request failed"
            raise StorageValidationError(f"Google Drive write request failed: {detail}", operation=operation)
        if not isinstance(payload, dict) or not str(payload.get("id") or "").strip():
            raise StorageValidationError("Google Drive write request did not return file metadata.", operation=operation)
        return payload

    def _start_drive_resumable_session(self, *, metadata: dict[str, Any], content_type: str, size_bytes: int) -> str:
        query = urlencode({"uploadType": "resumable", "fields": DRIVE_FILE_FIELDS, "supportsAllDrives": "true"})
        url = f"{DRIVE_UPLOAD_API_BASE}/files?{query}"
        headers = {
            "Authorization": f"Bearer {self._token()}",
            "Accept": "application/json",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": content_type,
            "X-Upload-Content-Length": str(size_bytes),
        }
        data = json.dumps(metadata, ensure_ascii=True).encode("utf-8")
        if self.transport is not default_transport:
            status, payload = self.transport("POST", url, {"headers": headers, "data": data})
            if status >= 400:
                detail = _provider_error_detail(payload, fallback="Drive resumable upload session request failed")
                raise StorageValidationError(f"Google Drive upload session request failed: {detail}", operation="drive_upload_session.start")
            session_uri = ""
            if isinstance(payload, dict):
                session_uri = str(payload.get("session_uri") or payload.get("upload_url") or payload.get("location") or "").strip()
            if not session_uri:
                raise StorageValidationError("Google Drive upload session did not return a resumable session URI.", operation="drive_upload_session.start")
            return session_uri
        try:
            request = Request(url, data=data, headers=headers, method="POST")
            with urlopen(request, timeout=60) as response:
                session_uri = str(response.headers.get("Location") or "").strip()
                if not session_uri:
                    raise StorageValidationError(
                        "Google Drive upload session did not return a resumable session URI.",
                        operation="drive_upload_session.start",
                    )
                return session_uri
        except HTTPError as error:
            raise StorageValidationError(
                f"Google Drive upload session request failed: {_http_error_detail(error)}",
                operation="drive_upload_session.start",
            ) from error
        except URLError as error:
            raise DriveProviderError(503, "Google Drive upload session is currently unavailable.") from error

    def _drive_resumable_chunk_request(
        self,
        *,
        session_uri: str,
        content_type: str,
        chunk: bytes,
        start: int,
        total_size: int,
    ) -> dict[str, Any]:
        end = start + len(chunk) - 1
        headers = {
            "Authorization": f"Bearer {self._token()}",
            "Accept": "application/json",
            "Content-Type": content_type,
            "Content-Length": str(len(chunk)),
            "Content-Range": f"bytes {start}-{end}/{total_size}",
        }
        if self.transport is not default_transport:
            status, payload = self.transport("PUT", session_uri, {"headers": headers, "data": chunk})
            if status == 308:
                return {"status": "uploading", "bytes_uploaded": _next_offset_from_range_payload(payload, fallback=end + 1)}
            if status >= 400:
                detail = _provider_error_detail(payload, fallback="Drive resumable upload chunk failed")
                raise StorageValidationError(f"Google Drive upload chunk failed: {detail}", operation="drive_upload_session.chunk")
            if not isinstance(payload, dict) or not str(payload.get("id") or "").strip():
                raise StorageValidationError("Google Drive upload chunk did not return file metadata.", operation="drive_upload_session.chunk")
            return {"status": "uploaded", "file": payload}
        try:
            request = Request(session_uri, data=chunk, headers=headers, method="PUT")
            with urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
                if not isinstance(payload, dict) or not str(payload.get("id") or "").strip():
                    raise StorageValidationError("Google Drive upload chunk did not return file metadata.", operation="drive_upload_session.chunk")
                return {"status": "uploaded", "file": payload}
        except HTTPError as error:
            if int(error.code) == 308:
                return {"status": "uploading", "bytes_uploaded": _next_offset_from_range_header(error.headers.get("Range"), fallback=end + 1)}
            raise StorageValidationError(
                f"Google Drive upload chunk failed: {_http_error_detail(error)}",
                operation="drive_upload_session.chunk",
            ) from error
        except URLError as error:
            raise DriveProviderError(503, "Google Drive upload is currently unavailable.") from error

    def _drive_resumable_query_request(self, *, session_uri: str, total_size: int) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._token()}",
            "Accept": "application/json",
            "Content-Length": "0",
            "Content-Range": f"bytes */{total_size}",
        }
        if self.transport is not default_transport:
            status, payload = self.transport("PUT", session_uri, {"headers": headers, "data": b""})
            if status == 308:
                return {"status": "uploading", "bytes_uploaded": _next_offset_from_range_payload(payload, fallback=0)}
            if status >= 400:
                detail = _provider_error_detail(payload, fallback="Drive resumable upload status check failed")
                raise StorageValidationError(f"Google Drive upload status check failed: {detail}", operation="drive_upload_session.status")
            if not isinstance(payload, dict) or not str(payload.get("id") or "").strip():
                raise StorageValidationError("Google Drive upload status check did not return file metadata.", operation="drive_upload_session.status")
            return {"status": "uploaded", "file": payload}
        try:
            request = Request(session_uri, data=b"", headers=headers, method="PUT")
            with urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
                if not isinstance(payload, dict) or not str(payload.get("id") or "").strip():
                    raise StorageValidationError("Google Drive upload status check did not return file metadata.", operation="drive_upload_session.status")
                return {"status": "uploaded", "file": payload}
        except HTTPError as error:
            if int(error.code) == 308:
                return {"status": "uploading", "bytes_uploaded": _next_offset_from_range_header(error.headers.get("Range"), fallback=0)}
            raise StorageValidationError(
                f"Google Drive upload status check failed: {_http_error_detail(error)}",
                operation="drive_upload_session.status",
            ) from error
        except URLError as error:
            raise DriveProviderError(503, "Google Drive upload status check is currently unavailable.") from error

    def _drive_resumable_cancel_request(self, *, session_uri: str) -> None:
        headers = {"Authorization": f"Bearer {self._token()}"}
        if self.transport is not default_transport:
            status, payload = self.transport("DELETE", session_uri, {"headers": headers})
            if status not in {200, 204, 404, 410} and status >= 400:
                raise DriveProviderError(status, _provider_error_detail(payload, fallback="Drive resumable upload cancel failed"))
            return
        try:
            with urlopen(Request(session_uri, headers=headers, method="DELETE"), timeout=30):
                return
        except HTTPError as error:
            if int(error.code) in {404, 410}:
                return
            raise DriveProviderError(int(error.code), _http_error_detail(error)) from error
        except URLError as error:
            raise DriveProviderError(503, "Google Drive upload cancel is currently unavailable.") from error

    def _drive_bytes_request(self, method: str, path: str, *, params: dict[str, Any] | None = None, max_bytes: int, operation: str) -> bytes:
        query = urlencode({key: value for key, value in (params or {}).items() if value is not None})
        url = f"{DRIVE_API_BASE}{path}" + (f"?{query}" if query else "")
        status, payload = self.transport(
            method,
            url,
            {
                "headers": {"Authorization": f"Bearer {self._token()}"},
                "response_type": "bytes",
                "max_bytes": max_bytes,
            },
        )
        if status >= 400:
            detail = str(payload.get("error", {}).get("message") or payload.get("error") or "Drive request failed") if isinstance(payload, dict) else "Drive request failed"
            if "export" in path and status in {400, 403, 413}:
                detail = f"Google Drive files.export failed or exceeded the {GOOGLE_EXPORT_LIMIT_BYTES} byte export limit: {detail}"
            raise DriveProviderError(status, detail)
        if not isinstance(payload, bytes):
            raise DriveProviderError(status, "Drive did not return file bytes.")
        if len(payload) > max_bytes:
            raise StorageValidationError(f"Drive content exceeds the requested max_bytes limit of {max_bytes}.", operation=operation)
        return payload

    def _drive_bytes_to_path(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        max_bytes: int,
        operation: str,
        target_path: Path,
        declared_size: int = 0,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[int, str]:
        query = urlencode({key: value for key, value in (params or {}).items() if value is not None})
        url = f"{DRIVE_API_BASE}{path}" + (f"?{query}" if query else "")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        sha256 = hashlib.sha256()
        try:
            with urlopen(Request(url, headers={"Authorization": f"Bearer {self._token()}"}, method=method.upper()), timeout=60) as response:
                with target_path.open("wb") as handle:
                    while True:
                        chunk = response.read(DRIVE_STREAM_CHUNK_BYTES)
                        if not chunk:
                            break
                        if total + len(chunk) > max_bytes:
                            raise StorageValidationError(f"Drive content exceeds the requested max_bytes limit of {max_bytes}.", operation=operation)
                        handle.write(chunk)
                        sha256.update(chunk)
                        total += len(chunk)
                        if progress_callback is not None:
                            progress_callback(total, declared_size or total)
                    handle.flush()
                    os.fsync(handle.fileno())
        except HTTPError as error:
            try:
                payload = json.loads(error.read().decode("utf-8") or "{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload = {}
            detail = str(payload.get("error", {}).get("message") or payload.get("error") or "Drive request failed") if isinstance(payload, dict) else "Drive request failed"
            raise DriveProviderError(int(error.code), detail) from error
        except URLError as error:
            raise DriveProviderError(503, "Google Drive media download is currently unavailable.") from error
        if total == 0 and declared_size:
            raise DriveProviderError(502, "Drive returned an empty media response.")
        _validate_declared_stream_size(actual_size=total, declared_size=declared_size, operation=operation)
        return total, sha256.hexdigest()

    def _prepare_drive_bytes_to_path(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        max_bytes: int,
        operation: str,
        target_path: Path,
        declared_size: int,
        file_record: dict[str, Any],
    ) -> PreparedDriveBinaryStream:
        query = urlencode({key: value for key, value in (params or {}).items() if value is not None})
        url = f"{DRIVE_API_BASE}{path}" + (f"?{query}" if query else "")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        request = Request(url, headers={"Authorization": f"Bearer {self._token()}"}, method=method.upper())
        try:
            response = urlopen(request, timeout=60)
            first_chunk = response.read(DRIVE_STREAM_CHUNK_BYTES)
            if declared_size and not first_chunk:
                response.close()
                raise DriveProviderError(502, "Drive returned an empty media response.")
            return PreparedDriveBinaryStream(
                file_record=file_record,
                target_path=target_path,
                declared_size=declared_size,
                max_bytes=max_bytes,
                operation=operation,
                response=response,
                first_chunk=first_chunk,
            )
        except HTTPError as error:
            try:
                payload = json.loads(error.read().decode("utf-8") or "{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload = {}
            detail = str(payload.get("error", {}).get("message") or payload.get("error") or "Drive request failed") if isinstance(payload, dict) else "Drive request failed"
            raise DriveProviderError(int(error.code), detail) from error
        except URLError as error:
            raise DriveProviderError(503, "Google Drive media download is currently unavailable.") from error

    def _finish_prepared_drive_bytes_to_path_and_handle(
        self,
        prepared: PreparedDriveBinaryStream,
        *,
        output_handle: BinaryIO,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[int, str]:
        prepared.target_path.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        sha256 = hashlib.sha256()
        try:
            with prepared.target_path.open("wb") as handle:
                prepared.handle = handle
                if prepared.first_chunk:
                    total = _write_stream_chunk(
                        handle=handle,
                        output_handle=output_handle,
                        sha256=sha256,
                        total=total,
                        chunk=prepared.first_chunk,
                        max_bytes=prepared.max_bytes,
                        operation=prepared.operation,
                        progress_callback=progress_callback,
                        declared_size=prepared.declared_size,
                    )
                while True:
                    chunk = prepared.response.read(DRIVE_STREAM_CHUNK_BYTES) if prepared.response is not None else b""
                    if not chunk:
                        break
                    total = _write_stream_chunk(
                        handle=handle,
                        output_handle=output_handle,
                        sha256=sha256,
                        total=total,
                        chunk=chunk,
                        max_bytes=prepared.max_bytes,
                        operation=prepared.operation,
                        progress_callback=progress_callback,
                        declared_size=prepared.declared_size,
                    )
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            prepared.close()
        _validate_declared_stream_size(actual_size=total, declared_size=prepared.declared_size, operation=prepared.operation)
        return total, sha256.hexdigest()

    def _drive_bytes_to_path_and_handle(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        max_bytes: int,
        operation: str,
        target_path: Path,
        output_handle: BinaryIO,
        declared_size: int = 0,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[int, str]:
        query = urlencode({key: value for key, value in (params or {}).items() if value is not None})
        url = f"{DRIVE_API_BASE}{path}" + (f"?{query}" if query else "")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        sha256 = hashlib.sha256()
        try:
            with urlopen(Request(url, headers={"Authorization": f"Bearer {self._token()}"}, method=method.upper()), timeout=60) as response:
                with target_path.open("wb") as handle:
                    while True:
                        chunk = response.read(DRIVE_STREAM_CHUNK_BYTES)
                        if not chunk:
                            break
                        if total + len(chunk) > max_bytes:
                            raise StorageValidationError(f"Drive content exceeds the requested max_bytes limit of {max_bytes}.", operation=operation)
                        handle.write(chunk)
                        output_handle.write(chunk)
                        flush = getattr(output_handle, "flush", None)
                        if callable(flush):
                            flush()
                        sha256.update(chunk)
                        total += len(chunk)
                        if progress_callback is not None:
                            progress_callback(total, declared_size or total)
                    handle.flush()
                    os.fsync(handle.fileno())
        except HTTPError as error:
            try:
                payload = json.loads(error.read().decode("utf-8") or "{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload = {}
            detail = str(payload.get("error", {}).get("message") or payload.get("error") or "Drive request failed") if isinstance(payload, dict) else "Drive request failed"
            raise DriveProviderError(int(error.code), detail) from error
        except URLError as error:
            raise DriveProviderError(503, "Google Drive media download is currently unavailable.") from error
        if total == 0 and declared_size:
            raise DriveProviderError(502, "Drive returned an empty media response.")
        _validate_declared_stream_size(actual_size=total, declared_size=declared_size, operation=operation)
        return total, sha256.hexdigest()

    def _drive_byte_range_to_path(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        operation: str,
        target_path: Path,
        start: int,
        end: int,
        total_size: int,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[int, str]:
        query = urlencode({key: value for key, value in (params or {}).items() if value is not None})
        url = f"{DRIVE_API_BASE}{path}" + (f"?{query}" if query else "")
        expected_length = end - start + 1
        target_path.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        sha256 = hashlib.sha256()
        request = Request(
            url,
            headers={"Authorization": f"Bearer {self._token()}", "Range": f"bytes={start}-{end}"},
            method=method.upper(),
        )
        try:
            with urlopen(request, timeout=60) as response:
                status = int(getattr(response, "status", 200))
                content_range = str(response.headers.get("Content-Range") or "")
                if status == 206:
                    parsed = _parse_drive_content_range(content_range)
                    if parsed is None:
                        raise StorageValidationError("Drive media response did not include a valid Content-Range header.", operation=operation)
                    range_start, range_end, range_total = parsed
                    if range_start != start or range_end != end:
                        raise StorageValidationError("Drive returned a different media range than Storage requested.", operation=operation)
                    if total_size and range_total and total_size != range_total:
                        raise StorageValidationError("Drive media source size changed; refresh the Storage file record and retry.", operation=operation)
                elif status == 200 and start == 0:
                    pass
                else:
                    raise StorageValidationError("Drive media server did not satisfy the requested byte range.", operation=operation)
                with target_path.open("wb") as handle:
                    while total < expected_length:
                        chunk = response.read(min(DRIVE_STREAM_CHUNK_BYTES, expected_length - total))
                        if not chunk:
                            break
                        handle.write(chunk)
                        sha256.update(chunk)
                        total += len(chunk)
                        if progress_callback is not None:
                            progress_callback(total, expected_length)
                    handle.flush()
                    os.fsync(handle.fileno())
        except HTTPError as error:
            if int(error.code) == 416:
                raise StorageValidationError("Drive media Range header is not satisfiable for this file.", operation=operation) from error
            try:
                payload = json.loads(error.read().decode("utf-8") or "{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload = {}
            detail = str(payload.get("error", {}).get("message") or payload.get("error") or "Drive request failed") if isinstance(payload, dict) else "Drive request failed"
            raise DriveProviderError(int(error.code), detail) from error
        except URLError as error:
            raise DriveProviderError(503, "Google Drive media range download is currently unavailable.") from error
        if total != expected_length:
            raise StorageValidationError("Drive did not return enough bytes for the requested media range.", operation=operation)
        return total, sha256.hexdigest()

    def _active_metadata(self, *, drive_file_id: str, operation: str, file_record: dict[str, Any] | None = None) -> dict[str, Any]:
        file_record = self._usable_cached_file_record(drive_file_id=drive_file_id, file_record=file_record) or self.metadata(drive_file_id=drive_file_id)
        if file_record.get("status") == "removed":
            raise StorageValidationError("Google Drive file is not accessible because it was removed or cannot be found.", operation=operation)
        if file_record.get("status") == "inaccessible":
            raise StorageValidationError("Google Drive file is not accessible with the current Storage Drive connection.", operation=operation)
        return file_record

    def _usable_cached_file_record(self, *, drive_file_id: str, file_record: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(file_record, dict):
            return None
        if file_record.get("provider") != GOOGLE_DRIVE_PROVIDER:
            return None
        if str(file_record.get("connection_id") or "").strip() != self.connection_id:
            return None
        remote_locator = file_record.get("remote_locator") if isinstance(file_record.get("remote_locator"), dict) else {}
        cached_drive_file_id = str(file_record.get("drive_file_id") or remote_locator.get("drive_file_id") or "").strip()
        if cached_drive_file_id != drive_file_id:
            return None
        if str(file_record.get("status") or "active") != "active":
            return file_record
        if not str(file_record.get("content_type") or "").strip():
            return None
        return file_record

    def _require_download_capability(self, file_record: dict[str, Any], *, operation: str) -> None:
        if not _capability(file_record, "can_read") or not _capability(file_record, "can_preview"):
            raise StorageValidationError(
                "Google Drive did not grant download/export permission for this file through the current connection.",
                operation=operation,
            )

    def _require_capability(self, file_record: dict[str, Any], *, capability: str, operation: str, detail: str) -> None:
        if not _capability(file_record, capability):
            raise StorageValidationError(detail, operation=operation)

    def _download_binary(
        self,
        *,
        file_record: dict[str, Any],
        max_bytes: int,
        operation: str,
        validate_declared_size: bool = False,
    ) -> tuple[bytes, bool]:
        declared_size = _int_value(file_record.get("size_bytes"))
        if declared_size and declared_size > max_bytes:
            raise StorageValidationError(f"Drive file is too large to read through Storage with max_bytes={max_bytes}.", operation=operation)
        cache_key = self._cache_key(file_record=file_record, content_mime_type=file_record["content_type"], purpose="download", max_bytes=max_bytes)
        cached = self._read_cache(cache_key)
        if cached is not None:
            if validate_declared_size:
                _validate_declared_stream_size(actual_size=len(cached), declared_size=declared_size, operation=operation)
            return cached, True
        payload = self._drive_bytes_request(
            "GET",
            f"/files/{quote(file_record['drive_file_id'], safe='')}",
            params={"alt": "media", "supportsAllDrives": "true"},
            max_bytes=max_bytes,
            operation=operation,
        )
        if validate_declared_size:
            _validate_declared_stream_size(actual_size=len(payload), declared_size=declared_size, operation=operation)
        self._write_cache(cache_key, payload)
        return payload, False

    def _export_native(self, *, file_record: dict[str, Any], export_mime_type: str, max_bytes: int) -> tuple[bytes, bool]:
        cache_key = self._cache_key(file_record=file_record, content_mime_type=export_mime_type, purpose="export", max_bytes=max_bytes)
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached, True
        try:
            payload = self._drive_bytes_request(
                "GET",
                f"/files/{quote(file_record['drive_file_id'], safe='')}/export",
                params={"mimeType": export_mime_type},
                max_bytes=max_bytes,
                operation="drive_export",
            )
        except DriveProviderError as error:
            if error.status_code in {400, 403, 413}:
                raise StorageValidationError(error.detail, operation="drive_export") from error
            raise
        if len(payload) > GOOGLE_EXPORT_LIMIT_BYTES:
            raise StorageValidationError(
                f"Google Drive files.export returned more than the {GOOGLE_EXPORT_LIMIT_BYTES} byte export limit.",
                operation="drive_export",
            )
        self._write_cache(cache_key, payload)
        return payload, False

    def _cache_key(self, *, file_record: dict[str, Any], content_mime_type: str, purpose: str, max_bytes: int) -> str:
        material = "|".join(
            [
                self.connection_id,
                str(file_record.get("drive_file_id") or ""),
                str(file_record.get("etag_or_version") or file_record.get("modified_at") or ""),
                content_mime_type,
                purpose,
                str(max_bytes),
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _read_cache(self, cache_key: str) -> bytes | None:
        if self.cache_root is None:
            return None
        self._prune_cache()
        metadata_path = self.cache_root / f"{cache_key}.json"
        content_path = self.cache_root / f"{cache_key}.bin"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if time.time() - float(metadata.get("created_at", 0)) > DRIVE_TEMP_CACHE_TTL_SECONDS:
                return None
            if not content_path.is_file() or content_path.stat().st_size > DRIVE_TEMP_CACHE_MAX_ITEM_BYTES:
                return None
            return content_path.read_bytes()
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _write_cache(self, cache_key: str, payload: bytes) -> None:
        if self.cache_root is None or len(payload) > DRIVE_TEMP_CACHE_MAX_ITEM_BYTES:
            return
        self.cache_root.mkdir(parents=True, exist_ok=True)
        (self.cache_root / f"{cache_key}.bin").write_bytes(payload)
        (self.cache_root / f"{cache_key}.json").write_text(json.dumps({"created_at": time.time(), "size_bytes": len(payload)}), encoding="utf-8")
        self._prune_cache()

    def _prune_cache(self) -> None:
        if self.cache_root is None or not self.cache_root.exists():
            return
        entries: list[tuple[float, int, Path, Path]] = []
        now = time.time()
        for content_path in self.cache_root.glob("*.bin"):
            metadata_path = content_path.with_suffix(".json")
            try:
                stat = content_path.stat()
                created_at = stat.st_mtime
                if metadata_path.exists():
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    created_at = float(metadata.get("created_at") or created_at)
                if now - created_at > DRIVE_TEMP_CACHE_TTL_SECONDS or stat.st_size > DRIVE_TEMP_CACHE_MAX_ITEM_BYTES:
                    content_path.unlink(missing_ok=True)
                    metadata_path.unlink(missing_ok=True)
                    continue
                entries.append((created_at, stat.st_size, content_path, metadata_path))
            except (OSError, ValueError, json.JSONDecodeError):
                content_path.unlink(missing_ok=True)
                metadata_path.unlink(missing_ok=True)
        total = sum(size for _, size, _, _ in entries)
        for _created_at, size, content_path, metadata_path in sorted(entries):
            if total <= DRIVE_TEMP_CACHE_MAX_BYTES:
                break
            content_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            total -= size

    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        client_id = _required_secret(self.app_secrets, GOOGLE_DRIVE_CLIENT_ID_SECRET)
        client_secret = _required_secret(self.app_secrets, GOOGLE_DRIVE_CLIENT_SECRET_SECRET)
        refresh_token = _required_secret(self.app_secrets, GOOGLE_DRIVE_REFRESH_TOKEN_SECRET)
        cached_token = self._read_access_token_cache(refresh_token=refresh_token)
        if cached_token:
            self._access_token = cached_token
            return cached_token
        status, payload = self.transport(
            "POST",
            GOOGLE_TOKEN_URL,
            {
                "headers": {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                "data": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            },
        )
        if status >= 400 or not isinstance(payload, dict) or not str(payload.get("access_token") or "").strip():
            raise StorageValidationError("Google Drive access token refresh failed.", operation="drive")
        self._access_token = str(payload["access_token"])
        self._write_access_token_cache(refresh_token=refresh_token, access_token=self._access_token, token_payload=payload)
        return self._access_token

    def _access_token_cache_path(self, *, refresh_token: str) -> Path | None:
        if self.cache_root is None:
            return None
        digest = hashlib.sha256(f"{self.connection_id}\0{refresh_token}".encode("utf-8")).hexdigest()
        return self.cache_root / f"access-token-{digest}.json"

    def _read_access_token_cache(self, *, refresh_token: str) -> str | None:
        path = self._access_token_cache_path(refresh_token=refresh_token)
        if path is None:
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            expires_at = float(payload.get("expires_at") or 0)
            access_token = str(payload.get("access_token") or "").strip()
            if not access_token or expires_at <= time.time() + DRIVE_ACCESS_TOKEN_EXPIRY_SKEW_SECONDS:
                return None
            return access_token
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _write_access_token_cache(self, *, refresh_token: str, access_token: str, token_payload: dict[str, Any]) -> None:
        path = self._access_token_cache_path(refresh_token=refresh_token)
        if path is None:
            return
        expires_in = _int_value(token_payload.get("expires_in")) or DRIVE_ACCESS_TOKEN_CACHE_TTL_SECONDS
        ttl = max(1, min(expires_in - DRIVE_ACCESS_TOKEN_EXPIRY_SKEW_SECONDS, DRIVE_ACCESS_TOKEN_CACHE_TTL_SECONDS))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"access_token": access_token, "expires_at": time.time() + ttl}, ensure_ascii=True), encoding="utf-8")
        path.chmod(0o600)
        self._prune_access_token_cache()

    def _prune_access_token_cache(self) -> None:
        if self.cache_root is None or not self.cache_root.exists():
            return
        cutoff = time.time() - DRIVE_ACCESS_TOKEN_CACHE_TTL_SECONDS
        for path in self.cache_root.glob("access-token-*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if float(payload.get("expires_at") or 0) < cutoff:
                    path.unlink(missing_ok=True)
            except (OSError, ValueError, json.JSONDecodeError):
                path.unlink(missing_ok=True)


def stable_storage_file_id(connection_id: str, drive_file_id: str) -> str:
    digest = hashlib.sha256(f"{connection_id}\0{drive_file_id}".encode("utf-8")).hexdigest()[:32]
    return f"file_{digest}"


def _drive_list_scope(*, corpora: str = "allDrives", drive_id: str = "") -> dict[str, Any]:
    if corpora == "drive" and drive_id:
        return {"corpora": "drive", "driveId": drive_id, "includeItemsFromAllDrives": "true"}
    if corpora == "user":
        return {"corpora": "user"}
    return {"corpora": "allDrives", "includeItemsFromAllDrives": "true"}


def _drive_capabilities(raw_value: object) -> dict[str, bool]:
    capabilities = raw_value if isinstance(raw_value, dict) else {}
    mapped = {
        "can_read": bool(capabilities.get("canDownload", True)),
        "can_write": bool(capabilities.get("canEdit") or capabilities.get("canModifyContent") or capabilities.get("canAddChildren")),
        "can_move": bool(
            capabilities.get("canMoveItemWithinDrive")
            or capabilities.get("canMoveItemOutOfDrive")
            or capabilities.get("canMoveChildrenWithinDrive")
        ),
        "can_rename": bool(capabilities.get("canRename") or capabilities.get("canEdit")),
        "can_delete": bool(capabilities.get("canDelete") or capabilities.get("canTrash")),
        "can_preview": bool(capabilities.get("canDownload", True)),
        "can_index": bool(capabilities.get("canDownload", True)),
    }
    return normalize_capabilities(mapped, provider=GOOGLE_DRIVE_PROVIDER)


def _drive_preview_kind(mime_type: str, extension: str) -> str:
    if mime_type in GOOGLE_NATIVE_PREVIEW_KINDS:
        return GOOGLE_NATIVE_PREVIEW_KINDS[mime_type]
    if mime_type == DRIVE_FOLDER_MIME_TYPE:
        return "folder"
    return preview_kind(mime_type, extension)


def _is_google_native(mime_type: str) -> bool:
    return mime_type in GOOGLE_NATIVE_EXPORTS


def _select_export_mime(source_mime_type: str, requested: str) -> str:
    normalized = str(requested or "readable_text").strip().lower()
    aliases = {
        "": "readable_text",
        "readable": "readable_text",
        "readable_text": "readable_text",
        "text": "text",
        "preview": "preview",
        "pdf": "pdf",
        "docx": "docx",
        "xlsx": "xlsx",
        "pptx": "pptx",
        "csv": "csv",
    }
    export_map = GOOGLE_NATIVE_EXPORTS.get(source_mime_type)
    if export_map is None:
        return str(requested or "").strip()
    key = aliases.get(normalized, str(requested or "").strip())
    if key in export_map:
        return export_map[key]
    if key in export_map.values():
        return key
    raise StorageValidationError(
        "Unsupported Google Drive export format for this file type.",
        operation="drive_export",
        allowed_values={"export_mime_type": sorted(set(export_map) | set(export_map.values()))},
    )


def _content_payload(*, file_record: dict[str, Any], payload: bytes, content_type: str, cache_hit: bool) -> dict[str, Any]:
    return {
        "file": file_record,
        "content_base64": b64encode(payload).decode("ascii"),
        "content_type": content_type,
        "file_name": _export_file_name(file_record["name"], content_type),
        "bytes_read": len(payload),
        "cache_hit": cache_hit,
        "truncated": False,
    }


def _multipart_related_payload(*, boundary: str, metadata: dict[str, Any], content: bytes, content_type: str) -> bytes:
    metadata_bytes = json.dumps(metadata, ensure_ascii=True).encode("utf-8")
    return b"".join(
        [
            f"--{boundary}\r\n".encode("ascii"),
            b"Content-Type: application/json; charset=UTF-8\r\n\r\n",
            metadata_bytes,
            b"\r\n",
            f"--{boundary}\r\n".encode("ascii"),
            f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )


def _required_file_name(value: object, *, operation: str) -> str:
    name = str(value or "").strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise StorageValidationError("file_name/new_name is required and must not contain a path.", operation=operation)
    return name


def _required_content(value: bytes, *, operation: str) -> bytes:
    if not isinstance(value, bytes):
        raise StorageValidationError("Drive write content must be bytes.", operation=operation)
    return value


def _content_type(value: object) -> str:
    return normalize_content_type(value)


def _capability(file_record: dict[str, Any], name: str) -> bool:
    capabilities = file_record.get("capabilities") if isinstance(file_record.get("capabilities"), dict) else {}
    return bool(capabilities.get(name))


def _decode_preview_text(payload: bytes, *, max_chars: int | None) -> str:
    return _decode_preview_text_payload(payload, max_chars=max_chars)["preview_text"]


def _decode_preview_text_payload(payload: bytes, *, max_chars: int | None) -> dict[str, Any]:
    text = payload.decode("utf-8", errors="replace")
    if max_chars is not None and len(text) > max_chars:
        return {"preview_text": text[:max_chars], "preview_truncated": True}
    return {"preview_text": text, "preview_truncated": False}


def _export_file_name(name: str, content_type: str) -> str:
    extension = {
        "text/plain": ".txt",
        "text/csv": ".csv",
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    }.get(content_type, "")
    if not extension or str(name).lower().endswith(extension):
        return name
    return f"{name}{extension}"


def _search_query(query: str) -> str:
    normalized = " ".join(str(query or "").strip().split())
    if len(normalized) > MAX_DRIVE_QUERY_CHARS:
        raise StorageValidationError(f"query must be at most {MAX_DRIVE_QUERY_CHARS} characters.", operation="drive_search")
    if not normalized:
        return "trashed = false"
    lowered = normalized.casefold()
    looks_like_drive_query = any(marker in lowered for marker in ("=", " contains ", " in ", "mimeType".casefold(), "fullText".casefold(), "modifiedTime".casefold(), "name ".casefold()))
    if looks_like_drive_query:
        return normalized if "trashed" in lowered else f"({normalized}) and trashed = false"
    literal = _drive_query_literal(normalized)
    return f"(name contains '{literal}' or fullText contains '{literal}') and trashed = false"


def _drive_query_literal(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _join_display_path(parent: str, name: str) -> str:
    normalized_name = str(name or "").strip()
    normalized_parent = str(parent or "").strip().rstrip("/")
    if not normalized_parent:
        return f"/{normalized_name}" if normalized_name else ""
    return f"{normalized_parent}/{normalized_name}" if normalized_name else normalized_parent


def _bounded_limit(value: int | None, *, default: int = 100) -> int:
    if value is None:
        return default
    try:
        limit = int(value)
    except (TypeError, ValueError) as error:
        raise StorageValidationError("limit must be an integer.", operation="drive") from error
    if limit <= 0:
        raise StorageValidationError("limit must be positive.", operation="drive")
    return min(limit, MAX_DRIVE_PAGE_SIZE)


def _required_secret(app_secrets: dict[str, object], name: str) -> str:
    value = str(app_secrets.get(name) or "").strip()
    if not value:
        raise StorageValidationError("A Google Drive secret grant is required for this operation.", operation="drive")
    return value


def _write_payload_to_path(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _write_stream_chunk(
    *,
    handle: BinaryIO,
    output_handle: BinaryIO,
    sha256: Any,
    total: int,
    chunk: bytes,
    max_bytes: int,
    operation: str,
    progress_callback: Callable[[int, int], None] | None,
    declared_size: int,
) -> int:
    if total + len(chunk) > max_bytes:
        raise StorageValidationError(f"Drive content exceeds the requested max_bytes limit of {max_bytes}.", operation=operation)
    handle.write(chunk)
    output_handle.write(chunk)
    flush = getattr(output_handle, "flush", None)
    if callable(flush):
        flush()
    sha256.update(chunk)
    total += len(chunk)
    if progress_callback is not None:
        progress_callback(total, declared_size or total)
    return total


def _validate_declared_stream_size(*, actual_size: int, declared_size: int, operation: str) -> None:
    if declared_size and actual_size != declared_size:
        raise DriveProviderError(502, f"Drive media response ended after {actual_size} bytes but metadata declared {declared_size} bytes.")


def _write_payload_to_path_and_handle(
    path: Path,
    payload: bytes,
    output_handle: BinaryIO,
    *,
    progress_callback: Callable[[int, int], None] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with path.open("wb") as handle:
        for offset in range(0, len(payload), DRIVE_STREAM_CHUNK_BYTES):
            chunk = payload[offset : offset + DRIVE_STREAM_CHUNK_BYTES]
            handle.write(chunk)
            output_handle.write(chunk)
            flush = getattr(output_handle, "flush", None)
            if callable(flush):
                flush()
            total += len(chunk)
            if progress_callback is not None:
                progress_callback(total, len(payload))
        handle.flush()
        os.fsync(handle.fileno())


def _parse_drive_content_range(value: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", str(value or "").strip())
    if match is None:
        return None
    start = int(match.group(1))
    end = int(match.group(2))
    total = 0 if match.group(3) == "*" else int(match.group(3))
    if end < start:
        return None
    return start, end, total


def _next_offset_from_range_payload(payload: object, *, fallback: int) -> int:
    range_value = ""
    if isinstance(payload, dict):
        range_value = str(payload.get("range") or payload.get("Range") or "").strip()
    return _next_offset_from_range_header(range_value, fallback=fallback)


def _next_offset_from_range_header(value: object, *, fallback: int) -> int:
    normalized = str(value or "").strip()
    match = re.fullmatch(r"bytes=(\d+)-(\d+)", normalized)
    if match is None:
        return fallback
    return int(match.group(2)) + 1


def _provider_error_detail(payload: object, *, fallback: str) -> str:
    if not isinstance(payload, dict):
        return fallback
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or fallback)
    return str(error or payload.get("detail") or fallback)


def _http_error_detail(error: HTTPError) -> str:
    try:
        payload = json.loads(error.read().decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    return _provider_error_detail(payload, fallback="Drive request failed")


def _required_drive_file_id(value: object, *, operation: str) -> str:
    drive_file_id = str(value or "").strip()
    if not drive_file_id:
        raise StorageValidationError("drive_file_id is required.", operation=operation)
    return drive_file_id


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
