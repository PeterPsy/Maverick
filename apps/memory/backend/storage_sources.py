"""Remote Storage source helpers for Memory ingestion."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from typing import Any

from database import json_text
from errors import MemoryValidationError


REMOTE_STORAGE_PROVIDERS = {"google_drive"}
MAX_REMOTE_PREVIEW_CHARS = 20000
MAX_REMOTE_PREVIEW_BYTES = 5 * 1024 * 1024


def default_storage_preview_surface(data_root: Path, request: dict[str, Any]) -> dict[str, Any]:
    workspace_root = workspace_root_for_data_root(data_root)
    if workspace_root is None:
        raise MemoryValidationError("Memory data_root must live under a workspace data directory for Storage ingestion.")
    if shutil.which("maverick"):
        return platform_storage_preview(workspace_root, request)
    return local_storage_preview(workspace_root, request)


def platform_storage_preview(workspace_root: Path, request: dict[str, Any]) -> dict[str, Any]:
    arguments = {
        key: value
        for key, value in request.items()
        if key in {"connection_id", "drive_file_id", "stable_storage_file_id", "max_chars", "max_bytes"}
    }
    completed = subprocess.run(
        [
            "maverick",
            "app",
            "storage",
            "mcp",
            "call",
            "storage_drive_preview",
            "--json",
            "--arguments",
            json.dumps(arguments, sort_keys=True),
        ],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    try:
        response = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as error:
        raise MemoryValidationError("Storage preview surface returned invalid JSON.") from error
    if completed.returncode != 0:
        raise MemoryValidationError(str(response.get("detail") or response.get("error") or "Storage preview surface failed."))
    status_code = int(response.get("status_code") or 200)
    if status_code >= 400:
        raise MemoryValidationError(str(response.get("detail") or response.get("error") or "Storage preview failed."))
    return response


def local_storage_preview(workspace_root: Path, request: dict[str, Any]) -> dict[str, Any]:
    storage_root = Path(__file__).resolve().parents[2] / "storage"
    payload = {
        "app_id": "storage",
        "workspace_id": workspace_root.name,
        "data_root": str(workspace_root / "data" / "storage"),
        "uploaded_storage_root": str(workspace_root / "storage" / "uploaded"),
        "generated_storage_root": str(workspace_root / "storage" / "generated"),
        "body": request,
    }
    completed = subprocess.run(
        [sys.executable, str(storage_root / "backend" / "app_backend.py")],
        cwd=storage_root,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise MemoryValidationError("Storage preview surface failed.")
    try:
        response = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as error:
        raise MemoryValidationError("Storage preview surface returned invalid JSON.") from error
    status_code = int(response.get("status_code") or 500)
    result = response.get("json") if isinstance(response.get("json"), dict) else {}
    if status_code >= 400:
        detail = str(result.get("detail") or result.get("error") or "Storage preview failed.")
        raise MemoryValidationError(detail)
    return result


_storage_preview_surface = default_storage_preview_surface


def remote_storage_snapshot(
    ref: sqlite3.Row,
    metadata: dict[str, Any],
    data_root: Path | None,
    *,
    include_preview: bool,
) -> dict[str, Any]:
    provider = str(metadata.get("provider") or "").strip()
    connection_id = str(metadata.get("connection_id") or "").strip()
    drive_file_id = str(metadata.get("drive_file_id") or "").strip()
    source_version = str(metadata.get("source_version") or "").strip()
    display_path = str(metadata.get("display_path") or "").strip()
    preview_payload: dict[str, Any] = {}
    preview_text = ""
    if include_preview:
        if data_root is None:
            raise MemoryValidationError("data_root is required to ingest remote Storage files.")
        preview_payload = _storage_preview_surface(data_root, remote_preview_request(ref, metadata))
        preview_text = str(preview_payload.get("preview_text") or "")
        file_payload = preview_payload.get("file") if isinstance(preview_payload.get("file"), dict) else {}
        source_version = str(
            preview_payload.get("source_version")
            or file_payload.get("source_version")
            or file_payload.get("etag_or_version")
            or file_payload.get("modified_at")
            or source_version
            or ""
        )
        display_path = str(file_payload.get("display_path") or display_path or "")
    return {
        "hash": sha256(
            json.dumps(
                remote_hash_payload(
                    ref,
                    provider=provider,
                    connection_id=connection_id,
                    drive_file_id=drive_file_id,
                    source_version=source_version,
                    display_path=display_path,
                ),
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest(),
        "hash_kind": "remote_storage_preview" if include_preview else "remote_storage_reference",
        "extracted_text": preview_text,
        "extracted_ref": display_path or str(ref["entity_id"] or ref["file_id"] or ""),
        "metadata": {
            "provider": provider,
            "connection_id": connection_id,
            "drive_file_id": drive_file_id,
            "source_version": source_version,
            "display_path": display_path,
            "preview_truncated": bool(preview_payload.get("truncated")) if include_preview else False,
        },
    }


def remote_preview_request(ref: sqlite3.Row, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "drive_preview",
        "provider": str(metadata.get("provider") or ""),
        "stable_storage_file_id": str(ref["entity_id"] or ref["file_id"] or ""),
        "connection_id": str(metadata.get("connection_id") or ""),
        "drive_file_id": str(metadata.get("drive_file_id") or ""),
        "max_chars": MAX_REMOTE_PREVIEW_CHARS,
        "max_bytes": MAX_REMOTE_PREVIEW_BYTES,
    }


def remote_hash_payload(
    ref: sqlite3.Row,
    *,
    provider: str,
    connection_id: str,
    drive_file_id: str,
    source_version: str,
    display_path: str,
) -> dict[str, Any]:
    return {
        "ref_kind": str(ref["ref_kind"] or ""),
        "owning_app_id": str(ref["owning_app_id"] or ""),
        "entity_type": str(ref["entity_type"] or ""),
        "entity_id": str(ref["entity_id"] or ""),
        "file_id": str(ref["file_id"] or ""),
        "title": str(ref["title"] or ""),
        "provider": provider,
        "connection_id": connection_id,
        "drive_file_id": drive_file_id,
        "source_version": source_version,
        "display_path": display_path,
        "storage_staleness": storage_ref_staleness(ref),
    }


def ref_metadata(ref: sqlite3.Row) -> dict[str, Any]:
    try:
        metadata = json.loads(ref["metadata_json"] or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return metadata if isinstance(metadata, dict) else {}


def is_remote_storage_ref(ref: sqlite3.Row, metadata: dict[str, Any] | None = None) -> bool:
    metadata = metadata if metadata is not None else ref_metadata(ref)
    return str(ref["ref_kind"] or "") == "remote_storage_file" or str(metadata.get("provider") or "") in REMOTE_STORAGE_PROVIDERS


def storage_ref_staleness(ref: sqlite3.Row) -> dict[str, Any] | None:
    metadata = ref_metadata(ref)
    staleness = metadata.get("staleness")
    if isinstance(staleness, dict) and staleness:
        return {"source": "storage", **staleness}
    if isinstance(staleness, str) and staleness.strip():
        return {"source": "storage", "state": staleness.strip()}
    if bool(metadata.get("stale")):
        return {"source": "storage", "state": "stale", "reason": str(metadata.get("stale_reason") or "")}
    sync_state = metadata.get("sync_state")
    if isinstance(sync_state, dict):
        status = str(sync_state.get("status") or "").strip()
        if status and status not in {"healthy", "synced", "idle"}:
            return {
                "source": "storage",
                "state": "stale",
                "sync_status": status,
                "reason": str(sync_state.get("reason") or sync_state.get("error") or ""),
            }
    return None


def update_remote_ref_metadata(
    db: sqlite3.Connection,
    ref: sqlite3.Row,
    snapshot: dict[str, Any],
    *,
    timestamp: str,
) -> None:
    if not snapshot.get("metadata") or not is_remote_storage_ref(ref):
        return
    metadata = ref_metadata(ref)
    metadata.update(snapshot["metadata"])
    db.execute(
        "UPDATE external_refs SET metadata_json = ?, updated_at = ? WHERE id = ?",
        (json_text(metadata), timestamp, ref["id"]),
    )


def workspace_root_for_data_root(data_root: Path) -> Path | None:
    if data_root.parent.name != "data":
        return None
    return data_root.parent.parent
