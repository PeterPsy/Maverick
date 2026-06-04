"""Read-only source and chunk retrieval primitives for Memory."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from content_store import read_body
from database import connect, ensure_schema, normalize_limit, row_payload
from errors import MemoryValidationError
from storage_reference_payloads import storage_reference_for_citation


def source_query(data_root: Path, query: str, *, limit: int = 10) -> dict[str, Any]:
    ensure_schema(data_root)
    normalized_limit = normalize_limit(limit, default=10, minimum=1, maximum=50)
    needle = f"%{query.strip()}%"
    if not query.strip():
        return {"query": query, "results": []}
    with connect(data_root) as db:
        chunk_rows = list(
            db.execute(
                """
                SELECT
                  sc.*,
                  sv.id AS source_version_id,
                  sv.version_hash,
                  sv.hash_kind,
                  sv.extraction_status,
                  sv.source_document_id,
                  s.id AS source_id,
                  s.title AS source_title,
                  s.external_ref_id,
                  s.file_id,
                  s.workspace_relative_path,
                  s.entity_id,
                  s.owning_app_id,
                  sd.source_key,
                  sd.adapter_id
                FROM source_chunks sc
                JOIN source_versions sv ON sv.id = sc.source_version_id
                JOIN sources s ON s.id = sv.source_id
                LEFT JOIN source_documents sd ON sd.id = sv.source_document_id
                WHERE sc.body_path != ''
                  AND (
                    s.title LIKE ?
                    OR s.file_id LIKE ?
                    OR s.entity_id LIKE ?
                    OR s.workspace_relative_path LIKE ?
                    OR sv.extracted_text LIKE ?
                  )
                ORDER BY sv.observed_at DESC, sc.chunk_index
                LIMIT ?
                """,
                (needle, needle, needle, needle, needle, normalized_limit * 8),
            )
        )
        results = []
        for row in chunk_rows:
            payload = row_payload(row) or {}
            chunk_body = _read_chunk_body(data_root, payload)
            if not chunk_matches_query(payload, chunk_body, query):
                continue
            results.append(
                {
                    "kind": "source_chunk",
                    "source_id": payload["source_id"],
                    "source_document_id": payload.get("source_document_id") or "",
                    "source_key": payload.get("source_key") or "",
                    "source_version_id": payload["source_version_id"],
                    "chunk_id": payload["id"],
                    "title": payload.get("source_title") or payload.get("source_key") or payload["source_id"],
                    "summary": chunk_summary(chunk_body, query),
                    "freshness": chunk_freshness(db, payload),
                    "citations": citations_for_chunk(db, payload["id"]),
                    "locator": {
                        "kind": payload.get("locator_kind") or "",
                        "value": payload.get("locator") or "",
                        "char_start": payload.get("char_start"),
                        "char_end": payload.get("char_end"),
                    },
                    "hash": payload.get("body_sha256") or "",
                    "source": _source_payload(payload),
                }
            )
            if len(results) >= normalized_limit:
                break
        return {"query": query, "results": results}


def fetch_chunks(data_root: Path, chunk_ids: object, *, limit: int = 20) -> dict[str, Any]:
    ensure_schema(data_root)
    ids = _normalized_chunk_ids(chunk_ids)
    normalized_limit = normalize_limit(limit, default=20, minimum=1, maximum=20)
    ids = ids[:normalized_limit]
    if not ids:
        return {"chunks": []}
    placeholders = ",".join("?" for _item in ids)
    with connect(data_root) as db:
        rows = {
            row["id"]: row_payload(row) or {}
            for row in db.execute(
                f"""
                SELECT
                  sc.*,
                  sv.source_id,
                  sv.source_document_id,
                  sv.version_hash,
                  sv.hash_kind,
                  sv.extraction_status,
                  s.title AS source_title,
                  s.external_ref_id,
                  s.file_id,
                  s.workspace_relative_path,
                  s.entity_id,
                  s.owning_app_id,
                  sd.source_key,
                  sd.adapter_id
                FROM source_chunks sc
                JOIN source_versions sv ON sv.id = sc.source_version_id
                JOIN sources s ON s.id = sv.source_id
                LEFT JOIN source_documents sd ON sd.id = sv.source_document_id
                WHERE sc.id IN ({placeholders})
                """,
                tuple(ids),
            )
        }
        chunks = []
        for chunk_id in ids:
            chunk = rows.get(chunk_id)
            if not chunk:
                continue
            body = _read_chunk_body(data_root, chunk)
            chunks.append(
                {
                    **chunk,
                    "kind": "source_chunk",
                    "chunk_id": chunk["id"],
                    "title": chunk.get("source_title") or chunk.get("source_key") or chunk["source_id"],
                    "freshness": chunk_freshness(db, chunk),
                    "citations": citations_for_chunk(db, chunk["id"]),
                    "locator": {
                        "kind": chunk.get("locator_kind") or "",
                        "value": chunk.get("locator") or "",
                        "char_start": chunk.get("char_start"),
                        "char_end": chunk.get("char_end"),
                    },
                    "source": _source_payload(chunk),
                    "body": body,
                }
            )
    return {"chunks": chunks}


def inspect_source(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        document = _resolve_source_document(db, body)
        if document is None:
            raise MemoryValidationError("source not found.")
        versions = [
            row_payload(row) or {}
            for row in db.execute(
                """
                SELECT sv.*
                FROM source_versions sv
                WHERE sv.source_document_id = ?
                ORDER BY sv.observed_at DESC
                """,
                (document["id"],),
            )
        ]
        version_ids = [version["id"] for version in versions]
        chunks = _chunks_for_versions(db, version_ids)
        linked_nodes = [
            row_payload(row) or {}
            for row in db.execute(
                """
                SELECT DISTINCT n.id, n.title, n.type, n.summary, n.updated_at
                FROM node_source_links nsl
                JOIN sources s ON s.id = nsl.source_id
                JOIN source_versions sv ON sv.source_id = s.id
                JOIN nodes n ON n.id = nsl.node_id
                WHERE sv.source_document_id = ? AND n.status = 'active'
                ORDER BY n.updated_at DESC
                """,
                (document["id"],),
            )
        ]
        jobs = [
            row_payload(row) or {}
            for row in db.execute(
                """
                SELECT *
                FROM ingest_jobs
                WHERE payload_json LIKE ?
                ORDER BY updated_at DESC
                LIMIT 20
                """,
                (f"%{document['id']}%",),
            )
        ]
    return {"source_document": document, "versions": versions, "chunks": chunks, "linked_nodes": linked_nodes, "ingest_jobs": jobs}


def _resolve_source_document(db: sqlite3.Connection, body: dict[str, Any]) -> dict[str, Any] | None:
    for field in ("source_document_id", "id"):
        value = str(body.get(field) or "").strip()
        if value:
            row = db.execute("SELECT * FROM source_documents WHERE id = ?", (value,)).fetchone()
            if row is not None:
                return row_payload(row)
    source_key = str(body.get("source_key") or "").strip()
    if source_key:
        row = db.execute("SELECT * FROM source_documents WHERE source_key = ?", (source_key,)).fetchone()
        if row is not None:
            return row_payload(row)
    source_id = str(body.get("source_id") or "").strip()
    if source_id:
        row = db.execute(
            """
            SELECT sd.*
            FROM source_documents sd
            JOIN source_versions sv ON sv.source_document_id = sd.id
            WHERE sv.source_id = ?
            ORDER BY sv.observed_at DESC
            LIMIT 1
            """,
            (source_id,),
        ).fetchone()
        if row is not None:
            return row_payload(row)
    for field in ("file_id", "entity_id"):
        value = str(body.get(field) or "").strip()
        if value:
            row = db.execute(f"SELECT * FROM source_documents WHERE {field} = ? ORDER BY updated_at DESC LIMIT 1", (value,)).fetchone()
            if row is not None:
                return row_payload(row)
    return None


def _chunks_for_versions(db: sqlite3.Connection, version_ids: list[str]) -> list[dict[str, Any]]:
    if not version_ids:
        return []
    placeholders = ",".join("?" for _item in version_ids)
    return [
        row_payload(row) or {}
        for row in db.execute(
            f"""
            SELECT *
            FROM source_chunks
            WHERE source_version_id IN ({placeholders})
            ORDER BY source_version_id, chunk_index
            """,
            tuple(version_ids),
        )
    ]


def _read_chunk_body(data_root: Path, chunk: dict[str, Any]) -> str:
    return read_body(
        data_root,
        relative_path=str(chunk.get("body_path") or ""),
        expected_sha256=str(chunk.get("body_sha256") or ""),
    )


def citations_for_chunk(db: sqlite3.Connection, chunk_id: str) -> list[dict[str, Any]]:
    citations = []
    for row in db.execute("SELECT * FROM citations WHERE source_chunk_id = ? ORDER BY created_at", (chunk_id,)):
        citation = row_payload(row) or {}
        metadata = citation.get("metadata") if isinstance(citation.get("metadata"), dict) else {}
        citation["source_version"] = str(metadata.get("source_version") or "")
        storage_reference = storage_reference_for_citation(db, citation)
        if storage_reference:
            citation["storage_reference"] = storage_reference
        citations.append(citation)
    return citations


def chunk_freshness(db: sqlite3.Connection, chunk: dict[str, Any]) -> str:
    if chunk_marked_stale(chunk):
        return "stale"
    latest = db.execute(
        """
        SELECT id
        FROM source_versions
        WHERE COALESCE(NULLIF(source_document_id, ''), source_id) = COALESCE(NULLIF(?, ''), ?)
        ORDER BY observed_at DESC, created_at DESC
        LIMIT 1
        """,
        (
            str(chunk.get("source_document_id") or ""),
            str(chunk.get("source_id") or ""),
        ),
    ).fetchone()
    if latest is None:
        return "unknown"
    return "fresh" if str(latest["id"] or "") == str(chunk.get("source_version_id") or "") else "stale"


def chunk_matches_query(payload: dict[str, Any], chunk_body: str, query: str) -> bool:
    normalized = query.strip().casefold()
    if not normalized:
        return False
    haystacks = (
        chunk_body,
        str(payload.get("source_title") or ""),
        str(payload.get("source_key") or ""),
        str(payload.get("file_id") or ""),
        str(payload.get("entity_id") or ""),
        str(payload.get("workspace_relative_path") or ""),
    )
    return any(normalized in value.casefold() for value in haystacks)


def chunk_summary(chunk_body: str, query: str, *, max_chars: int = 500) -> str:
    body = str(chunk_body or "")
    normalized = query.strip().casefold()
    if not normalized:
        return body[:max_chars]
    index = body.casefold().find(normalized)
    if index == -1:
        return body[:max_chars]
    start = max(0, index - max_chars // 3)
    end = min(len(body), start + max_chars)
    return body[start:end]


def chunk_marked_stale(chunk: dict[str, Any]) -> bool:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    staleness = metadata.get("staleness") if isinstance(metadata.get("staleness"), dict) else {}
    return bool(metadata.get("stale") or staleness.get("state") == "stale")


def _source_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "owning_app_id": payload.get("owning_app_id") or "",
        "external_ref_id": payload.get("external_ref_id") or "",
        "file_id": payload.get("file_id") or "",
        "workspace_relative_path": payload.get("workspace_relative_path") or "",
        "entity_id": payload.get("entity_id") or "",
        "adapter_id": payload.get("adapter_id") or "",
        "hash_kind": payload.get("hash_kind") or "",
        "extraction_status": payload.get("extraction_status") or "",
    }


def _normalized_chunk_ids(chunk_ids: object) -> list[str]:
    if not isinstance(chunk_ids, list):
        raise MemoryValidationError("chunk_ids must be a list.")
    normalized = []
    seen = set()
    for raw_id in chunk_ids:
        chunk_id = str(raw_id or "").strip()
        if not chunk_id or chunk_id in seen:
            continue
        seen.add(chunk_id)
        normalized.append(chunk_id)
    return normalized
