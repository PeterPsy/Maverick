"""Search, context retrieval, and audit reads for Memory."""

from __future__ import annotations

from pathlib import Path
import re
import sqlite3
from typing import Any

from content_store import read_body
from database import connect, ensure_schema, normalize_limit, record_event, row_payload
from errors import MemoryValidationError
from source_chunk_index import source_chunk_fts_query
from storage_reference_payloads import storage_references_for_node
from wiki_queries import compact_compiled_payload, search_compiled_node_ids

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")

def fts_query(query: str) -> str:
    tokens = TOKEN_PATTERN.findall(query)
    if not tokens:
        return ""
    return " OR ".join(f"{token}*" for token in tokens[:12])


def search_nodes(data_root: Path, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    ensure_schema(data_root)
    normalized_limit = normalize_limit(limit, default=10, minimum=1, maximum=50)
    with connect(data_root) as db:
        search = fts_query(query)
        rows: list[sqlite3.Row]
        if search:
            try:
                rows = list(
                    db.execute(
                        """
                        SELECT n.*, bm25(memory_fts) AS score
                        FROM memory_fts JOIN nodes n ON n.id = memory_fts.node_id
                        WHERE memory_fts MATCH ? AND n.status = 'active'
                        ORDER BY score, n.importance DESC
                        LIMIT ?
                        """,
                        (search, normalized_limit),
                    )
                )
            except sqlite3.OperationalError:
                rows = []
        else:
            rows = []
        results = [row_payload(row) or {} for row in rows]
        for result in results:
            result["match_sources"] = ["node"]
            result["storage_references"] = storage_references_for_node(db, result["id"])
        if len(results) < normalized_limit:
            known_ids = {result["id"] for result in results}
            compiled_matches = search_compiled_node_ids(db, query, limit=normalized_limit)
            for node_id, match_source in compiled_matches:
                if node_id in known_ids:
                    for result in results:
                        if result["id"] == node_id and match_source not in result["match_sources"]:
                            result["match_sources"].append(match_source)
                    continue
                node_row = db.execute(
                    "SELECT *, 0.0 AS score FROM nodes WHERE id = ? AND status = 'active'",
                    (node_id,),
                ).fetchone()
                if node_row is None:
                    continue
                payload = row_payload(node_row) or {}
                payload["match_sources"] = [match_source]
                payload["storage_references"] = storage_references_for_node(db, payload["id"])
                results.append(payload)
                known_ids.add(node_id)
                if len(results) >= normalized_limit:
                    break
        if query.strip():
            add_source_chunk_matches(db, data_root, results, query, limit=normalized_limit)
            if len(results) < normalized_limit:
                known_ids = {result["id"] for result in results}
                for node, matches in source_chunk_node_matches(db, data_root, query, limit=normalized_limit):
                    if node["id"] in known_ids:
                        continue
                    payload = row_payload(node) or {}
                    payload["match_sources"] = ["source_chunk"]
                    payload["source_chunk_matches"] = matches
                    payload["storage_references"] = storage_references_for_node(db, payload["id"])
                    results.append(payload)
                    known_ids.add(payload["id"])
                    if len(results) >= normalized_limit:
                        break
        if not results:
            like = f"%{query.strip()}%"
            rows = list(
                db.execute(
                    """
                    SELECT *, 0.0 AS score FROM nodes
                    WHERE status = 'active' AND (title LIKE ? OR summary LIKE ? OR body_text LIKE ?)
                    ORDER BY importance DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (like, like, like, normalized_limit),
                )
            )
            results = [row_payload(row) or {} for row in rows]
            for result in results:
                result["match_sources"] = ["node"]
                result["storage_references"] = storage_references_for_node(db, result["id"])
        return results[:normalized_limit]


def context_payload(data_root: Path, query: str, *, limit: int = 8, record_access_event: bool = False) -> dict[str, Any]:
    normalized_limit = normalize_limit(limit, default=8, minimum=1, maximum=50)
    nodes = search_nodes(data_root, query, limit=normalized_limit)
    with connect(data_root) as db:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, node in enumerate(nodes):
            if node["id"] in seen:
                continue
            seen.add(node["id"])
            refs = [
                row_payload(row) or {}
                for row in db.execute("SELECT * FROM external_refs WHERE node_id = ? ORDER BY created_at", (node["id"],))
            ]
            storage_references = storage_references_for_node(db, node["id"])
            items.append(
                {
                    "node_id": node["id"],
                    "type": node["type"],
                    "title": node["title"],
                    "summary": node["summary"] or node["body_text"][:280],
                    "relevance": round(max(0.1, 1.0 - (index * 0.08)), 3),
                    "provenance": refs,
                    "match_sources": node.get("match_sources", []),
                    "source_chunk_matches": node.get("source_chunk_matches", []),
                    "storage_references": storage_references,
                    "compiled": compact_compiled_payload(db, node["id"], data_root=data_root),
                }
            )
            related = db.execute(
                """
                SELECT n.*, e.kind, e.weight, e.confidence, e.reason
                FROM edges e JOIN nodes n ON n.id = e.target_node_id
                WHERE e.source_node_id = ? AND e.status = 'active' AND n.status = 'active'
                ORDER BY e.weight DESC, e.confidence DESC
                LIMIT 3
                """,
                (node["id"],),
            )
            for related_row in related:
                related_payload = row_payload(related_row) or {}
                if related_payload["id"] in seen or len(items) >= normalized_limit:
                    continue
                seen.add(related_payload["id"])
                items.append(
                    {
                        "node_id": related_payload["id"],
                        "type": related_payload["type"],
                        "title": related_payload["title"],
                        "summary": related_payload["summary"] or related_payload["body_text"][:280],
                        "relevance": round(float(related_payload.get("weight") or 0.5) * float(related_payload.get("confidence") or 1.0), 3),
                        "reason": related_payload.get("reason") or f"Related through {related_payload.get('kind')}",
                        "match_sources": ["related_node"],
                        "source_chunk_matches": [],
                        "provenance": [],
                        "storage_references": storage_references_for_node(db, related_payload["id"]),
                        "compiled": compact_compiled_payload(db, related_payload["id"], data_root=data_root),
                    }
                )
            if len(items) >= normalized_limit:
                break
        if record_access_event:
            record_event(db, event_type="retrieval_context_generated", payload={"query": query, "item_count": len(items)})
    return {"query": query, "items": items[:normalized_limit]}


def add_source_chunk_matches(db: sqlite3.Connection, data_root: Path, results: list[dict[str, Any]], query: str, *, limit: int) -> None:
    if not results:
        return
    node_ids = [result["id"] for result in results]
    matches_by_node = source_chunk_matches_by_node(db, data_root, query, node_ids=node_ids, limit=limit)
    for result in results:
        matches = matches_by_node.get(result["id"], [])
        if not matches:
            continue
        result.setdefault("source_chunk_matches", [])
        result["source_chunk_matches"].extend(matches)
        if "source_chunk" not in result.setdefault("match_sources", []):
            result["match_sources"].append("source_chunk")


def source_chunk_node_matches(
    db: sqlite3.Connection,
    data_root: Path,
    query: str,
    *,
    limit: int,
) -> list[tuple[sqlite3.Row, list[dict[str, Any]]]]:
    matches_by_node = source_chunk_matches_by_node(db, data_root, query, node_ids=None, limit=limit)
    if not matches_by_node:
        return []
    placeholders = ",".join("?" for _item in matches_by_node)
    rows = list(
        db.execute(
            f"""
            SELECT *, 0.0 AS score
            FROM nodes
            WHERE id IN ({placeholders}) AND status = 'active'
            ORDER BY importance DESC, updated_at DESC
            """,
            tuple(matches_by_node),
        )
    )
    return [(row, matches_by_node.get(row["id"], [])) for row in rows]


def source_chunk_matches_by_node(
    db: sqlite3.Connection,
    data_root: Path,
    query: str,
    *,
    node_ids: list[str] | None,
    limit: int,
) -> dict[str, list[dict[str, Any]]]:
    search = source_chunk_fts_query(query)
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
          AND sc.body_path != ''
          AND source_chunk_fts MATCH ?
          {node_clause}
        ORDER BY rank, sv.observed_at DESC, sc.chunk_index
        LIMIT ?
        """,
        tuple(values),
    )
    matches: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        payload = row_payload(row) or {}
        try:
            chunk_body = read_body(
                data_root,
                relative_path=str(payload.get("body_path") or ""),
                expected_sha256=str(payload.get("body_sha256") or ""),
            )
        except MemoryValidationError:
            continue
        if not source_chunk_match_matches_query(payload, chunk_body, query):
            continue
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
            }
        )
    return matches


def chunk_freshness(db: sqlite3.Connection, chunk: sqlite3.Row) -> str:
    if chunk_marked_stale(row_payload(chunk) or {}):
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
            str(chunk["source_document_id"] or ""),
            str(chunk["source_id"] or ""),
        ),
    ).fetchone()
    if latest is None:
        return "unknown"
    return "fresh" if str(latest["id"] or "") == str(chunk["source_version_id"] or "") else "stale"


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
    return any(normalized in value.casefold() for value in haystacks)


def chunk_marked_stale(chunk: dict[str, Any]) -> bool:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    staleness = metadata.get("staleness") if isinstance(metadata.get("staleness"), dict) else {}
    return bool(metadata.get("stale") or staleness.get("state") == "stale")


def graph_payload(data_root: Path, *, query: str = "", node_ids: object = None, limit: int = 200) -> dict[str, Any]:
    ensure_schema(data_root)
    normalized_limit = normalize_limit(limit, default=200, minimum=1, maximum=500)
    selected_node_ids = _normalized_node_ids(node_ids, limit=normalized_limit)
    if selected_node_ids:
        placeholders = ",".join("?" for _item in selected_node_ids)
        with connect(data_root) as db:
            rows = [
                row_payload(row) or {}
                for row in db.execute(
                    f"""
                    SELECT *, 0.0 AS score FROM nodes
                    WHERE status = 'active' AND id IN ({placeholders})
                    """,
                    tuple(selected_node_ids),
                )
            ]
        row_by_id = {row["id"]: row for row in rows}
        nodes = [row_by_id[node_id] for node_id in selected_node_ids if node_id in row_by_id]
        if query.strip():
            needle = query.strip().lower()
            nodes = [
                node
                for node in nodes
                if needle in f"{node['title']} {node['summary']} {node['body_text']}".lower()
            ]
        node_ids = {node["id"] for node in nodes}
    elif query.strip():
        nodes = search_nodes(data_root, query, limit=normalized_limit)
        node_ids = {node["id"] for node in nodes}
    else:
        with connect(data_root) as db:
            nodes = [
                row_payload(row) or {}
                for row in db.execute(
                    """
                    SELECT *, 0.0 AS score FROM nodes
                    WHERE status = 'active'
                    ORDER BY importance DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (normalized_limit,),
                )
            ]
            node_ids = {node["id"] for node in nodes}
    if not node_ids:
        return {"nodes": [], "edges": []}
    placeholders = ",".join("?" for _item in node_ids)
    with connect(data_root) as db:
        edges = [
            row_payload(row) or {}
            for row in db.execute(
                f"""
                SELECT * FROM edges
                WHERE status = 'active'
                  AND source_node_id IN ({placeholders})
                  AND target_node_id IN ({placeholders})
                ORDER BY weight DESC, confidence DESC
                LIMIT 1000
                """,
                tuple(node_ids) + tuple(node_ids),
            )
        ]
    graph_nodes = []
    for node in nodes:
        graph_nodes.append(
            {
                "id": node["id"],
                "type": node["type"],
                "title": node["title"],
                "summary": node["summary"] or node["body_text"][:240],
                "importance": node["importance"],
                "confidence": node["confidence"],
                "updated_at": node["updated_at"],
            }
        )
    graph_edges = [
        {
            "id": edge["id"],
            "source": edge["source_node_id"],
            "target": edge["target_node_id"],
            "kind": edge["kind"],
            "weight": edge["weight"],
            "confidence": edge["confidence"],
            "reason": edge["reason"],
        }
        for edge in edges
    ]
    return {"nodes": graph_nodes, "edges": graph_edges}


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
