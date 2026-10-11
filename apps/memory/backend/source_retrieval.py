"""Read-only source and chunk retrieval primitives for Memory."""

from __future__ import annotations

from pathlib import Path
import re
import sqlite3
from typing import Any

from content_store import read_body
from context_payloads import compact_citations
from database import connect, ensure_schema, normalize_limit, row_payload
from errors import MemoryValidationError
from source_current import current_version_id
from search_candidates import query_expression, query_terms, scope_sql
from retrieval_pages import bounded_page, fingerprint, page_offset, response_budget, retrieval_revision
from storage_reference_payloads import storage_reference_for_citation

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


def source_query(data_root: Path, query: str, *, limit: int = 10, include_history: bool = False, include_excluded: bool = False,
                 scope: dict | None = None, cursor: object = None, max_bytes: object = None) -> dict[str, Any]:
    ensure_schema(data_root)
    normalized_limit = normalize_limit(limit, default=10, minimum=1, maximum=50)
    search = query_expression(query, complete=False)
    with connect(data_root) as db:
        db.execute('BEGIN')
        binding = fingerprint([query,scope,include_history,include_excluded,retrieval_revision(db),'source'])
        offset = page_offset(cursor,binding)
        scope_clause, scope_values = scope_sql(scope,alias='n')
        base = {'query':query[:420],'snapshot_id':binding}
        if not search:
            return bounded_page([],key='results',base=base,limit=normalized_limit,offset=offset,binding=binding,max_bytes=response_budget(max_bytes))
        chunk_rows = list(
            db.execute(
                f"""
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
                WHERE sc.body_path != '' AND (? OR s.status = 'active')
                  AND (? OR s.current_version_id = sv.id)
                  AND EXISTS (SELECT 1 FROM node_source_links nl JOIN nodes n ON n.id = nl.node_id
                    WHERE nl.source_id = s.id AND (? OR n.status = 'active') {scope_clause})
                  AND source_chunk_fts MATCH ?
                ORDER BY rank, sv.observed_at DESC, sc.chunk_index
                LIMIT ? OFFSET ?
                """,
                (include_excluded, include_history, include_excluded, *scope_values, search, normalized_limit+1, offset),
            )
        )
        results = []
        for row in chunk_rows:
            payload = row_payload(row) or {}
            chunk_body = _read_chunk_body(data_root, payload)
            citations = citations_for_chunk(db, payload['id'], limit=4)
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
                    "reason": "Matches a historical source passage" if include_history else "Matches a current source passage",
                    "match_sources": ["source_chunk"],
                    "freshness": chunk_freshness(db, payload),
                    "citations": compact_citations(citations,limit=3,quote_chars=300),
                    "citations_has_more": len(citations)>3,
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
        return bounded_page(results,key='results',base=base,limit=normalized_limit,offset=offset,
                            binding=binding,max_bytes=response_budget(max_bytes))


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


def _read_chunk_body(data_root: Path, chunk: dict[str, Any]) -> str:
    return read_body(
        data_root,
        relative_path=str(chunk.get("body_path") or ""),
        expected_sha256=str(chunk.get("body_sha256") or ""),
    )


def citations_for_chunk(db: sqlite3.Connection, chunk_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    citations = []
    query = "SELECT ct.* FROM citations ct JOIN claims cl ON cl.id = ct.claim_id JOIN nodes n ON n.id = cl.node_id WHERE source_chunk_id = ? AND ct.evidence_relation = 'supports' AND n.status = 'active' AND cl.stale = 0 ORDER BY ct.created_at,ct.id"
    for row in db.execute(query+(' LIMIT ?' if limit else ''), (chunk_id,limit) if limit else (chunk_id,)):
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
    current = current_version_id(db, str(chunk.get("source_id") or ""))
    if not current:
        return "unknown"
    return "fresh" if current == str(chunk.get("source_version_id") or "") else "stale"


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
    tokens = query_terms(query)
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
