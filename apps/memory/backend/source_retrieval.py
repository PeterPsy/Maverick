"""Read-only source and chunk retrieval primitives for Memory."""

from __future__ import annotations

from pathlib import Path
import re
import sqlite3
from typing import Any

from content_store import read_body
from database import connect, ensure_schema, normalize_limit, row_payload
from errors import MemoryValidationError
from source_chunk_index import source_chunk_fts_query
from storage_reference_payloads import storage_reference_for_citation

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


def source_query(data_root: Path, query: str, *, limit: int = 10) -> dict[str, Any]:
    ensure_schema(data_root)
    normalized_limit = normalize_limit(limit, default=10, minimum=1, maximum=50)
    search = source_chunk_fts_query(query)
    if not query.strip():
        return {"query": query, "results": []}
    if not search:
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
                  sd.adapter_id,
                  bm25(source_chunk_fts) AS rank
                FROM source_chunks sc
                JOIN source_chunk_fts ON source_chunk_fts.chunk_id = sc.id
                JOIN source_versions sv ON sv.id = sc.source_version_id
                JOIN sources s ON s.id = sv.source_id
                LEFT JOIN source_documents sd ON sd.id = sv.source_document_id
                WHERE sc.body_path != ''
                  AND source_chunk_fts MATCH ?
                ORDER BY rank, sv.observed_at DESC, sc.chunk_index
                LIMIT ?
                """,
                (search, normalized_limit * 8),
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
        raw_versions = [
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
        version_ids = [version["id"] for version in raw_versions]
        latest_version_id = version_ids[0] if version_ids else ""
        raw_chunks = _chunks_for_versions(db, version_ids)
        versions = [_normalized_source_version(version, latest_version_id=latest_version_id) for version in raw_versions]
        chunks = [_normalized_source_chunk(db, chunk) for chunk in raw_chunks]
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
        jobs = _jobs_for_source_document(db, document_id=str(document["id"]), version_ids=version_ids)
        freshness = _source_freshness_summary(document, versions, chunks)
    return {
        "source_document": _normalized_source_document(document, freshness=freshness),
        "freshness": freshness,
        "versions": versions,
        "chunks": chunks,
        "linked_nodes": linked_nodes,
        "ingest_jobs": jobs,
    }


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
            SELECT sc.*, sv.source_id, sv.source_document_id
            FROM source_chunks sc
            JOIN source_versions sv ON sv.id = sc.source_version_id
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
    haystack = " ".join(value for value in haystacks if value).casefold()
    if normalized in haystack:
        return True
    tokens = [token.casefold() for token in TOKEN_PATTERN.findall(query)[:12]]
    return bool(tokens) and all(token in haystack for token in tokens)


def chunk_summary(chunk_body: str, query: str, *, max_chars: int = 500) -> str:
    body = str(chunk_body or "")
    normalized = query.strip().casefold()
    if not normalized:
        return body[:max_chars]
    index = body.casefold().find(normalized)
    if index == -1:
        for token in TOKEN_PATTERN.findall(query)[:12]:
            index = body.casefold().find(token.casefold())
            if index != -1:
                break
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


def _normalized_source_document(document: dict[str, Any], *, freshness: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "source_document",
        "id": document.get("id") or "",
        "source_document_id": document.get("id") or "",
        "source_key": document.get("source_key") or "",
        "adapter_id": document.get("adapter_id") or "",
        "source_kind": document.get("source_kind") or "",
        "owning_app_id": document.get("owning_app_id") or "",
        "entity_type": document.get("entity_type") or "",
        "entity_id": document.get("entity_id") or "",
        "file_id": document.get("file_id") or "",
        "workspace_relative_path": document.get("workspace_relative_path") or "",
        "uri": document.get("uri") or "",
        "title": document.get("title") or document.get("source_key") or "",
        "status": document.get("status") or "active",
        "freshness": freshness,
        "created_at": document.get("created_at") or "",
        "updated_at": document.get("updated_at") or "",
        "metadata": document.get("metadata") if isinstance(document.get("metadata"), dict) else {},
    }


def _normalized_source_version(version: dict[str, Any], *, latest_version_id: str) -> dict[str, Any]:
    freshness = "stale" if chunk_marked_stale(version) else "fresh" if str(version.get("id") or "") == latest_version_id else "stale"
    return {
        "kind": "source_version",
        "id": version.get("id") or "",
        "source_version_id": version.get("id") or "",
        "source_id": version.get("source_id") or "",
        "source_document_id": version.get("source_document_id") or "",
        "version_hash": version.get("version_hash") or "",
        "hash_kind": version.get("hash_kind") or "",
        "extraction_status": version.get("extraction_status") or "",
        "freshness": freshness,
        "is_latest": str(version.get("id") or "") == latest_version_id,
        "body": {
            "path": version.get("body_path") or "",
            "sha256": version.get("body_sha256") or "",
            "bytes": version.get("body_bytes") or 0,
        },
        "extracted_ref": version.get("extracted_ref") or "",
        "content_type": version.get("content_type") or "",
        "source_modified_at": version.get("source_modified_at") or "",
        "observed_at": version.get("observed_at") or "",
        "created_at": version.get("created_at") or "",
        "metadata": version.get("metadata") if isinstance(version.get("metadata"), dict) else {},
    }


def _normalized_source_chunk(db: sqlite3.Connection, chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "source_chunk",
        "id": chunk.get("id") or "",
        "chunk_id": chunk.get("id") or "",
        "source_version_id": chunk.get("source_version_id") or "",
        "chunk_index": chunk.get("chunk_index") or 0,
        "freshness": chunk_freshness(db, chunk),
        "hash": chunk.get("body_sha256") or "",
        "body": {
            "path": chunk.get("body_path") or "",
            "sha256": chunk.get("body_sha256") or "",
        },
        "locator": {
            "kind": chunk.get("locator_kind") or "",
            "value": chunk.get("locator") or "",
            "char_start": chunk.get("char_start"),
            "char_end": chunk.get("char_end"),
        },
        "citations": citations_for_chunk(db, str(chunk.get("id") or "")),
        "created_at": chunk.get("created_at") or "",
        "metadata": chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {},
    }


def _jobs_for_source_document(db: sqlite3.Connection, *, document_id: str, version_ids: list[str]) -> list[dict[str, Any]]:
    where = ["source_document_id = ?"]
    values: list[Any] = [document_id]
    if version_ids:
        placeholders = ",".join("?" for _item in version_ids)
        where.append(f"source_version_id IN ({placeholders})")
        values.extend(version_ids)
    rows = db.execute(
        f"""
        SELECT *
        FROM ingest_jobs
        WHERE {" OR ".join(where)}
        ORDER BY updated_at DESC
        LIMIT 20
        """,
        tuple(values),
    )
    return [_normalized_ingest_job(row_payload(row) or {}) for row in rows]


def _normalized_ingest_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "ingest_job",
        "id": job.get("id") or "",
        "job_id": job.get("id") or "",
        "job_type": job.get("job_type") or "",
        "dedupe_key": job.get("dedupe_key") or "",
        "status": job.get("status") or "",
        "attempt_count": job.get("attempt_count") or 0,
        "max_attempts": job.get("max_attempts") or 0,
        "available_at": job.get("available_at") or "",
        "locked_until": job.get("locked_until") or "",
        "last_error": job.get("last_error") or "",
        "node_id": job.get("node_id") or "",
        "source_document_id": job.get("source_document_id") or "",
        "source_version_id": job.get("source_version_id") or "",
        "payload": job.get("payload") if isinstance(job.get("payload"), dict) else {},
        "created_at": job.get("created_at") or "",
        "updated_at": job.get("updated_at") or "",
    }


def _source_freshness_summary(
    document: dict[str, Any],
    versions: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    stale_reasons = sorted(
        {
            reason
            for payload in [document, *versions, *chunks]
            for reason in [_stale_reason(payload)]
            if reason
        }
    )
    stale_version_count = sum(1 for version in versions if version.get("freshness") == "stale")
    stale_chunk_count = sum(1 for chunk in chunks if chunk.get("freshness") == "stale")
    latest_source_version_id = versions[0]["id"] if versions else ""
    current_version_stale = bool(versions and versions[0].get("freshness") == "stale" and _metadata_marks_stale(versions[0]))
    current_chunk_stale = any(
        chunk.get("source_version_id") == latest_source_version_id and chunk.get("freshness") == "stale"
        for chunk in chunks
    )
    state = "stale" if _metadata_marks_stale(document) or current_version_stale or current_chunk_stale else "fresh"
    return {
        "state": state,
        "latest_source_version_id": latest_source_version_id,
        "version_count": len(versions),
        "chunk_count": len(chunks),
        "stale_version_count": stale_version_count,
        "stale_chunk_count": stale_chunk_count,
        "reasons": stale_reasons,
    }


def _metadata_marks_stale(payload: dict[str, Any]) -> bool:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    staleness = metadata.get("staleness") if isinstance(metadata.get("staleness"), dict) else {}
    return bool(metadata.get("stale") or staleness.get("state") == "stale")


def _stale_reason(payload: dict[str, Any]) -> str:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    staleness = metadata.get("staleness") if isinstance(metadata.get("staleness"), dict) else {}
    return str(metadata.get("stale_reason") or staleness.get("reason") or "").strip()


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
