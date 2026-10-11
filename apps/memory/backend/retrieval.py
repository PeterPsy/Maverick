"""Search, context retrieval, and audit reads for Memory."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from content_store import read_body
from database import connect, ensure_schema, normalize_limit, row_payload
from errors import MemoryValidationError
from source_retrieval import citations_for_chunk, chunk_freshness as source_chunk_freshness, chunk_summary
from storage_reference_payloads import storage_references_for_node
from source_references import external_refs_for_nodes
from wiki_queries import compact_compiled_payload
from retrieval_projections import compact_projections
from search_candidates import ranked_candidates, query_expression, query_terms, scope_sql


def search_nodes(data_root: Path, query: str, *, limit: int = 10, compact: bool = False, scope: dict | None = None, offset: int = 0) -> list[dict[str, Any]]:
    ensure_schema(data_root)
    normalized_limit = normalize_limit(limit, default=10, minimum=1, maximum=500)
    scope_clause, scope_values = scope_sql(scope)
    with connect(data_root) as db:
        candidates = ranked_candidates(db, query, limit=normalized_limit, scope=scope, offset=offset) if query.strip() else [
            {**dict(row), "match_sources": ["node"], "relevance": float(row["importance"])}
            for row in db.execute(f"SELECT id, importance FROM nodes WHERE status = 'active' {scope_clause} ORDER BY importance DESC, updated_at DESC, id DESC LIMIT ? OFFSET ?", (*scope_values, normalized_limit, offset))]
        selected_ids = [candidate["id"] for candidate in candidates[:normalized_limit]]
        projections = compact_projections(db, selected_ids, data_root=data_root) if compact else {}
        matches_by_node = source_chunk_matches_by_node(db, data_root, query, node_ids=selected_ids, limit=normalized_limit)
        fields = "id, type, title, substr(summary,1,360) AS summary, substr(body_text, 1, 520) AS body_text, length(body_text) AS body_text_char_count, status, importance, confidence, created_at, updated_at, metadata_json" if compact else "*"
        marks = ",".join("?" for _ in selected_ids)
        selected_nodes = {row["id"]: row_payload(row) or {} for row in db.execute(f"SELECT {fields} FROM nodes WHERE id IN ({marks})", selected_ids)} if selected_ids else {}
        results = []
        for candidate in candidates:
            node_id = candidate["id"]
            node = selected_nodes.get(node_id) or row_payload(db.execute(f"SELECT {fields} FROM nodes WHERE id = ?", (node_id,)).fetchone()) or {}
            node["match_sources"] = candidate["match_sources"]
            matches = matches_by_node if node_id in selected_ids else source_chunk_matches_by_node(db, data_root, query, node_ids=[node_id], limit=1)
            if "source_chunk" in candidate["match_sources"] and not matches.get(node_id) and candidate["match_sources"] == ["source_chunk"]:
                continue
            node["source_chunk_matches"] = matches.get(node_id, [])
            results.append(memory_node_result(db, data_root, node, relevance=candidate["relevance"], compact=compact, projection=projections.get(node_id)))
            if len(results) >= normalized_limit:
                break
        return results


def source_chunk_matches_by_node(
    db: sqlite3.Connection,
    data_root: Path,
    query: str,
    *,
    node_ids: list[str] | None,
    limit: int,
) -> dict[str, list[dict[str, Any]]]:
    search = query_expression(query, complete=False)
    if not query.strip():
        return {}
    if not search:
        return {}
    node_clause = ""
    values: list[Any] = [search]
    if node_ids is not None:
        if not node_ids:
            return {}
        placeholders = ",".join("?" for _item in node_ids)
        node_clause = f"AND n.id IN ({placeholders})"
        values.extend(node_ids)
    values.append(limit * 8)
    rows = db.execute(
        f"""
        SELECT
          n.id AS node_id,
          sc.id AS chunk_id,
          sc.source_version_id,
          sc.chunk_index,
          sc.body_path,
          sc.body_sha256,
          sc.char_start,
          sc.char_end,
          sc.locator,
          sc.locator_kind,
          sc.metadata_json,
          sv.source_document_id,
          sv.extraction_status,
          sv.hash_kind,
          sv.observed_at,
          s.id AS source_id,
          s.title AS source_title,
          s.file_id,
          s.workspace_relative_path,
          s.entity_id,
          bm25(source_chunk_fts) AS rank
        FROM source_chunks sc
        JOIN source_chunk_fts ON source_chunk_fts.chunk_id = sc.id
        JOIN source_versions sv ON sv.id = sc.source_version_id
        JOIN sources s ON s.id = sv.source_id
        JOIN node_source_links nsl ON nsl.source_id = s.id
        JOIN nodes n ON n.id = nsl.node_id
        WHERE n.status = 'active'
          AND sc.body_path != '' AND s.status = 'active' AND s.current_version_id = sv.id
          AND source_chunk_fts MATCH ?
          {node_clause}
        ORDER BY rank, sv.observed_at DESC, sc.chunk_index
        LIMIT ?
        """,
        tuple(values),
    )
    matches: dict[str, list[dict[str, Any]]] = {}
    body_cache: dict[str, str] = {}
    for row in rows:
        if len(matches.get(str(row["node_id"]), [])) >= 3:
            continue
        payload = row_payload(row) or {}
        try:
            chunk_body = body_cache.get(row["chunk_id"]) or read_body(
                data_root,
                relative_path=str(payload.get("body_path") or ""),
                expected_sha256=str(payload.get("body_sha256") or ""),
            )
        except MemoryValidationError:
            continue
        if not source_chunk_match_matches_query(payload, chunk_body, query):
            continue
        body_cache[row["chunk_id"]] = chunk_body
        node_id = str(row["node_id"])
        matches.setdefault(node_id, [])
        if len(matches[node_id]) >= 3:
            continue
        matches[node_id].append(
            {
                "kind": "source_chunk",
                "source_id": row["source_id"],
                "source_document_id": row["source_document_id"] or "",
                "source_version_id": row["source_version_id"],
                "chunk_id": row["chunk_id"],
                "title": row["source_title"] or row["source_id"],
                "summary": chunk_summary(chunk_body, query),
                "freshness": chunk_freshness(db, row),
                "hash": row["body_sha256"] or "",
                "locator": {
                    "kind": row["locator_kind"] or "",
                    "value": row["locator"] or "",
                    "char_start": row["char_start"],
                    "char_end": row["char_end"],
                },
                "source": {
                    "file_id": row["file_id"] or "",
                    "workspace_relative_path": row["workspace_relative_path"] or "",
                    "entity_id": row["entity_id"] or "",
                    "hash_kind": row["hash_kind"] or "",
                    "extraction_status": row["extraction_status"] or "",
                },
                "citations": citations_for_chunk(db, str(row["chunk_id"] or ""), limit=4),
            }
        )
    return matches


def chunk_freshness(db: sqlite3.Connection, chunk: sqlite3.Row) -> str:
    return source_chunk_freshness(db, row_payload(chunk) or {})


def source_chunk_match_matches_query(payload: dict[str, Any], chunk_body: str, query: str) -> bool:
    normalized = query.strip().casefold()
    if not normalized:
        return False
    haystacks = (
        chunk_body,
        str(payload.get("source_title") or ""),
        str(payload.get("file_id") or ""),
        str(payload.get("entity_id") or ""),
        str(payload.get("workspace_relative_path") or ""),
    )
    haystack = " ".join(value for value in haystacks if value).casefold()
    if normalized in haystack:
        return True
    tokens = query_terms(query)
    return bool(tokens) and sum(token in haystack for token in tokens) / len(tokens) >= .5


def memory_node_result(
    db: sqlite3.Connection,
    data_root: Path,
    node: dict[str, Any],
    *,
    relevance: float = 0.0,
    match_sources: list[str] | None = None,
    reason: str = "",
    compact: bool = False,
    projection: dict | None = None,
) -> dict[str, Any]:
    node_id = str(node.get("id") or node.get("node_id") or "").strip()
    summary = str(node.get("summary") or str(node.get("body_text") or "")[:280])
    sources = list(match_sources if match_sources is not None else node.get("match_sources") or ["node"])
    compiled = projection["compiled"] if projection is not None else compact_compiled_payload(db, node_id, data_root=data_root, bounded=compact) or {}
    compiled_citations = compiled.get("citations") if isinstance(compiled.get("citations"), list) else []
    item = {
        "kind": "memory_node",
        "entity": {"entity_type": "node", "entity_id": node_id},
        "source_version_id": "",
        "chunk_id": "",
        "freshness": compiled.get("freshness") or "unknown",
        "citations": compiled_citations,
        "locator": {"kind": "memory_node", "value": node_id},
        "node": {
            "id": node_id,
            "node_id": node_id,
            "type": node.get("type") or "",
            "title": node.get("title") or node_id,
            "summary": summary,
            "body_text": node.get("body_text") or "",
            "status": node.get("status") or "active",
            "importance": node.get("importance"),
            "confidence": node.get("confidence"),
            "created_at": node.get("created_at") or "",
            "updated_at": node.get("updated_at") or "",
            "metadata": node.get("metadata") if isinstance(node.get("metadata"), dict) else {},
        },
        "id": node_id,
        "node_id": node_id,
        "type": node.get("type") or "",
        "title": node.get("title") or node_id,
        "summary": summary,
        "body_text": node.get("body_text") or "",
        "body_text_char_count": node.get("body_text_char_count", len(node.get("body_text") or "")),
        "updated_at": node.get("updated_at") or "",
        "created_at": node.get("created_at") or "",
        "metadata": node.get("metadata") or {},
        "status": node.get("status") or "active",
        "importance": node.get("importance"),
        "confidence": node.get("confidence"),
        "revision": node.get("revision") or node.get("updated_at"),
        "compilation_state": node.get("compilation_state", compiled.get("compilation_state", "unknown")),
        "details_available": node.get("details_available", ["content","evidence","sources","history"]),
        "verification": compiled.get("verification", "unverified"),
        "relevance": round(relevance, 3),
        "match_sources": sources,
        "source_chunk_matches": list(node.get("source_chunk_matches") or []),
        "provenance": projection["provenance"] if projection is not None else [
            row_payload(row) or {}
            for row in external_refs_for_nodes(db, [node_id])
        ],
        "storage_references": projection["storage_references"] if projection is not None else storage_references_for_node(db, node_id),
        "compiled": compiled,
    }
    if reason:
        item["reason"] = reason
    return item


def graph_payload(data_root: Path, *, query: str = "", node_ids: object = None, limit: int = 30, scope: dict | None = None) -> dict[str, Any]:
    ensure_schema(data_root)
    normalized_limit = normalize_limit(limit, default=30, minimum=1, maximum=500)
    selected = _normalized_node_ids(node_ids, limit=normalized_limit)
    scope_clause, scope_values = scope_sql(scope, alias="n")
    with connect(data_root) as db:
        db.execute("BEGIN")
        if query.strip():
            from node_search import search_candidates_page
            candidates = search_candidates_page(db, query, limit=normalized_limit, scope=scope, node_ids=selected or None)
            ids = [item["id"] for item in candidates[:normalized_limit]]
            has_more = len(candidates)>normalized_limit
        elif selected:
            marks = ",".join("?" for _ in selected)
            eligible = {row["id"] for row in db.execute(f"SELECT n.id FROM nodes n WHERE n.id IN ({marks}) AND n.status='active' {scope_clause}", (*selected,*scope_values))}
            ids, has_more = [value for value in selected if value in eligible], False
        else:
            ids = [row["id"] for row in db.execute(f"SELECT n.id FROM nodes n WHERE n.status='active' {scope_clause} ORDER BY importance DESC,updated_at DESC,id DESC LIMIT ?", (*scope_values,normalized_limit+1))]
            has_more, ids = len(ids)>normalized_limit, ids[:normalized_limit]
        from retrieval_cards import node_cards
        nodes = node_cards(db, ids)
        marks = ",".join("?" for _ in ids)
        edges = [dict(row) for row in db.execute(f"""SELECT id,source_node_id AS source,target_node_id AS target,
            kind,weight,confidence,substr(reason,1,220) AS reason FROM edges WHERE status='active'
            AND source_node_id IN ({marks}) AND target_node_id IN ({marks}) ORDER BY weight DESC,confidence DESC,id LIMIT 1001""", (*ids,*ids))] if ids else []
        return {"nodes": nodes,"edges": edges[:1000],"has_more": has_more,"edges_has_more": len(edges)>1000}


def _normalized_node_ids(raw_node_ids: object, *, limit: int) -> list[str]:
    if raw_node_ids is None:
        return []
    if not isinstance(raw_node_ids, list):
        return []
    node_ids: list[str] = []
    seen: set[str] = set()
    for raw_node_id in raw_node_ids:
        node_id = str(raw_node_id or "").strip()
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        node_ids.append(node_id)
        if len(node_ids) >= limit:
            break
    return node_ids


def audit_events(data_root: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    ensure_schema(data_root)
    normalized_limit = normalize_limit(limit, default=50, minimum=1, maximum=200)
    with connect(data_root) as db:
        return [
            row_payload(row) or {}
            for row in db.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (normalized_limit,))
        ]
