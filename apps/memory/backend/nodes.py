"""Node persistence operations for Memory."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from database import (
    connect,
    ensure_schema,
    json_text,
    new_id,
    normalize_float,
    normalize_node_type,
    now_timestamp,
    record_event,
    refresh_fts,
    row_payload,
    transaction,
)
from errors import MemoryValidationError
from node_identity import identity_key
from node_revisions import revisions_for_node, save_revision
from lint import mark_wiki_stale
from wiki_queries import compiled_payload_for_node


def create_node(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(data_root)
    title = " ".join(str(body.get("title") or "").split()).strip()
    if not title:
        raise MemoryValidationError("title is required.")
    timestamp = now_timestamp()
    node = {
        "id": str(body.get("node_id") or body.get("id") or new_id("node")),
        "type": normalize_node_type(str(body.get("type") or body.get("node_type") or "note")),
        "title": title[:240],
        "summary": str(body.get("summary") or "").strip(),
        "body_text": str(body.get("body") or body.get("body_text") or "").strip(),
        "importance": normalize_float(
            body.get("importance"),
            default=0.5,
            minimum=0,
            maximum=1,
            field_name="importance",
        ),
        "confidence": normalize_float(
            body.get("confidence"),
            default=0.5,
            minimum=0,
            maximum=1,
            field_name="confidence",
        ),
        "created_at": timestamp,
        "updated_at": timestamp,
        "metadata_json": json_text({"confidence_basis": "unspecified", **(body.get("metadata") if isinstance(body.get("metadata"), dict) else {})}),
    }
    node["identity_key"] = identity_key({**node, "metadata": body.get("metadata")})
    with transaction(data_root, immediate=True) as db:
        if not body.get("node_id") and not body.get("id"):
            existing = db.execute("SELECT id FROM nodes WHERE identity_key = ? AND status = 'active'", (node["identity_key"],)).fetchone()
            if existing is not None:
                return get_node_with_details(db, existing["id"], data_root=data_root)
        db.execute(
            """
            INSERT INTO nodes(id, type, title, summary, body_text, importance, confidence, created_at, updated_at, metadata_json, identity_key)
            VALUES (:id, :type, :title, :summary, :body_text, :importance, :confidence, :created_at, :updated_at, :metadata_json, :identity_key)
            """,
            node,
        )
        refresh_fts(db, node["id"])
        save_revision(db, node["id"], "created")
        record_event(db, event_type="node_created", node_id=node["id"], payload={"title": node["title"]})
        return get_node_with_details(db, node["id"], data_root=data_root)


def update_node(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(data_root)
    node_id = str(body.get("node_id") or body.get("id") or "").strip()
    if not node_id:
        raise MemoryValidationError("node_id is required.")
    timestamp = now_timestamp()
    with transaction(data_root, immediate=True) as db:
        existing = db.execute("SELECT * FROM nodes WHERE id = ? AND status = 'active'", (node_id,)).fetchone()
        if existing is None:
            raise MemoryValidationError("node not found.")
        if body.get("expected_updated_at") is not None and body["expected_updated_at"] != existing["updated_at"]:
            raise MemoryValidationError("node changed since the reviewed revision; inspect Memory before updating it.")
        save_revision(db, node_id, "before_update")
        metadata = (row_payload(existing) or {}).get("metadata", {})
        metadata.update(body.get("metadata") if isinstance(body.get("metadata"), dict) else {})
        metadata["content_mode"] = "curated"
        values = {
            "id": node_id,
            "title": str(body.get("title", existing["title"])).strip() or existing["title"],
            "summary": str(body.get("summary", existing["summary"])).strip(),
            "body_text": str(body.get("body", body.get("body_text", existing["body_text"]))).strip(),
            "importance": normalize_float(
                body.get("importance", existing["importance"]),
                default=float(existing["importance"]),
                minimum=0,
                maximum=1,
                field_name="importance",
            ),
            "confidence": normalize_float(
                body.get("confidence", existing["confidence"]),
                default=float(existing["confidence"]),
                minimum=0,
                maximum=1,
                field_name="confidence",
            ),
            "updated_at": timestamp,
            "type": normalize_node_type(body.get("type", existing["type"])),
            "metadata_json": json_text(metadata),
        }
        candidate_key = identity_key({**values, "metadata": metadata})
        duplicate = db.execute("SELECT id FROM nodes WHERE identity_key = ? AND status = 'active' AND id != ?", (candidate_key, node_id)).fetchone()
        values["identity_key"] = "" if duplicate else candidate_key
        db.execute(
            """
            UPDATE nodes SET type = :type, metadata_json = :metadata_json, identity_key = :identity_key, title = :title, summary = :summary, body_text = :body_text,
              importance = :importance, confidence = :confidence, updated_at = :updated_at
            WHERE id = :id
            """,
            values,
        )
        refresh_fts(db, node_id)
        save_revision(db, node_id, "updated")
        mark_wiki_stale(db, node_id, timestamp=timestamp, reason="node_updated", data_root=data_root)
        record_event(db, event_type="node_updated", node_id=node_id, payload={"title": values["title"]})
        return get_node_with_details(db, node_id, data_root=data_root)


def soft_delete_node(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(data_root)
    node_id = str(body.get("node_id") or body.get("id") or "").strip()
    if not node_id:
        raise MemoryValidationError("node_id is required.")
    timestamp = now_timestamp()
    with transaction(data_root, immediate=True) as db:
        expected = body.get("expected_updated_at")
        if expected is not None:
            current = db.execute("SELECT updated_at,status,delete_reason FROM nodes WHERE id=?", (node_id,)).fetchone()
            if current is not None and current[1] == 'deleted' and current[2] == body.get("reason"):
                return {"deleted": True, "node_id": node_id}
            if current is None or current[0] != expected:
                raise MemoryValidationError("node changed since the saved revision; inspect Memory before removing it.")
        result = db.execute(
            """
            UPDATE nodes
            SET status = 'deleted', deleted_at = ?, deleted_by = ?, delete_reason = ?, updated_at = ?
            WHERE id = ? AND status IN ('active', 'excluded')
            """,
            (timestamp, str(body.get("actor_id") or ""), str(body.get("reason") or ""), timestamp, node_id),
        )
        if result.rowcount == 0:
            raise MemoryValidationError("node not found.")
        db.execute(
            "UPDATE edges SET status = 'deleted', deleted_at = ?, updated_at = ? WHERE source_node_id = ? OR target_node_id = ?",
            (timestamp, timestamp, node_id, node_id),
        )
        db.execute("DELETE FROM memory_fts WHERE node_id = ?", (node_id,))
        record_event(db, event_type="node_soft_deleted", node_id=node_id, payload={"reason": str(body.get("reason") or "")})
        return {"deleted": True, "node_id": node_id}


def get_node_with_details(db: sqlite3.Connection, node_id: str, *, data_root: Path | None = None) -> dict[str, Any]:
    node = row_payload(db.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone())
    if node is None:
        raise MemoryValidationError("node not found.")
    refs = [
        row_payload(row)
        for row in db.execute("SELECT * FROM external_refs WHERE node_id = ? ORDER BY created_at", (node_id,))
    ]
    outgoing = [
        row_payload(row)
        for row in db.execute(
            "SELECT e.*, n.title AS other_title, n.type AS other_type FROM edges e JOIN nodes n ON n.id = e.target_node_id WHERE e.source_node_id = ? AND e.status = 'active' AND n.status != 'deleted' ORDER BY e.weight DESC",
            (node_id,),
        )
    ]
    incoming = [
        row_payload(row)
        for row in db.execute(
            "SELECT e.*, n.title AS other_title, n.type AS other_type FROM edges e JOIN nodes n ON n.id = e.source_node_id WHERE e.target_node_id = ? AND e.status = 'active' AND n.status != 'deleted' ORDER BY e.weight DESC",
            (node_id,),
        )
    ]
    node["duplicate_candidates"] = [dict(row) for row in db.execute("SELECT id, title, summary, updated_at FROM nodes WHERE id != ? AND status = 'active' AND (lower(title) = lower(?) OR (body_text != '' AND body_text = ?)) ORDER BY updated_at DESC LIMIT 5", (node_id, node["title"], node["body_text"]))]
    node["revisions"] = revisions_for_node(db, node_id)
    node["external_refs"] = [item for item in refs if item is not None]
    node["outgoing_edges"] = [item for item in outgoing if item is not None]
    node["incoming_edges"] = [item for item in incoming if item is not None]
    node.update(compiled_payload_for_node(db, node_id, data_root=data_root))
    return node


def inspect_node(data_root: Path, node_id: str) -> dict[str, Any]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        return get_node_with_details(db, node_id, data_root=data_root)
