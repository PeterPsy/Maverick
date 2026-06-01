"""Agent-facing Storage reference payloads for Memory retrieval."""

from __future__ import annotations

import sqlite3
from typing import Any
from urllib.parse import quote

from database import row_payload


STORAGE_REF_KINDS = {"workspace_file", "local_storage_file", "remote_storage_file"}


def storage_references_for_node(db: sqlite3.Connection, node_id: str) -> list[dict[str, Any]]:
    references = []
    for row in db.execute(
        """
        SELECT *
        FROM external_refs
        WHERE node_id = ?
          AND (ref_kind IN ('workspace_file', 'local_storage_file', 'remote_storage_file')
               OR owning_app_id = 'storage')
        ORDER BY created_at
        """,
        (node_id,),
    ):
        reference = storage_reference_payload(row_payload(row) or {})
        if reference:
            references.append(reference)
    return references


def storage_reference_for_citation(db: sqlite3.Connection, citation: dict[str, Any]) -> dict[str, Any] | None:
    external_ref_id = str(citation.get("external_ref_id") or "").strip()
    if external_ref_id:
        row = db.execute("SELECT * FROM external_refs WHERE id = ?", (external_ref_id,)).fetchone()
        reference = storage_reference_payload(row_payload(row) or {}) if row is not None else None
        if reference:
            return reference
    source_id = str(citation.get("source_id") or "").strip()
    if source_id:
        row = db.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        return storage_reference_payload(row_payload(row) or {}) if row is not None else None
    return None


def storage_reference_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    ref_kind = str(payload.get("ref_kind") or payload.get("source_kind") or "").strip()
    owning_app_id = str(payload.get("owning_app_id") or "").strip()
    entity_type = str(payload.get("entity_type") or "").strip()
    if ref_kind not in STORAGE_REF_KINDS and owning_app_id != "storage":
        return None
    if owning_app_id and owning_app_id != "storage":
        return None
    entity_id = str(payload.get("entity_id") or payload.get("file_id") or "").strip()
    file_id = str(payload.get("file_id") or entity_id).strip()
    workspace_relative_path = str(payload.get("workspace_relative_path") or "").strip()
    provider = str(metadata.get("provider") or "").strip()
    stable_storage_file_id = entity_id if provider == "google_drive" else file_id
    display_path = str(metadata.get("display_path") or workspace_relative_path or "").strip()
    title = str(payload.get("title") or display_path or entity_id or file_id).strip()
    reference = {
        "app_id": "storage",
        "owning_app_id": "storage",
        "entity_type": entity_type or "file",
        "entity_id": entity_id,
        "file_id": file_id,
        "stable_storage_file_id": stable_storage_file_id,
        "ref_kind": ref_kind or "local_storage_file",
        "title": title,
        "display_path": display_path,
        "workspace_relative_path": workspace_relative_path,
        "provider": provider,
        "connection_id": str(metadata.get("connection_id") or "").strip(),
        "drive_file_id": str(metadata.get("drive_file_id") or "").strip(),
        "source_version": str(metadata.get("source_version") or "").strip(),
        "deep_link": storage_deep_link(entity_id),
        "reference_resolve_request": {
            "tool": "storage_reference_resolve",
            "arguments": {
                "entity_type": entity_type or "file",
                "entity_id": entity_id,
            },
        },
    }
    preview_request = storage_preview_request(reference)
    if preview_request:
        reference["preview_request"] = preview_request
    export_request = storage_export_request(reference)
    if export_request:
        reference["export_request"] = export_request
    return reference


def storage_deep_link(entity_id: str) -> str:
    if not entity_id:
        return ""
    return f"/app/storage/files/{quote(entity_id, safe='')}"


def storage_preview_request(reference: dict[str, Any]) -> dict[str, Any] | None:
    if reference.get("provider") == "google_drive":
        arguments = {
            "stable_storage_file_id": reference.get("stable_storage_file_id") or reference.get("entity_id"),
            "connection_id": reference.get("connection_id") or "",
            "drive_file_id": reference.get("drive_file_id") or "",
        }
        return {"tool": "storage_drive_preview", "arguments": arguments}
    if reference.get("entity_id"):
        return {
            "tool": "storage_reference_resolve",
            "arguments": {"entity_type": reference.get("entity_type") or "file", "entity_id": reference["entity_id"]},
        }
    return None


def storage_export_request(reference: dict[str, Any]) -> dict[str, Any] | None:
    if reference.get("provider") != "google_drive":
        return None
    return {
        "tool": "storage_drive_export",
        "arguments": {
            "stable_storage_file_id": reference.get("stable_storage_file_id") or reference.get("entity_id"),
            "connection_id": reference.get("connection_id") or "",
            "drive_file_id": reference.get("drive_file_id") or "",
        },
    }
