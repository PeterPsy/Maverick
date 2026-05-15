"""Read helpers for compiled Memory wiki data."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from database import connect, ensure_schema, normalize_limit, now_timestamp, row_payload
from lint import lint_findings_for_node, refresh_compiled_freshness


def wiki_query(data_root: Path, query: str, *, limit: int = 10) -> dict[str, Any]:
    ensure_schema(data_root)
    normalized_limit = normalize_limit(limit, default=10, minimum=1, maximum=50)
    needle = f"%{query.strip()}%"
    if not query.strip():
        return {"query": query, "results": []}
    with connect(data_root) as db:
        page_rows = list(
            db.execute(
                """
                SELECT wp.*, n.type AS node_type
                FROM wiki_pages wp
                JOIN nodes n ON n.id = wp.node_id
                WHERE wp.status = 'active'
                  AND n.status = 'active'
                  AND (wp.title LIKE ? OR wp.summary LIKE ? OR wp.body_markdown LIKE ?)
                ORDER BY wp.updated_at DESC
                LIMIT ?
                """,
                (needle, needle, needle, normalized_limit),
            )
        )
        timestamp = now_timestamp()
        for row in page_rows:
            refresh_compiled_freshness(db, row["node_id"], data_root=data_root, timestamp=timestamp)
        results = [
            {
                "kind": "wiki_page",
                "node_id": row["node_id"],
                "wiki_page_id": row["id"],
                "title": row["title"],
                "summary": row["summary"],
                "node_type": row["node_type"],
                "freshness": _page_freshness(db, row["id"]) or row["freshness"],
                "compiled_at": row["compiled_at"],
            }
            for row in page_rows
        ]
        if len(results) < normalized_limit:
            claim_rows = list(
                db.execute(
                    """
                    SELECT c.*, wp.title, wp.freshness, wp.compiled_at
                    FROM claims c
                    JOIN wiki_pages wp ON wp.id = c.wiki_page_id
                    JOIN nodes n ON n.id = c.node_id
                    WHERE c.status = 'active'
                      AND wp.status = 'active'
                      AND n.status = 'active'
                      AND c.claim_text LIKE ?
                    ORDER BY c.updated_at DESC
                    LIMIT ?
                    """,
                    (needle, normalized_limit - len(results)),
                )
            )
            for row in claim_rows:
                refresh_compiled_freshness(db, row["node_id"], data_root=data_root, timestamp=timestamp)
            results.extend(
                {
                    "kind": "claim",
                    "node_id": row["node_id"],
                    "wiki_page_id": row["wiki_page_id"],
                    "claim_id": row["id"],
                    "title": row["title"],
                    "summary": row["claim_text"],
                    "freshness": _page_freshness(db, row["wiki_page_id"]) or row["freshness"],
                    "compiled_at": row["compiled_at"],
                }
                for row in claim_rows
            )
    return {"query": query, "results": results}


def _page_freshness(db: sqlite3.Connection, wiki_page_id: str) -> str:
    row = db.execute("SELECT freshness FROM wiki_pages WHERE id = ?", (wiki_page_id,)).fetchone()
    return str(row["freshness"] or "") if row is not None else ""


def compiled_payload_for_node(
    db: sqlite3.Connection,
    node_id: str,
    *,
    data_root: Path | None = None,
) -> dict[str, Any]:
    refresh_compiled_freshness(db, node_id, data_root=data_root, timestamp=now_timestamp())
    page = row_payload(db.execute("SELECT * FROM wiki_pages WHERE node_id = ? AND status = 'active'", (node_id,)).fetchone())
    if page is None:
        return {
            "compiled_page": None,
            "claims": [],
            "citations": [],
            "sources": [],
            "lint_findings": lint_findings_for_node(db, node_id),
        }
    claims = _claims_with_citations(db, page["id"])
    citations = [citation for claim in claims for citation in claim.get("citations", [])]
    sources = [
        row_payload(row) or {}
        for row in db.execute(
            """
            SELECT s.*
            FROM node_source_links nsl
            JOIN sources s ON s.id = nsl.source_id
            WHERE nsl.node_id = ? AND s.status = 'active'
            ORDER BY s.updated_at DESC
            """,
            (node_id,),
        )
    ]
    return {
        "compiled_page": page,
        "claims": claims,
        "citations": citations,
        "sources": sources,
        "lint_findings": lint_findings_for_node(db, node_id),
    }


def compact_compiled_payload(
    db: sqlite3.Connection,
    node_id: str,
    *,
    data_root: Path | None = None,
) -> dict[str, Any] | None:
    payload = compiled_payload_for_node(db, node_id, data_root=data_root)
    page = payload.get("compiled_page")
    if not page:
        return None
    return {
        "wiki_page_id": page["id"],
        "summary": page["summary"],
        "body_markdown": page["body_markdown"],
        "freshness": page["freshness"],
        "compiled_at": page["compiled_at"],
        "claims": payload["claims"],
        "lint_findings": payload["lint_findings"],
    }


def search_compiled_node_ids(db: sqlite3.Connection, query: str, *, limit: int) -> list[tuple[str, str]]:
    if not query.strip():
        return []
    normalized_limit = normalize_limit(limit, default=10, minimum=1, maximum=50)
    needle = f"%{query.strip()}%"
    rows = db.execute(
        """
        SELECT DISTINCT node_id, 'wiki_page' AS match_source, updated_at
        FROM wiki_pages
        WHERE status = 'active' AND (title LIKE ? OR summary LIKE ? OR body_markdown LIKE ?)
        UNION
        SELECT DISTINCT node_id, 'claim' AS match_source, updated_at
        FROM claims
        WHERE status = 'active' AND claim_text LIKE ?
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (needle, needle, needle, needle, normalized_limit),
    )
    return [(row["node_id"], row["match_source"]) for row in rows]


def _claims_with_citations(db: sqlite3.Connection, page_id: str) -> list[dict[str, Any]]:
    claims = []
    for row in db.execute("SELECT * FROM claims WHERE wiki_page_id = ? AND status = 'active' ORDER BY created_at", (page_id,)):
        claim = row_payload(row) or {}
        claim["citations"] = [
            row_payload(citation) or {}
            for citation in db.execute("SELECT * FROM citations WHERE claim_id = ? ORDER BY created_at", (claim["id"],))
        ]
        claims.append(claim)
    return claims
