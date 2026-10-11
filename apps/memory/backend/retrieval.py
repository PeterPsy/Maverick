"""Search, context retrieval, and audit reads for Memory."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from database import connect, ensure_schema, normalize_limit, row_payload
from source_matches import source_chunk_matches_by_node
from storage_reference_payloads import storage_references_for_node
from source_references import external_refs_for_nodes
from wiki_queries import compact_compiled_payload
from retrieval_projections import compact_projections
from search_candidates import ranked_candidates, scope_sql


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
        matches_by_node = source_chunk_matches_by_node(db, data_root, query, node_ids=selected_ids)
        fields = "id, type, title, substr(summary,1,360) AS summary, substr(body_text, 1, 520) AS body_text, length(body_text) AS body_text_char_count, status, importance, confidence, created_at, updated_at, metadata_json" if compact else "*"
        marks = ",".join("?" for _ in selected_ids)
        selected_nodes = {row["id"]: row_payload(row) or {} for row in db.execute(f"SELECT {fields} FROM nodes WHERE id IN ({marks})", selected_ids)} if selected_ids else {}
        results = []
        for candidate in candidates:
            node_id = candidate["id"]
            node = selected_nodes.get(node_id) or row_payload(db.execute(f"SELECT {fields} FROM nodes WHERE id = ?", (node_id,)).fetchone()) or {}
            node["match_sources"] = candidate["match_sources"]
            matches = matches_by_node if node_id in selected_ids else source_chunk_matches_by_node(db, data_root, query, node_ids=[node_id])
            if "source_chunk" in candidate["match_sources"] and not matches.get(node_id) and candidate["match_sources"] == ["source_chunk"]:
                continue
            node["source_chunk_matches"] = matches.get(node_id, [])
            results.append(memory_node_result(db, data_root, node, relevance=candidate["relevance"], compact=compact, projection=projections.get(node_id)))
            if len(results) >= normalized_limit:
                break
        return results


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
