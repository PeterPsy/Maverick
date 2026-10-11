"""Compiled internal wiki operations for Memory."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
from typing import Any

from database import ensure_schema, json_text, new_id, now_timestamp, record_event, row_payload, transaction
from errors import MemoryValidationError
from fact_updates import reconcile_ingested_fact
from lint import refresh_node_lint
from sources import prepare_source_snapshots, sync_sources, source_version_body
from wiki_content import compile_input_hash, compiled_markdown
from wiki_citations import replace_claims
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
        origin = (row_payload(node) or {}).get("metadata", {})
        if origin.get("content_mode") == "source_generated" or (origin.get("created_from") == "source_ingest" and origin.get("content_mode") != "curated"):
            primary = next((source for source in sources if source.get("source_document_id") == origin.get("source_document_id")), sources[0] if len(sources) == 1 else None)
            if primary and primary.get("source_version_id"):
                version = row_payload(db.execute("SELECT * FROM source_versions WHERE id = ?", (primary["source_version_id"],)).fetchone()) or {}
                if version.get("extraction_status") in {"available", "truncated"}:
                    text = source_version_body(data_root, version)
                    if text and origin.get("candidate_id") is None:
                        reconcile_ingested_fact(db, {"title": primary.get("title") or node["title"], "body_markdown": text,
                            "confidence": node["confidence"], "metadata": version.get("metadata", {})}, node_id, timestamp=timestamp)
                        node = _active_node(db, node_id)
        input_hash = compile_source_aware_input_hash(
            node,
            refs,
            relationships,
            sources=sources,
            data_root=data_root,
        )
        cached = db.execute("""SELECT cr.* FROM compile_runs cr JOIN wiki_pages wp ON wp.compile_run_id = cr.id
          WHERE wp.node_id = ? AND wp.status = 'active' AND wp.freshness = 'fresh'
            AND cr.status = 'completed' AND cr.input_hash = ?""", (node_id, input_hash)).fetchone()
        if cached is not None:
            return {"compile_run": row_payload(cached), "reused": True,
                    **compiled_payload_for_node(db, node_id, data_root=data_root)}
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
        replace_claims(db, data_root=data_root, page_id=page["id"], node=node, sources=sources, timestamp=timestamp)
        db.execute("DELETE FROM compiled_fts WHERE node_id = ?", (node_id,))
        db.execute("INSERT INTO compiled_fts(node_id, title, summary, body_text, claim_text) SELECT wp.node_id, wp.title, wp.summary, wp.body_markdown, COALESCE((SELECT group_concat(claim_text, char(10)) FROM claims WHERE wiki_page_id = wp.id AND status = 'active'), '') FROM wiki_pages wp WHERE wp.node_id = ?", (node_id,))
        _complete_compile_run(db, run_id=run["id"], page_id=page["id"], timestamp=timestamp, provenance=provenance)
        lint_findings = refresh_node_lint(db, node_id, data_root=data_root)
        compile_run = row_payload(db.execute("SELECT * FROM compile_runs WHERE id = ?", (run["id"],)).fetchone()) or {}
        record_compile_completed_event(
            db,
            node_id=node_id,
            page_id=page["id"],
            compile_run=compile_run,
            lint_findings=lint_findings,
        )
        return {
            "compile_run": compile_run,
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
            WHERE claim_id IN (SELECT id FROM claims WHERE wiki_page_id = ?) AND evidence_relation = 'supports'
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


def record_compile_completed_event(
    db: sqlite3.Connection,
    *,
    node_id: str,
    page_id: str,
    compile_run: dict[str, Any],
    lint_findings: list[dict[str, Any]],
) -> None:
    metadata = compile_run.get("metadata") if isinstance(compile_run.get("metadata"), dict) else {}
    source_version_ids = metadata.get("source_version_ids") if isinstance(metadata.get("source_version_ids"), list) else []
    source_chunk_ids = metadata.get("source_chunk_ids") if isinstance(metadata.get("source_chunk_ids"), list) else []
    cited_source_version_ids = (
        metadata.get("cited_source_version_ids") if isinstance(metadata.get("cited_source_version_ids"), list) else []
    )
    cited_source_chunk_ids = metadata.get("cited_source_chunk_ids") if isinstance(metadata.get("cited_source_chunk_ids"), list) else []
    record_event(
        db,
        event_type="memory_compile_completed",
        node_id=node_id,
        payload={
            "compile_run_id": compile_run.get("id") or "",
            "wiki_page_id": page_id,
            "status": compile_run.get("status") or "completed",
            "compiler": compile_run.get("compiler") or "deterministic",
            "source_version_count": len(source_version_ids),
            "source_chunk_count": len(source_chunk_ids),
            "cited_source_version_count": len(cited_source_version_ids),
            "cited_source_chunk_count": len(cited_source_chunk_ids),
            "citation_count": int(metadata.get("citation_count") or 0),
            "lint_finding_count": len(lint_findings),
        },
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
                existing["source_document_id"] = version.get("source_document_id") or ""
        sources_by_id[source["id"]] = existing
    return list(sources_by_id.values())


def latest_source_version(db: sqlite3.Connection, source_id: str) -> dict[str, Any] | None:
    return row_payload(db.execute(
        "SELECT sv.* FROM source_versions sv JOIN sources s ON s.current_version_id = sv.id WHERE s.id = ?",
        (source_id,),
    ).fetchone())


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
    return sha256("\n".join(["support-v4", base_hash, *source_parts]).encode("utf-8")).hexdigest()
