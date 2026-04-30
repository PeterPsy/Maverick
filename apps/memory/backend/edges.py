"""Relationship persistence operations for Memory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from errors import MemoryValidationError
from database import connect, ensure_schema, json_text, new_id, normalize_edge_kind, now_timestamp, record_event, row_payload

def create_edge(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(data_root)
    source = str(body.get("source_node_id") or body.get("source") or "").strip()
    target = str(body.get("target_node_id") or body.get("target") or "").strip()
    if not source or not target:
        raise MemoryValidationError("source_node_id and target_node_id are required.")
    timestamp = now_timestamp()
    edge = {
        "id": str(body.get("edge_id") or body.get("id") or new_id("edge")),
        "source_node_id": source,
        "target_node_id": target,
        "kind": normalize_edge_kind(str(body.get("kind") or "related_to")),
        "weight": float(body.get("weight", 0.5)),
        "confidence": float(body.get("confidence", 1.0)),
        "reason": str(body.get("reason") or "").strip(),
        "created_at": timestamp,
        "updated_at": timestamp,
        "metadata_json": json_text(body.get("metadata")),
    }
    with connect(data_root) as db:
        for node_id in (source, target):
            if db.execute("SELECT id FROM nodes WHERE id = ? AND status = 'active'", (node_id,)).fetchone() is None:
                raise MemoryValidationError(f"node `{node_id}` not found.")
        db.execute(
            """
            INSERT INTO edges(id, source_node_id, target_node_id, kind, weight, confidence, reason, created_at, updated_at, metadata_json)
            VALUES (:id, :source_node_id, :target_node_id, :kind, :weight, :confidence, :reason, :created_at, :updated_at, :metadata_json)
            """,
            edge,
        )
        record_event(db, event_type="edge_created", edge_id=edge["id"], payload={"reason": edge["reason"]})
        return row_payload(db.execute("SELECT * FROM edges WHERE id = ?", (edge["id"],)).fetchone()) or {}


def soft_delete_edge(data_root: Path, edge_id: str) -> dict[str, Any]:
    ensure_schema(data_root)
    timestamp = now_timestamp()
    with connect(data_root) as db:
        db.execute("UPDATE edges SET status = 'deleted', deleted_at = ?, updated_at = ? WHERE id = ?", (timestamp, timestamp, edge_id))
        record_event(db, event_type="edge_soft_deleted", edge_id=edge_id)
    return {"deleted": True, "edge_id": edge_id}
