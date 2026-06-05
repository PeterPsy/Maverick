"""Compiled internal wiki operations for Memory."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
from typing import Any

from citation_matching import citation_quote
from content_store import read_body
from database import ensure_schema, json_text, new_id, now_timestamp, row_payload, transaction
from errors import MemoryValidationError
from lint import refresh_node_lint
from sources import prepare_source_snapshots, sync_sources
from wiki_content import claim_texts, compile_input_hash, compiled_markdown
from wiki_queries import compiled_payload_for_node


def compile_node(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(data_root)
    node_id = str(body.get("node_id") or body.get("id") or "").strip()
    if not node_id:
        raise MemoryValidationError("node_id is required.")
    prepared_snapshots = prepare_source_snapshots(data_root, node_id)
    with transaction(data_root, immediate=True) as db:
        node = _active_node(db, node_id)
        refs = _external_refs(db, node_id)
        relationships = _relationships(db, node_id)
        timestamp = now_timestamp()
        sources = sync_sources(
            db,
            data_root=data_root,
            node_id=node_id,
            refs=refs,
            timestamp=timestamp,
            prepared_snapshots=prepared_snapshots,
        )
        sources = merged_source_candidates(db, node_id=node_id, synced_sources=sources)
        input_hash = compile_source_aware_input_hash(
            node,
            refs,
            relationships,
            sources=sources,
            data_root=data_root,
        )
        provenance = compile_source_provenance(db, sources)
        run = _create_compile_run(
            db,
            node_id=node_id,
            input_hash=input_hash,
            timestamp=timestamp,
            metadata={"mode": "node_snapshot", **provenance},
        )
        page = _upsert_wiki_page(
            db,
            node=node,
            refs=refs,
            relationships=relationships,
            compile_run_id=run["id"],
            timestamp=timestamp,
        )
        _replace_claims(db, data_root=data_root, page_id=page["id"], node=node, sources=sources, timestamp=timestamp)
        _complete_compile_run(db, run_id=run["id"], page_id=page["id"], timestamp=timestamp, provenance=provenance)
        refresh_node_lint(db, node_id, data_root=data_root)
        return {
            "compile_run": row_payload(db.execute("SELECT * FROM compile_runs WHERE id = ?", (run["id"],)).fetchone()),
            **compiled_payload_for_node(db, node_id, data_root=data_root),
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


def _create_compile_run(
    db: sqlite3.Connection,
    *,
    node_id: str,
    input_hash: str,
    timestamp: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    run = {
        "id": new_id("run"),
        "node_id": node_id,
        "status": "running",
        "compiler": "deterministic",
        "input_hash": input_hash,
        "started_at": timestamp,
        "metadata_json": json_text(metadata),
    }
    db.execute(
        """
        INSERT INTO compile_runs(id, node_id, status, compiler, input_hash, started_at, metadata_json)
        VALUES (:id, :node_id, :status, :compiler, :input_hash, :started_at, :metadata_json)
        """,
        run,
    )
    return run


def _complete_compile_run(
    db: sqlite3.Connection,
    *,
    run_id: str,
    page_id: str,
    timestamp: str,
    provenance: dict[str, Any],
) -> None:
    rows = list(
        db.execute(
            """
            SELECT source_version_id, source_chunk_id
            FROM citations
            WHERE claim_id IN (SELECT id FROM claims WHERE wiki_page_id = ?)
            """,
            (page_id,),
        )
    )
    metadata = {
        "mode": "node_snapshot",
        **provenance,
        "citation_count": len(rows),
        "cited_source_version_ids": sorted({row["source_version_id"] for row in rows if row["source_version_id"]}),
        "cited_source_chunk_ids": sorted({row["source_chunk_id"] for row in rows if row["source_chunk_id"]}),
    }
    db.execute(
        "UPDATE compile_runs SET status = 'completed', completed_at = ?, metadata_json = ? WHERE id = ?",
        (timestamp, json_text(metadata), run_id),
    )


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
    data_root: Path,
    page_id: str,
    node: sqlite3.Row,
    sources: list[dict[str, Any]],
    timestamp: str,
) -> None:
    old_claim_ids = [row["id"] for row in db.execute("SELECT id FROM claims WHERE wiki_page_id = ?", (page_id,))]
    if old_claim_ids:
        placeholders = ",".join("?" for _item in old_claim_ids)
        db.execute(f"DELETE FROM citations WHERE claim_id IN ({placeholders})", tuple(old_claim_ids))
        db.execute(f"DELETE FROM lint_findings WHERE claim_id IN ({placeholders})", tuple(old_claim_ids))
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
        for source, version, chunk, chunk_body in citation_sources(db, sources, data_root=data_root):
            quote = citation_quote(claim_text, chunk_body)
            if not quote:
                continue
            char_start, char_end = quote_range(chunk_body, quote)
            metadata = dict(source.get("metadata") or {})
            version_metadata = dict(version.get("metadata") or {})
            metadata["source_version"] = version_metadata.get("source_version") or metadata.get("source_version") or version["version_hash"]
            db.execute(
                """
                INSERT INTO citations(
                  id, claim_id, source_id, source_version_id, source_chunk_id, external_ref_id,
                  locator, locator_kind, char_start, char_end, quote_sha256, quote, created_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("cite"),
                    claim["id"],
                    source["id"],
                    version["id"],
                    chunk["id"],
                    source.get("external_ref_id"),
                    citation_locator(source, version, chunk),
                    chunk.get("locator_kind") or "preview_text",
                    char_start,
                    char_end,
                    sha256(quote.encode("utf-8")).hexdigest(),
                    quote,
                    timestamp,
                    json_text(metadata),
                ),
            )


def citation_sources(
    db: sqlite3.Connection,
    sources: list[dict[str, Any]],
    *,
    data_root: Path,
) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]]:
    claim_sources: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]] = []
    for source in sources:
        version_id = str(source.get("source_version_id") or "")
        if not version_id:
            continue
        version_row = db.execute("SELECT * FROM source_versions WHERE id = ?", (version_id,)).fetchone()
        version = row_payload(version_row) or {}
        if not str(version.get("extracted_text") or "").strip():
            continue
        chunk_rows = db.execute(
            "SELECT * FROM source_chunks WHERE source_version_id = ? ORDER BY chunk_index",
            (version_id,),
        )
        for chunk_row in chunk_rows:
            chunk = row_payload(chunk_row) or {}
            if not chunk:
                continue
            chunk_body = read_body(data_root, relative_path=str(chunk.get("body_path") or ""), expected_sha256=str(chunk.get("body_sha256") or ""))
            if not chunk_body.strip():
                continue
            claim_sources.append((source, version, chunk, chunk_body))
    return claim_sources


def merged_source_candidates(
    db: sqlite3.Connection,
    *,
    node_id: str,
    synced_sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sources_by_id = {str(source.get("id") or ""): dict(source) for source in synced_sources if source.get("id")}
    for row in db.execute(
        """
        SELECT s.*
        FROM node_source_links nsl
        JOIN sources s ON s.id = nsl.source_id
        WHERE nsl.node_id = ? AND s.status = 'active'
        ORDER BY s.updated_at DESC
        """,
        (node_id,),
    ):
        source = row_payload(row) or {}
        if not source:
            continue
        existing = sources_by_id.get(source["id"], source)
        if not existing.get("source_version_id"):
            version = latest_source_version(db, source["id"])
            if version:
                existing["source_version_id"] = version["id"]
        sources_by_id[source["id"]] = existing
    return list(sources_by_id.values())


def latest_source_version(db: sqlite3.Connection, source_id: str) -> dict[str, Any] | None:
    return row_payload(
        db.execute(
            """
            SELECT *
            FROM source_versions
            WHERE source_id = ?
            ORDER BY observed_at DESC, created_at DESC
            LIMIT 1
            """,
            (source_id,),
        ).fetchone()
    )


def compile_source_provenance(db: sqlite3.Connection, sources: list[dict[str, Any]]) -> dict[str, Any]:
    source_items = []
    source_version_ids: set[str] = set()
    source_chunk_ids: set[str] = set()
    for source in sources:
        version_id = str(source.get("source_version_id") or "")
        if not version_id:
            continue
        version = row_payload(db.execute("SELECT * FROM source_versions WHERE id = ?", (version_id,)).fetchone()) or {}
        if not version:
            continue
        chunks = [
            row_payload(row) or {}
            for row in db.execute(
                """
                SELECT id, body_sha256, locator, locator_kind
                FROM source_chunks
                WHERE source_version_id = ?
                ORDER BY chunk_index
                """,
                (version_id,),
            )
        ]
        chunk_ids = [chunk["id"] for chunk in chunks if chunk.get("id")]
        source_version_ids.add(version_id)
        source_chunk_ids.update(chunk_ids)
        source_items.append(
            {
                "source_id": source["id"],
                "source_document_id": version.get("source_document_id") or "",
                "source_version_id": version_id,
                "version_hash": version.get("version_hash") or "",
                "hash_kind": version.get("hash_kind") or "",
                "extraction_status": version.get("extraction_status") or "",
                "source_chunk_ids": chunk_ids,
            }
        )
    return {
        "source_version_ids": sorted(source_version_ids),
        "source_chunk_ids": sorted(source_chunk_ids),
        "sources": source_items,
    }


def compile_source_aware_input_hash(
    node: sqlite3.Row,
    refs: list[sqlite3.Row],
    relationships: list[sqlite3.Row],
    *,
    sources: list[dict[str, Any]],
    data_root: Path,
) -> str:
    base_hash = compile_input_hash(node, refs, relationships, data_root=data_root)
    source_parts = [
        "\t".join(
            str(part or "")
            for part in (
                source.get("id"),
                source.get("source_version_id"),
                source.get("content_hash"),
            )
        )
        for source in sorted(sources, key=lambda item: str(item.get("id") or ""))
    ]
    return sha256("\n".join([base_hash, *source_parts]).encode("utf-8")).hexdigest()


def citation_locator(source: dict[str, Any], version: dict[str, Any], chunk: dict[str, Any] | None = None) -> str:
    metadata = dict(source.get("metadata") or {})
    return str(
        (chunk or {}).get("locator")
        or metadata.get("display_path")
        or version.get("extracted_ref")
        or source.get("workspace_relative_path")
        or source.get("entity_id")
        or source.get("uri")
        or ""
    )


def quote_range(body: str, quote: str) -> tuple[int, int]:
    if not quote:
        return (0, 0)
    start = body.find(quote)
    if start == -1:
        collapsed_body = " ".join(body.split())
        collapsed_start = collapsed_body.find(quote)
        if collapsed_start == -1:
            return (0, min(len(body), len(quote)))
        return (collapsed_start, collapsed_start + len(quote))
    return (start, start + len(quote))
