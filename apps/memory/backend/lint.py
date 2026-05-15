"""Deterministic Memory wiki linting."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from database import ensure_schema, json_text, new_id, normalize_limit, now_timestamp, row_payload, transaction
from errors import MemoryValidationError


def lint_memory(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    """Refresh and return current lint findings for one node or the active graph."""

    ensure_schema(data_root)
    node_id = str(body.get("node_id") or body.get("id") or "").strip()
    limit = normalize_limit(body.get("limit"), default=50, minimum=1, maximum=200)
    with transaction(data_root, immediate=True) as db:
        node_ids = _target_node_ids(db, node_id=node_id, limit=limit)
        for current_node_id in node_ids:
            refresh_node_lint(db, current_node_id)
        findings = active_lint_findings(db, node_ids=node_ids, limit=limit)
    return {
        "findings": findings,
        "summary": {
            "node_count": len(node_ids),
            "finding_count": len(findings),
            "has_errors": any(finding.get("severity") == "error" for finding in findings),
        },
    }


def refresh_node_lint(db: sqlite3.Connection, node_id: str) -> list[dict[str, Any]]:
    node = db.execute("SELECT * FROM nodes WHERE id = ? AND status = 'active'", (node_id,)).fetchone()
    if node is None:
        return []
    wiki_page = db.execute("SELECT * FROM wiki_pages WHERE node_id = ? AND status = 'active'", (node_id,)).fetchone()
    claims = list(db.execute("SELECT * FROM claims WHERE node_id = ? AND status = 'active'", (node_id,)))
    refs = list(db.execute("SELECT * FROM external_refs WHERE node_id = ?", (node_id,)))
    edge_count = db.execute(
        """
        SELECT COUNT(*) AS count FROM edges
        WHERE status = 'active' AND (source_node_id = ? OR target_node_id = ?)
        """,
        (node_id, node_id),
    ).fetchone()["count"]
    desired = _desired_findings(db, node, wiki_page=wiki_page, claims=claims, refs=refs, edge_count=edge_count)
    timestamp = now_timestamp()
    desired_keys = {finding["finding_key"] for finding in desired}
    if desired_keys:
        placeholders = ",".join("?" for _item in desired_keys)
        db.execute(
            f"""
            UPDATE lint_findings
            SET status = 'resolved', resolved_at = ?, updated_at = ?
            WHERE node_id = ? AND status = 'active' AND finding_key NOT IN ({placeholders})
            """,
            (timestamp, timestamp, node_id, *desired_keys),
        )
    else:
        db.execute(
            """
            UPDATE lint_findings
            SET status = 'resolved', resolved_at = ?, updated_at = ?
            WHERE node_id = ? AND status = 'active'
            """,
            (timestamp, timestamp, node_id),
        )
    for finding in desired:
        values = {
            "id": finding.get("id") or new_id("lint"),
            "node_id": node_id,
            "wiki_page_id": finding.get("wiki_page_id") or (wiki_page["id"] if wiki_page is not None else None),
            "claim_id": finding.get("claim_id"),
            "finding_key": finding["finding_key"],
            "finding_type": finding["finding_type"],
            "severity": finding["severity"],
            "message": finding["message"],
            "created_at": timestamp,
            "updated_at": timestamp,
            "metadata_json": json_text(finding.get("metadata")),
        }
        db.execute(
            """
            INSERT INTO lint_findings(
              id, node_id, wiki_page_id, claim_id, finding_key, finding_type, severity, message,
              status, created_at, updated_at, resolved_at, metadata_json
            )
            VALUES (
              :id, :node_id, :wiki_page_id, :claim_id, :finding_key, :finding_type, :severity, :message,
              'active', :created_at, :updated_at, NULL, :metadata_json
            )
            ON CONFLICT(node_id, finding_key) DO UPDATE SET
              wiki_page_id = excluded.wiki_page_id,
              claim_id = excluded.claim_id,
              finding_type = excluded.finding_type,
              severity = excluded.severity,
              message = excluded.message,
              status = 'active',
              updated_at = excluded.updated_at,
              resolved_at = NULL,
              metadata_json = excluded.metadata_json
            """,
            values,
        )
    return active_lint_findings(db, node_ids=[node_id], limit=200)


def active_lint_findings(
    db: sqlite3.Connection,
    *,
    node_ids: list[str] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    normalized_limit = normalize_limit(limit, default=50, minimum=1, maximum=200)
    if node_ids is not None:
        if not node_ids:
            return []
        placeholders = ",".join("?" for _item in node_ids)
        rows = db.execute(
            f"""
            SELECT * FROM lint_findings
            WHERE status = 'active' AND node_id IN ({placeholders})
            ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, updated_at DESC
            LIMIT ?
            """,
            (*node_ids, normalized_limit),
        )
    else:
        rows = db.execute(
            """
            SELECT * FROM lint_findings
            WHERE status = 'active'
            ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, updated_at DESC
            LIMIT ?
            """,
            (normalized_limit,),
        )
    return [row_payload(row) or {} for row in rows]


def _target_node_ids(db: sqlite3.Connection, *, node_id: str, limit: int) -> list[str]:
    if node_id:
        row = db.execute("SELECT id FROM nodes WHERE id = ? AND status = 'active'", (node_id,)).fetchone()
        if row is None:
            raise MemoryValidationError("node not found.")
        return [row["id"]]
    rows = db.execute(
        "SELECT id FROM nodes WHERE status = 'active' ORDER BY importance DESC, updated_at DESC LIMIT ?",
        (limit,),
    )
    return [row["id"] for row in rows]


def _desired_findings(
    db: sqlite3.Connection,
    node: sqlite3.Row,
    *,
    wiki_page: sqlite3.Row | None,
    claims: list[sqlite3.Row],
    refs: list[sqlite3.Row],
    edge_count: int,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    node_id = node["id"]
    if not str(node["summary"] or "").strip() and not str(node["body_text"] or "").strip():
        findings.append(_finding("empty_content", "warning", "Node has no summary or body content."))
    if edge_count == 0 and not refs:
        findings.append(_finding("orphan_node", "info", "Node has no relationships or evidence sources."))
    if wiki_page is None:
        findings.append(_finding("stale_page", "warning", "Node has not been compiled into the internal wiki."))
    elif str(node["updated_at"]) > str(wiki_page["compiled_at"]):
        findings.append(_finding("stale_page", "warning", "Node changed after the last wiki compilation."))
    for claim in claims:
        citation = db.execute("SELECT id FROM citations WHERE claim_id = ? LIMIT 1", (claim["id"],)).fetchone()
        if citation is None:
            findings.append(
                _finding(
                    f"missing_citation:{claim['id']}",
                    "warning",
                    "Compiled claim has no citation.",
                    claim_id=claim["id"],
                )
            )
    contradiction_rows = db.execute(
        """
        SELECT e.id, e.reason, other.title
        FROM edges e
        JOIN nodes other ON other.id = CASE WHEN e.source_node_id = ? THEN e.target_node_id ELSE e.source_node_id END
        WHERE e.status = 'active'
          AND e.kind = 'contradicts'
          AND (e.source_node_id = ? OR e.target_node_id = ?)
          AND other.status = 'active'
        ORDER BY e.updated_at DESC
        """,
        (node_id, node_id, node_id),
    )
    for row in contradiction_rows:
        message = f"Contradiction linked to {row['title']}."
        if row["reason"]:
            message = f"{message} {row['reason']}"
        findings.append(_finding(f"contradiction:{row['id']}", "error", message))
    return findings


def _finding(
    key_or_type: str,
    severity: str,
    message: str,
    *,
    claim_id: str | None = None,
) -> dict[str, Any]:
    finding_type = key_or_type.split(":", 1)[0]
    return {
        "finding_key": key_or_type,
        "finding_type": finding_type,
        "severity": severity,
        "message": message,
        "claim_id": claim_id,
    }


def lint_findings_for_node(db: sqlite3.Connection, node_id: str) -> list[dict[str, Any]]:
    return active_lint_findings(db, node_ids=[node_id], limit=200)
