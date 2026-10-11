"""Reversible removal, exclusion and explicit merges of workspace knowledge."""

from pathlib import Path

from database import ensure_schema, now_timestamp, record_event, refresh_fts, transaction
from errors import MemoryValidationError
from ingest_jobs import enqueue_compile_job_in_db
from lint import mark_wiki_stale
from node_revisions import save_revision
from nodes import get_node_with_details
from sources import ensure_node_source_link


def require_revision(db, node_id: str, expected: str | None):
    node = db.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if node is None or node["status"] == "deleted":
        raise MemoryValidationError("node not found.")
    if expected is not None and node["updated_at"] != expected:
        raise MemoryValidationError("node changed since the reviewed revision.")
    return node


def set_retrieval_exclusion(data_root: Path, body: dict) -> dict:
    ensure_schema(data_root)
    with transaction(data_root, immediate=True) as db:
        node = require_revision(db, str(body.get("node_id") or ""), body.get("expected_updated_at"))
        excluded = bool(body.get("excluded", True))
        timestamp = now_timestamp()
        save_revision(db, node["id"], "before_exclusion")
        if not excluded and node["identity_key"] and db.execute("SELECT 1 FROM nodes WHERE id != ? AND status = 'active' AND identity_key = ?", (node["id"], node["identity_key"])).fetchone():
            # Restoring retained knowledge must remain possible after an
            # identical active note was created; inspection can propose a merge.
            db.execute("UPDATE nodes SET identity_key = '' WHERE id = ?", (node["id"],))
        db.execute("UPDATE nodes SET status = ?, updated_at = ? WHERE id = ?", ("excluded" if excluded else "active", timestamp, node["id"]))
        refresh_fts(db, node["id"])
        save_revision(db, node["id"], "excluded" if excluded else "included")
        record_event(db, event_type="node_retrieval_exclusion", node_id=node["id"], payload={"excluded": excluded})
        return {"node": get_node_with_details(db, node["id"], data_root=data_root)}


def remove_source(data_root: Path, body: dict) -> dict:
    ensure_schema(data_root)
    source_id = str(body.get("source_id") or "")
    with transaction(data_root, immediate=True) as db:
        if body.get("node_id"):
            require_revision(db, str(body["node_id"]), body.get("expected_updated_at"))
            if db.execute("SELECT 1 FROM node_source_links WHERE node_id = ? AND source_id = ?", (body["node_id"], source_id)).fetchone() is None:
                raise MemoryValidationError("source is not linked to the reviewed node.")
        result = db.execute("UPDATE sources SET status = 'deleted', updated_at = ? WHERE id = ? AND status = 'active'", (now_timestamp(), source_id))
        if not result.rowcount:
            raise MemoryValidationError("source not found.")
        db.execute("""UPDATE source_documents SET status = 'deleted' WHERE id IN
            (SELECT source_document_id FROM source_versions WHERE source_id = ?)
            AND NOT EXISTS(SELECT 1 FROM source_versions sv JOIN sources s ON s.id = sv.source_id
                WHERE sv.source_document_id = source_documents.id AND s.status = 'active')""", (source_id,))
        for row in db.execute("SELECT node_id FROM node_source_links WHERE source_id = ?", (source_id,)):
            mark_wiki_stale(db, row["node_id"], timestamp=now_timestamp(), reason="source_removed", data_root=data_root)
            enqueue_compile_job_in_db(db, node_id=row["node_id"], reason="source_removed")
        record_event(db, event_type="source_removed", payload={"source_id": source_id})
    return {"removed": True, "source_id": source_id, "retained_for_audit": True}


def merge_nodes(data_root: Path, body: dict) -> dict:
    ensure_schema(data_root)
    source_id, target_id = str(body.get("node_id") or ""), str(body.get("target_node_id") or "")
    if source_id == target_id:
        raise MemoryValidationError("merge requires two different nodes.")
    with transaction(data_root, immediate=True) as db:
        source = require_revision(db, source_id, body.get("expected_updated_at"))
        target = require_revision(db, target_id, body.get("target_updated_at"))
        if source["status"] != "active" or target["status"] != "active":
            raise MemoryValidationError("merge requires active nodes.")
        timestamp = now_timestamp()
        save_revision(db, source_id, "before_merge")
        save_revision(db, target_id, "before_merge")
        for link in db.execute("SELECT * FROM node_source_links WHERE node_id = ?", (source_id,)):
            ensure_node_source_link(db, node_id=target_id, source_id=link["source_id"], external_ref_id=link["external_ref_id"] or "", timestamp=timestamp)
        db.execute("UPDATE external_refs SET node_id = ? WHERE node_id = ?", (target_id, source_id))
        db.execute("UPDATE edges SET source_node_id = ?, updated_at = ? WHERE source_node_id = ?", (target_id, timestamp, source_id))
        db.execute("UPDATE edges SET target_node_id = ?, updated_at = ? WHERE target_node_id = ?", (target_id, timestamp, source_id))
        db.execute("UPDATE edges SET status = 'deleted', deleted_at = ? WHERE source_node_id = target_node_id", (timestamp,))
        db.execute("UPDATE nodes SET status = 'deleted', deleted_at = ?, delete_reason = ?, updated_at = ? WHERE id = ?", (timestamp, "merged_into:" + target_id, timestamp, source_id))
        db.execute("UPDATE nodes SET updated_at = ? WHERE id = ?", (timestamp, target_id))
        db.execute("DELETE FROM memory_fts WHERE node_id = ?", (source_id,))
        mark_wiki_stale(db, target_id, timestamp=timestamp, reason="nodes_merged", data_root=data_root)
        enqueue_compile_job_in_db(db, node_id=target_id, reason="nodes_merged")
        save_revision(db, target_id, "merged")
        record_event(db, event_type="nodes_merged", node_id=target_id, payload={"merged_node_id": source_id, "retained_content": "target"})
        return {"node": get_node_with_details(db, target_id, data_root=data_root), "merged_node_id": source_id}
