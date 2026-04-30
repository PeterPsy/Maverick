"""External reference persistence operations for Memory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from errors import MemoryValidationError
from database import connect, ensure_schema, json_text, new_id, now_timestamp, record_event, row_payload

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


def add_external_ref(data_root: Path, body: dict[str, Any], *, ref_kind: str) -> dict[str, Any]:
    ensure_schema(data_root)
    node_id = str(body.get("node_id") or body.get("node") or "").strip()
    if not node_id:
        raise MemoryValidationError("node_id is required.")
    timestamp = now_timestamp()
    ref = {
        "id": str(body.get("external_ref_id") or body.get("id") or new_id("ref")),
        "node_id": node_id,
        "ref_kind": ref_kind,
        "owning_app_id": str(body.get("owning_app_id") or body.get("app") or ("gallery" if ref_kind == "workspace_file" else "")).strip(),
        "entity_type": str(body.get("entity_type") or body.get("type") or ("file" if ref_kind == "workspace_file" else "")).strip(),
        "entity_id": str(body.get("entity_id") or "").strip(),
        "file_id": str(body.get("file_id") or "").strip(),
        "workspace_relative_path": validate_workspace_relative_path(str(body.get("workspace_relative_path") or "")),
        "uri": str(body.get("uri") or "").strip(),
        "title": str(body.get("title") or "").strip(),
        "metadata_json": json_text(body.get("metadata")),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    if ref_kind == "workspace_file" and not (ref["file_id"] or ref["workspace_relative_path"]):
        raise MemoryValidationError("file_id or workspace_relative_path is required.")
    if ref_kind == "app_entity" and not (ref["owning_app_id"] and ref["entity_type"] and ref["entity_id"]):
        raise MemoryValidationError("owning_app_id, entity_type, and entity_id are required.")
    with connect(data_root) as db:
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
            event_type="file_attached" if ref_kind == "workspace_file" else "app_entity_attached",
            node_id=node_id,
            external_ref_id=ref["id"],
            payload=ref,
        )
        return row_payload(db.execute("SELECT * FROM external_refs WHERE id = ?", (ref["id"],)).fetchone()) or {}
