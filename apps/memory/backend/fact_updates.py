"""Explicit evidence attachment and fact reconciliation during ingestion."""

import sqlite3

from database import json_text, record_event, refresh_fts, row_payload
from errors import MemoryValidationError
from node_revisions import save_revision

FACT_OPERATIONS = {"attach_evidence", "update_fact", "replace_fact"}


def reconcile_ingested_fact(db: sqlite3.Connection, request: dict, node_id: str, *, timestamp: str) -> bool:
    node = row_payload(db.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()) or {}
    metadata = dict(node.get("metadata") or {})
    generated = metadata.get("content_mode") == "source_generated" or (metadata.get("created_from") == "source_ingest" and metadata.get("content_mode") != "curated")
    operation = request.get("operation") or ("update_fact" if generated else "attach_evidence")
    if operation not in FACT_OPERATIONS:
        raise MemoryValidationError("operation must be attach_evidence, update_fact, or replace_fact.")
    expected = request.get("expected_updated_at")
    if expected is not None and expected != node.get("updated_at"):
        raise MemoryValidationError("node changed since the reviewed revision; inspect Memory before updating it.")
    if operation == "attach_evidence":
        return False
    fact = str(request.get("fact_body") or request["body_markdown"]).strip()
    summary = str(request.get("fact_summary") or fact[:320]).strip()
    title = request["title"]
    origin = request.get("metadata") or {}
    metadata.update({key: origin[key] for key in ("knowledge_type", "confirmation", "chat_evidence", "candidate_id", "reviewed_at", "source_refs") if key in origin})
    metadata.update(request.get("fact_metadata") or {})
    metadata["content_mode"] = "source_generated" if generated and not request.get("operation") else "curated"
    metadata["confidence_basis"] = "user_confirmed" if metadata.get("confirmation") else "documentary" if generated else "agent_inference"
    if operation == "replace_fact":
        metadata["replaces_revision"] = node["updated_at"]
    changes = (node.get("title"), node.get("summary"), node.get("body_text"), node.get("metadata"), node.get("confidence")) != (title, summary, fact, metadata, request["confidence"])
    if not changes:
        return False
    save_revision(db, node_id, "before_" + operation)
    db.execute("""UPDATE nodes SET title = ?, summary = ?, body_text = ?, confidence = ?,
        updated_at = ?, metadata_json = ?, identity_key = '' WHERE id = ?""",
        (title, summary, fact, request["confidence"], timestamp, json_text(metadata), node_id))
    refresh_fts(db, node_id)
    save_revision(db, node_id, operation)
    record_event(db, event_type=operation, node_id=node_id, payload={"previous_revision": node["updated_at"], "revision": timestamp})
    return True
