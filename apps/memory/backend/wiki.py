"""Compiled internal wiki operations for Memory."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from database import ensure_schema, json_text, new_id, now_timestamp, row_payload, transaction
from errors import MemoryValidationError
from lint import refresh_node_lint
from sources import insert_citation, sync_sources
from wiki_content import claim_texts, compile_input_hash, compiled_markdown
from wiki_queries import compiled_payload_for_node


def compile_node(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(data_root)
    node_id = str(body.get("node_id") or body.get("id") or "").strip()
    if not node_id:
        raise MemoryValidationError("node_id is required.")
    with transaction(data_root, immediate=True) as db:
        node = _active_node(db, node_id)
        refs = _external_refs(db, node_id)
        relationships = _relationships(db, node_id)
        timestamp = now_timestamp()
        input_hash = compile_input_hash(node, refs, relationships)
        run = _create_compile_run(db, node_id=node_id, input_hash=input_hash, timestamp=timestamp)
        sources = sync_sources(db, node_id=node_id, refs=refs, timestamp=timestamp)
        page = _upsert_wiki_page(
            db,
            node=node,
            refs=refs,
            relationships=relationships,
            compile_run_id=run["id"],
            timestamp=timestamp,
        )
        _replace_claims(db, page_id=page["id"], node=node, sources=sources, timestamp=timestamp)
        db.execute(
            "UPDATE compile_runs SET status = 'completed', completed_at = ? WHERE id = ?",
            (timestamp, run["id"]),
        )
        refresh_node_lint(db, node_id)
        return {
            "compile_run": row_payload(db.execute("SELECT * FROM compile_runs WHERE id = ?", (run["id"],)).fetchone()),
            **compiled_payload_for_node(db, node_id),
        }


def _active_node(db: sqlite3.Connection, node_id: str) -> sqlite3.Row:
    node = db.execute("SELECT * FROM nodes WHERE id = ? AND status = 'active'", (node_id,)).fetchone()
    if node is None:
        raise MemoryValidationError("node not found.")
    return node


def _external_refs(db: sqlite3.Connection, node_id: str) -> list[sqlite3.Row]:
    return list(db.execute("SELECT * FROM external_refs WHERE node_id = ? ORDER BY created_at", (node_id,)))


def _relationships(db: sqlite3.Connection, node_id: str) -> list[sqlite3.Row]:
    return list(
        db.execute(
            """
            SELECT e.*, other.title AS other_title, other.type AS other_type
            FROM edges e
            JOIN nodes other ON other.id = CASE WHEN e.source_node_id = ? THEN e.target_node_id ELSE e.source_node_id END
            WHERE e.status = 'active'
              AND other.status = 'active'
              AND (e.source_node_id = ? OR e.target_node_id = ?)
            ORDER BY e.weight DESC, e.confidence DESC
            """,
            (node_id, node_id, node_id),
        )
    )


def _create_compile_run(db: sqlite3.Connection, *, node_id: str, input_hash: str, timestamp: str) -> dict[str, Any]:
    run = {
        "id": new_id("run"),
        "node_id": node_id,
        "status": "running",
        "compiler": "deterministic",
        "input_hash": input_hash,
        "started_at": timestamp,
        "metadata_json": json_text({"mode": "node_snapshot"}),
    }
    db.execute(
        """
        INSERT INTO compile_runs(id, node_id, status, compiler, input_hash, started_at, metadata_json)
        VALUES (:id, :node_id, :status, :compiler, :input_hash, :started_at, :metadata_json)
        """,
        run,
    )
    return run


def _upsert_wiki_page(
    db: sqlite3.Connection,
    *,
    node: sqlite3.Row,
    refs: list[sqlite3.Row],
    relationships: list[sqlite3.Row],
    compile_run_id: str,
    timestamp: str,
) -> dict[str, Any]:
    existing = db.execute("SELECT id, created_at FROM wiki_pages WHERE node_id = ?", (node["id"],)).fetchone()
    page = {
        "id": existing["id"] if existing is not None else new_id("wiki"),
        "node_id": node["id"],
        "title": node["title"],
        "summary": str(node["summary"] or node["body_text"][:320] or node["title"]).strip(),
        "body_markdown": compiled_markdown(node, refs, relationships),
        "freshness": "fresh",
        "compile_run_id": compile_run_id,
        "compiled_at": timestamp,
        "created_at": existing["created_at"] if existing is not None else timestamp,
        "updated_at": timestamp,
        "metadata_json": json_text({"compiler": "deterministic"}),
    }
    db.execute(
        """
        INSERT INTO wiki_pages(
          id, node_id, title, summary, body_markdown, freshness, compile_run_id,
          compiled_at, created_at, updated_at, metadata_json
        )
        VALUES (
          :id, :node_id, :title, :summary, :body_markdown, :freshness, :compile_run_id,
          :compiled_at, :created_at, :updated_at, :metadata_json
        )
        ON CONFLICT(node_id) DO UPDATE SET
          title = excluded.title,
          summary = excluded.summary,
          body_markdown = excluded.body_markdown,
          freshness = excluded.freshness,
          status = 'active',
          compile_run_id = excluded.compile_run_id,
          compiled_at = excluded.compiled_at,
          updated_at = excluded.updated_at,
          metadata_json = excluded.metadata_json
        """,
        page,
    )
    return row_payload(db.execute("SELECT * FROM wiki_pages WHERE node_id = ?", (node["id"],)).fetchone()) or page


def _replace_claims(
    db: sqlite3.Connection,
    *,
    page_id: str,
    node: sqlite3.Row,
    sources: list[dict[str, Any]],
    timestamp: str,
) -> None:
    old_claim_ids = [row["id"] for row in db.execute("SELECT id FROM claims WHERE wiki_page_id = ?", (page_id,))]
    if old_claim_ids:
        placeholders = ",".join("?" for _item in old_claim_ids)
        db.execute(f"DELETE FROM citations WHERE claim_id IN ({placeholders})", tuple(old_claim_ids))
    db.execute("DELETE FROM claims WHERE wiki_page_id = ?", (page_id,))
    for claim_text in claim_texts(node):
        claim = {
            "id": new_id("claim"),
            "wiki_page_id": page_id,
            "node_id": node["id"],
            "claim_text": claim_text,
            "confidence": float(node["confidence"] or 0.8),
            "created_at": timestamp,
            "updated_at": timestamp,
            "metadata_json": json_text({"source": "node_content"}),
        }
        db.execute(
            """
            INSERT INTO claims(id, wiki_page_id, node_id, claim_text, confidence, created_at, updated_at, metadata_json)
            VALUES (:id, :wiki_page_id, :node_id, :claim_text, :confidence, :created_at, :updated_at, :metadata_json)
            """,
            claim,
        )
        for source in sources[:3]:
            insert_citation(db, claim_id=claim["id"], source=source, timestamp=timestamp)
