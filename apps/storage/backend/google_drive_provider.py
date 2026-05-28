"""Google Drive remote provider for Storage."""

from __future__ import annotations

from base64 import b64decode, b64encode
from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

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

    def list_roots(self, *, limit: int | None = None) -> dict[str, Any]:
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
        try:
            payload = self._drive_request(
                "GET",
                "/drives",
                params={
                    "pageSize": min(page_size, 100),
                    "fields": "nextPageToken,drives(id,name,capabilities(canDeleteDrive,canRenameDrive))",
                },
            )
        except DriveProviderError as error:
            if error.status_code in {400, 403, 404}:
                payload = {"drives": []}
            else:
                raise
        for drive in payload.get("drives") if isinstance(payload.get("drives"), list) else []:
            if not isinstance(drive, dict):
                continue
            drive_id = str(drive.get("id") or "").strip()
            name = str(drive.get("name") or "Shared drive").strip()
            if not drive_id:
                continue
            roots.append(
                self._root_folder(
                    drive_file_id=drive_id,
                    name=name,
                    display_path=f"/Shared drives/{name}",
                    root_kind="shared_drive",
                    capabilities={"can_read": True, "can_move": True},
                )
            )
        return {"provider": GOOGLE_DRIVE_PROVIDER, "connection_id": self.connection_id, "folders": roots[:page_size]}

    def list_children(self, *, parent_drive_file_id: str, limit: int | None = None) -> dict[str, Any]:
        parent_id = _required_drive_file_id(parent_drive_file_id, operation="drive_list_children")
        page_size = _bounded_limit(limit)
        parent_display_path = self._parent_display_path(parent_id)
        if parent_id == SHARED_WITH_ME_ROOT_ID:
            query = "sharedWithMe = true and trashed = false"
        else:
            query = f"'{_drive_query_literal(parent_id)}' in parents and trashed = false"
        items = self._list_files(query=query, limit=page_size)
        return self._split_items(items, parent_display_path=parent_display_path, limit=page_size)

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
        if parent_id:
            parent_display_path = self._parent_display_path(parent_id)
            if parent_id == SHARED_WITH_ME_ROOT_ID:
                drive_query = f"({drive_query}) and sharedWithMe = true"
            else:
                drive_query = f"({drive_query}) and '{_drive_query_literal(parent_id)}' in parents"
        items = self._list_files(query=drive_query, limit=page_size)
        return self._split_items(items, parent_display_path=parent_display_path, limit=page_size)

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

    def read(self, *, drive_file_id: str, max_bytes: int) -> dict[str, Any]:
        """Read bounded Drive file bytes; Google-native files are exported as readable text."""
        file_record = self._active_metadata(drive_file_id=drive_file_id, operation="drive_read")
        if _is_google_native(file_record["content_type"]):
            return self.export(drive_file_id=drive_file_id, export_mime_type="readable_text", max_bytes=max_bytes)
        self._require_download_capability(file_record, operation="drive_read")
        payload, cache_hit = self._download_binary(file_record=file_record, max_bytes=max_bytes, operation="drive_read")
        return _content_payload(file_record=file_record, payload=payload, content_type=file_record["content_type"], cache_hit=cache_hit)

    def preview(self, *, drive_file_id: str, max_bytes: int, max_chars: int | None = None) -> dict[str, Any]:
        """Return a bounded preview through Storage without exposing Google-specific rules."""
        file_record = self._active_metadata(drive_file_id=drive_file_id, operation="drive_preview")
        if _is_google_native(file_record["content_type"]):
            exported = self.export(drive_file_id=drive_file_id, export_mime_type="preview", max_bytes=min(max_bytes, GOOGLE_EXPORT_LIMIT_BYTES))
            preview_text = _decode_preview_text(b64decode(exported["content_base64"]), max_chars=max_chars)
            return {
                "file": file_record,
                "preview_text": preview_text,
                "export_mime_type": exported["content_type"],
                "bytes_read": exported["bytes_read"],
                "cache_hit": exported["cache_hit"],
                "truncated": exported["truncated"],
            }
        self._require_download_capability(file_record, operation="drive_preview")
        payload, cache_hit = self._download_binary(file_record=file_record, max_bytes=max_bytes, operation="drive_preview")
        result = _content_payload(file_record=file_record, payload=payload, content_type=file_record["content_type"], cache_hit=cache_hit)
        if file_record.get("preview_kind") in {"text", "markdown"} or str(file_record.get("content_type") or "").startswith("text/"):
            result["preview_text"] = _decode_preview_text(payload, max_chars=max_chars)
        return result

    def export(self, *, drive_file_id: str, export_mime_type: str, max_bytes: int) -> dict[str, Any]:
        """Export or download a Drive file in a bounded Storage-owned format."""
        file_record = self._active_metadata(drive_file_id=drive_file_id, operation="drive_export")
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

    def _split_items(self, items: list[dict[str, Any]], *, parent_display_path: str, limit: int) -> dict[str, Any]:
        files: list[dict[str, Any]] = []
        folders: list[dict[str, Any]] = []
        for item in items[:limit]:
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
            "pagination": {"limit": limit, "total": len(files) + len(folders), "has_more": len(items) > limit},
        }

    def _list_files(self, *, query: str, limit: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token = ""
        while len(items) <= limit:
            params: dict[str, Any] = {
                "q": query,
                "pageSize": min(limit - len(items) + 1, MAX_DRIVE_PAGE_SIZE),
                "fields": f"nextPageToken,files({DRIVE_FILE_FIELDS})",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
                "corpora": "allDrives",
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self._drive_request("GET", "/files", params=params)
            for item in payload.get("files") if isinstance(payload.get("files"), list) else []:
                if isinstance(item, dict):
                    items.append(item)
            page_token = str(payload.get("nextPageToken") or "")
            if not page_token or len(items) > limit:
                break
        return items

    def _parent_display_path(self, parent_id: str) -> str:
        if parent_id == "root":
            return "/My Drive"
        if parent_id == SHARED_WITH_ME_ROOT_ID:
            return "/Shared with me"
        try:
            parent = self._drive_request(
                "GET",
                f"/files/{quote(parent_id, safe='')}",
                params={"fields": "id,name,mimeType,parents,driveId,trashed", "supportsAllDrives": "true"},
            )
        except DriveProviderError:
            return ""
        return self._display_path_for_item(parent)

    def _display_path_for_item(self, item: dict[str, Any]) -> str:
        names = [str(item.get("name") or "").strip()]
        current = item
        seen = {str(item.get("id") or "")}
        for _depth in range(12):
            parents = current.get("parents") if isinstance(current.get("parents"), list) else []
            parent_id = str(parents[0] if parents else "").strip()
            if not parent_id or parent_id in seen:
                break
            if parent_id == "root":
                names.append("My Drive")
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
                names.append(parent_name)
        names = [name for name in reversed(names) if name]
        return "/" + "/".join(names) if names else ""

    def _normalize_item(self, item: dict[str, Any], *, display_path: str) -> dict[str, Any]:
        drive_file_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or drive_file_id).strip()
        mime_type = str(item.get("mimeType") or "application/octet-stream").strip()
        status = "removed" if bool(item.get("trashed") or item.get("explicitlyTrashed")) else "active"
        stable_id = stable_storage_file_id(self.connection_id, drive_file_id)
        version = str(item.get("headRevisionId") or item.get("version") or item.get("modifiedTime") or "")
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

    def _active_metadata(self, *, drive_file_id: str, operation: str) -> dict[str, Any]:
        file_record = self.metadata(drive_file_id=drive_file_id)
        if file_record.get("status") == "removed":
            raise StorageValidationError("Google Drive file is not accessible because it was removed or cannot be found.", operation=operation)
        if file_record.get("status") == "inaccessible":
            raise StorageValidationError("Google Drive file is not accessible with the current Storage Drive connection.", operation=operation)
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

    def _download_binary(self, *, file_record: dict[str, Any], max_bytes: int, operation: str) -> tuple[bytes, bool]:
        declared_size = _int_value(file_record.get("size_bytes"))
        if declared_size and declared_size > max_bytes:
            raise StorageValidationError(f"Drive file is too large to read through Storage with max_bytes={max_bytes}.", operation=operation)
        cache_key = self._cache_key(file_record=file_record, content_mime_type=file_record["content_type"], purpose="download", max_bytes=max_bytes)
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached, True
        payload = self._drive_bytes_request(
            "GET",
            f"/files/{quote(file_record['drive_file_id'], safe='')}",
            params={"alt": "media", "supportsAllDrives": "true"},
            max_bytes=max_bytes,
            operation=operation,
        )
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
        return self._access_token


def stable_storage_file_id(connection_id: str, drive_file_id: str) -> str:
    digest = hashlib.sha256(f"{connection_id}\0{drive_file_id}".encode("utf-8")).hexdigest()[:32]
    return f"file_{digest}"


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
    normalized = str(value or "").strip()
    return normalized or "application/octet-stream"


def _capability(file_record: dict[str, Any], name: str) -> bool:
    capabilities = file_record.get("capabilities") if isinstance(file_record.get("capabilities"), dict) else {}
    return bool(capabilities.get(name))


def _decode_preview_text(payload: bytes, *, max_chars: int | None) -> str:
    text = payload.decode("utf-8", errors="replace")
    if max_chars is not None and len(text) > max_chars:
        return text[:max_chars]
    return text


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
