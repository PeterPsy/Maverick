"""Search, context retrieval, and audit reads for Memory."""

from __future__ import annotations

from pathlib import Path
import re
import sqlite3
from typing import Any

from database import connect, ensure_schema, record_event, row_payload

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")

def fts_query(query: str) -> str:
    tokens = TOKEN_PATTERN.findall(query)
    if not tokens:
        return ""
    return " OR ".join(f"{token}*" for token in tokens[:12])


def search_nodes(data_root: Path, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    ensure_schema(data_root)
    normalized_limit = max(1, min(int(limit or 10), 50))
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
        if not rows:
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
        return [row_payload(row) or {} for row in rows]


def context_payload(data_root: Path, query: str, *, limit: int = 8) -> dict[str, Any]:
    nodes = search_nodes(data_root, query, limit=limit)
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
            items.append(
                {
                    "node_id": node["id"],
                    "type": node["type"],
                    "title": node["title"],
                    "summary": node["summary"] or node["body_text"][:280],
                    "relevance": round(max(0.1, 1.0 - (index * 0.08)), 3),
                    "provenance": refs,
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
                if related_payload["id"] in seen or len(items) >= limit:
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
                        "provenance": [],
                    }
                )
            if len(items) >= limit:
                break
        record_event(db, event_type="retrieval_context_generated", payload={"query": query, "item_count": len(items)})
    return {"query": query, "items": items[:limit]}


def graph_payload(data_root: Path, *, query: str = "", limit: int = 200) -> dict[str, Any]:
    ensure_schema(data_root)
    normalized_limit = max(1, min(int(limit or 200), 500))
    if query.strip():
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
        refs_by_node: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in node_ids}
        for row in db.execute(
            f"SELECT * FROM external_refs WHERE node_id IN ({placeholders}) ORDER BY created_at",
            tuple(node_ids),
        ):
            ref = row_payload(row) or {}
            refs_by_node.setdefault(ref.get("node_id", ""), []).append(ref)
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
                "external_refs": refs_by_node.get(node["id"], []),
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


def audit_events(data_root: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    ensure_schema(data_root)
    normalized_limit = max(1, min(int(limit or 50), 200))
    with connect(data_root) as db:
        return [
            row_payload(row) or {}
            for row in db.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (normalized_limit,))
        ]
