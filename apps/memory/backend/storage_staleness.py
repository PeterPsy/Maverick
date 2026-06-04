"""Storage staleness propagation for Memory."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from database import ensure_schema, json_text, now_timestamp, record_event, row_payload, transaction
from errors import MemoryValidationError
from ingest_jobs import enqueue_job_in_db
from lint import mark_wiki_stale
from storage_sources import ref_metadata


def apply_storage_staleness(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    """Apply a Storage memory_staleness payload to linked Memory nodes."""

    ensure_schema(data_root)
    request = normalize_staleness_request(body)
    timestamp = now_timestamp()
    with transaction(data_root, immediate=True) as db:
        refs = find_storage_refs(db, request)
        grouped: dict[str, dict[str, Any]] = {}
        for ref in refs:
            update_ref_staleness(db, ref, request, timestamp=timestamp)
            mark_source_rows_stale(db, ref, request, timestamp=timestamp)
            node_id = str(ref["node_id"] or "")
            if node_id not in grouped:
                node = db.execute("SELECT id, title FROM nodes WHERE id = ?", (node_id,)).fetchone()
                grouped[node_id] = {
                    "node_id": node_id,
                    "title": str(node["title"] or "") if node is not None else "",
                    "external_ref_ids": [],
                    "compiled_wiki_stale": False,
                    "claims_marked_stale": 0,
                }
            grouped[node_id]["external_ref_ids"].append(str(ref["id"] or ""))

        impacted_nodes: list[dict[str, Any]] = []
        for node_id, item in grouped.items():
            item["claims_marked_stale"] = active_claim_count(db, node_id)
            item["compiled_wiki_stale"] = mark_wiki_stale(
                db,
                node_id,
                timestamp=timestamp,
                reason=request["reason"],
                data_root=data_root,
            )
            record_event(
                db,
                event_type="storage_staleness_applied",
                node_id=node_id,
                external_ref_id=item["external_ref_ids"][0] if item["external_ref_ids"] else None,
                payload={
                    "owning_app_id": request["owning_app_id"],
                    "entity_type": request["entity_type"],
                    "entity_id": request["entity_id"],
                    "reason": request["reason"],
                    "external_ref_ids": item["external_ref_ids"],
                },
            )
            impacted_nodes.append(item)
        reindex_job = None
        if impacted_nodes:
            reindex_job = enqueue_job_in_db(
                db,
                job_type="requires_storage_reindex",
                dedupe_key=f"requires_storage_reindex:{request['entity_id']}",
                payload={
                    "reason": request["reason"],
                    "storage_identity": {
                        "owning_app_id": request["owning_app_id"],
                        "entity_type": request["entity_type"],
                        "entity_id": request["entity_id"],
                    },
                    "impacted_node_ids": [item["node_id"] for item in impacted_nodes],
                    "reindex_suggestion": reindex_suggestion(request),
                },
            )

    return {
        "status": "applied" if impacted_nodes else "not_found",
        "storage_identity": {
            "owning_app_id": request["owning_app_id"],
            "entity_type": request["entity_type"],
            "entity_id": request["entity_id"],
        },
        "reason": request["reason"],
        "impacted_nodes": impacted_nodes,
        "reindex_suggestion": reindex_suggestion(request),
        "reindex_job": reindex_job,
    }


def normalize_staleness_request(body: dict[str, Any]) -> dict[str, Any]:
    payload = body.get("memory_staleness") if isinstance(body.get("memory_staleness"), dict) else body
    owning_app_id = str(payload.get("owning_app_id") or "").strip()
    entity_type = str(payload.get("entity_type") or "").strip()
    entity_id = str(payload.get("entity_id") or payload.get("file_id") or "").strip()
    reason = str(payload.get("reason") or "storage_sync").strip()
    if owning_app_id != "storage":
        raise MemoryValidationError("apply_storage_staleness requires owning_app_id=storage.")
    if entity_type != "file":
        raise MemoryValidationError("apply_storage_staleness requires entity_type=file.")
    if not entity_id:
        raise MemoryValidationError("entity_id is required.")
    sync_state = payload.get("sync_state") if isinstance(payload.get("sync_state"), dict) else {}
    staleness = payload.get("staleness") if isinstance(payload.get("staleness"), dict) else {}
    for key in ("connection_id", "drive_file_id", "source_version", "indexed_source_version"):
        value = str(payload.get(key) or "").strip()
        if value:
            staleness[key] = value
    return {
        "owning_app_id": owning_app_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "reason": reason,
        "sync_state": dict(sync_state),
        "staleness": dict(staleness),
    }


def find_storage_refs(db: sqlite3.Connection, request: dict[str, Any]) -> list[sqlite3.Row]:
    return list(
        db.execute(
            """
            SELECT *
            FROM external_refs
            WHERE owning_app_id = ?
              AND entity_type = ?
              AND (entity_id = ? OR file_id = ?)
            ORDER BY node_id, created_at
            """,
            (request["owning_app_id"], request["entity_type"], request["entity_id"], request["entity_id"]),
        )
    )


def update_ref_staleness(
    db: sqlite3.Connection,
    ref: sqlite3.Row,
    request: dict[str, Any],
    *,
    timestamp: str,
) -> None:
    metadata = ref_metadata(ref)
    existing_staleness = metadata.get("staleness") if isinstance(metadata.get("staleness"), dict) else {}
    existing_sync_state = metadata.get("sync_state") if isinstance(metadata.get("sync_state"), dict) else {}
    metadata["stale"] = True
    metadata["stale_reason"] = request["reason"]
    metadata["staleness"] = {
        **existing_staleness,
        **request["staleness"],
        "state": "stale",
        "reason": request["reason"],
        "observed_at": timestamp,
        "owning_app_id": request["owning_app_id"],
        "entity_type": request["entity_type"],
        "entity_id": request["entity_id"],
    }
    metadata["sync_state"] = {
        **existing_sync_state,
        **request["sync_state"],
        "status": str(request["sync_state"].get("status") or "stale"),
        "reason": str(request["sync_state"].get("reason") or request["sync_state"].get("error") or request["reason"]),
        "last_staleness_at": timestamp,
    }
    db.execute(
        "UPDATE external_refs SET metadata_json = ?, updated_at = ? WHERE id = ?",
        (json_text(metadata), timestamp, ref["id"]),
    )


def mark_source_rows_stale(
    db: sqlite3.Connection,
    ref: sqlite3.Row,
    request: dict[str, Any],
    *,
    timestamp: str,
) -> None:
    sources = list(
        db.execute(
            """
            SELECT *
            FROM sources
            WHERE external_ref_id = ?
               OR (
                    owning_app_id = ?
                AND entity_type = ?
                AND (entity_id = ? OR file_id = ?)
               )
            """,
            (ref["id"], request["owning_app_id"], request["entity_type"], request["entity_id"], request["entity_id"]),
        )
    )
    if not sources:
        return
    source_ids = [str(source["id"] or "") for source in sources if source["id"]]
    for source in sources:
        update_row_metadata(db, "sources", str(source["id"]), request, timestamp=timestamp)
    placeholders = ",".join("?" for _item in source_ids)
    versions = list(
        db.execute(
            f"SELECT * FROM source_versions WHERE source_id IN ({placeholders})",
            tuple(source_ids),
        )
    )
    source_document_ids = sorted({str(version["source_document_id"] or "") for version in versions if version["source_document_id"]})
    for version in versions:
        update_row_metadata(db, "source_versions", str(version["id"]), request, timestamp=timestamp)
    version_ids = [str(version["id"] or "") for version in versions if version["id"]]
    if version_ids:
        version_placeholders = ",".join("?" for _item in version_ids)
        for chunk in db.execute(
            f"SELECT * FROM source_chunks WHERE source_version_id IN ({version_placeholders})",
            tuple(version_ids),
        ):
            update_row_metadata(db, "source_chunks", str(chunk["id"]), request, timestamp=timestamp)
    for source_document_id in source_document_ids:
        update_row_metadata(db, "source_documents", source_document_id, request, timestamp=timestamp)


def update_row_metadata(
    db: sqlite3.Connection,
    table_name: str,
    row_id: str,
    request: dict[str, Any],
    *,
    timestamp: str,
) -> None:
    row = db.execute(f"SELECT * FROM {table_name} WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        return
    payload = row_payload(row) or {}
    metadata = dict(payload.get("metadata") or {})
    existing_staleness = metadata.get("staleness") if isinstance(metadata.get("staleness"), dict) else {}
    metadata["stale"] = True
    metadata["stale_reason"] = request["reason"]
    metadata["staleness"] = {
        **existing_staleness,
        **request["staleness"],
        "state": "stale",
        "reason": request["reason"],
        "observed_at": timestamp,
        "owning_app_id": request["owning_app_id"],
        "entity_type": request["entity_type"],
        "entity_id": request["entity_id"],
    }
    if table_name in {"sources", "source_documents"}:
        db.execute(f"UPDATE {table_name} SET metadata_json = ?, updated_at = ? WHERE id = ?", (json_text(metadata), timestamp, row_id))
    else:
        db.execute(f"UPDATE {table_name} SET metadata_json = ? WHERE id = ?", (json_text(metadata), row_id))


def active_claim_count(db: sqlite3.Connection, node_id: str) -> int:
    row = db.execute(
        "SELECT COUNT(*) AS count FROM claims WHERE node_id = ? AND status = 'active'",
        (node_id,),
    ).fetchone()
    return int(row["count"] if row is not None else 0)


def reindex_suggestion(request: dict[str, Any]) -> dict[str, Any]:
    arguments = {"stable_storage_file_id": request["entity_id"]}
    connection_id = str(request["staleness"].get("connection_id") or "")
    drive_file_id = str(request["staleness"].get("drive_file_id") or "")
    if connection_id:
        arguments["connection_id"] = connection_id
    if drive_file_id:
        arguments["drive_file_id"] = drive_file_id
    return {
        "reason": request["reason"],
        "storage_action": "drive_index",
        "memory_action": "ingest_storage_source",
        "mcp_tool": "storage_drive_index",
        "arguments": arguments,
        "next_step": "Run Storage drive_index for this file, then pass memory_source to Memory ingest_storage_source with compile_after_ingest=true.",
    }
