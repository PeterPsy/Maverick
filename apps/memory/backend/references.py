"""External reference persistence operations for Memory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from database import ensure_schema, json_text, new_id, now_timestamp, record_event, row_payload, transaction
from errors import MemoryValidationError
from lint import mark_wiki_stale


REMOTE_STORAGE_PROVIDERS = {"google_drive"}
LOCAL_STORAGE_PROVIDERS = {"", "local"}
STORAGE_REF_KINDS = {"workspace_file", "local_storage_file", "remote_storage_file"}


def validate_workspace_relative_path(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    path = Path(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise MemoryValidationError("workspace_relative_path must stay inside the workspace.")
    if not normalized.startswith(("storage/uploaded/", "storage/generated/")):
        raise MemoryValidationError("workspace_relative_path must point to workspace storage.")
    return path.as_posix()


def metadata_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def storage_provider(body: dict[str, Any], metadata: dict[str, Any]) -> str:
    return str(body.get("provider") or metadata.get("provider") or "").strip()


def storage_ref_kind(body: dict[str, Any], *, requested_ref_kind: str, metadata: dict[str, Any]) -> str:
    if requested_ref_kind not in STORAGE_REF_KINDS:
        return requested_ref_kind
    provider = storage_provider(body, metadata)
    if provider in REMOTE_STORAGE_PROVIDERS:
        return "remote_storage_file"
    return "local_storage_file"


def validate_storage_ref(ref: dict[str, Any], *, metadata: dict[str, Any], provider: str) -> None:
    if ref["ref_kind"] == "remote_storage_file":
        if provider not in REMOTE_STORAGE_PROVIDERS:
            raise MemoryValidationError("remote_storage_file requires a supported remote provider.")
        if ref["workspace_relative_path"]:
            raise MemoryValidationError("workspace_relative_path is only valid for local Storage files.")
        if ref["owning_app_id"] != "storage" or ref["entity_type"] != "file":
            raise MemoryValidationError("remote_storage_file must reference owning_app_id=storage and entity_type=file.")
        if not ref["entity_id"].startswith("file_"):
            raise MemoryValidationError("remote_storage_file requires a stable Storage file entity_id.")
        if provider == "google_drive":
            missing = [
                field
                for field in ("connection_id", "drive_file_id")
                if not str(metadata.get(field) or "").strip()
            ]
            if missing:
                raise MemoryValidationError(f"remote_storage_file metadata is missing {', '.join(missing)}.")
        return
    if ref["ref_kind"] == "local_storage_file":
        if provider not in LOCAL_STORAGE_PROVIDERS:
            raise MemoryValidationError("remote Storage providers must use remote_storage_file.")
        if not (ref["file_id"] or ref["workspace_relative_path"] or ref["entity_id"]):
            raise MemoryValidationError("file_id, entity_id, or workspace_relative_path is required.")


def add_external_ref(data_root: Path, body: dict[str, Any], *, ref_kind: str) -> dict[str, Any]:
    ensure_schema(data_root)
    node_id = str(body.get("node_id") or body.get("node") or "").strip()
    if not node_id:
        raise MemoryValidationError("node_id is required.")
    timestamp = now_timestamp()
    metadata = metadata_dict(body.get("metadata"))
    provider = storage_provider(body, metadata)
    normalized_ref_kind = storage_ref_kind(body, requested_ref_kind=ref_kind, metadata=metadata)
    workspace_relative_path = ""
    if provider not in REMOTE_STORAGE_PROVIDERS:
        workspace_relative_path = validate_workspace_relative_path(str(body.get("workspace_relative_path") or ""))
    elif str(body.get("workspace_relative_path") or "").strip():
        raise MemoryValidationError("workspace_relative_path is only valid for local Storage files.")
    if provider and "provider" not in metadata:
        metadata["provider"] = provider
    ref = {
        "id": str(body.get("external_ref_id") or body.get("id") or new_id("ref")),
        "node_id": node_id,
        "ref_kind": normalized_ref_kind,
        "owning_app_id": str(body.get("owning_app_id") or body.get("app") or ("storage" if normalized_ref_kind in STORAGE_REF_KINDS else "")).strip(),
        "entity_type": str(body.get("entity_type") or body.get("type") or ("file" if normalized_ref_kind in STORAGE_REF_KINDS else "")).strip(),
        "entity_id": str(body.get("entity_id") or "").strip(),
        "file_id": str(body.get("file_id") or "").strip(),
        "workspace_relative_path": workspace_relative_path,
        "uri": str(body.get("uri") or "").strip(),
        "title": str(body.get("title") or "").strip(),
        "metadata_json": json_text(metadata),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    if normalized_ref_kind in STORAGE_REF_KINDS:
        validate_storage_ref(ref, metadata=metadata, provider=provider)
    if normalized_ref_kind == "app_entity" and not (ref["owning_app_id"] and ref["entity_type"] and ref["entity_id"]):
        raise MemoryValidationError("owning_app_id, entity_type, and entity_id are required.")
    with transaction(data_root, immediate=True) as db:
        if db.execute("SELECT id FROM nodes WHERE id = ? AND status = 'active'", (node_id,)).fetchone() is None:
            raise MemoryValidationError("node not found.")
        db.execute(
            """
            INSERT INTO external_refs(id, node_id, ref_kind, owning_app_id, entity_type, entity_id, file_id,
              workspace_relative_path, uri, title, metadata_json, created_at, updated_at)
            VALUES (:id, :node_id, :ref_kind, :owning_app_id, :entity_type, :entity_id, :file_id,
              :workspace_relative_path, :uri, :title, :metadata_json, :created_at, :updated_at)
            """,
            ref,
        )
        record_event(
            db,
            event_type="file_attached" if normalized_ref_kind in STORAGE_REF_KINDS else "app_entity_attached",
            node_id=node_id,
            external_ref_id=ref["id"],
            payload=ref,
        )
        mark_wiki_stale(db, node_id, timestamp=timestamp, reason="reference_attached", data_root=data_root)
        return row_payload(db.execute("SELECT * FROM external_refs WHERE id = ?", (ref["id"],)).fetchone()) or {}
