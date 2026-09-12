"""Candidate catalog filters, sorting, and aggregate statistics."""

from __future__ import annotations

import sqlite3
from typing import Any

from candidate_store import candidate_from_row

SORTS = {
    "review": "reviewed DESC, (score_portfolio IS NOT NULL AND score_budget IS NOT NULL AND score_test IS NOT NULL) DESC, (review_rank IS NULL), review_rank ASC, review_score DESC, form_fit_score DESC, name COLLATE NOCASE",
    "form": "form_fit_score DESC, reviewed DESC, review_score DESC, name COLLATE NOCASE",
    "name": "name COLLATE NOCASE",
    "newest": "COALESCE(source_response_number, 0) DESC, created_at DESC",
    "status": "CASE decision WHEN 'selezionato' THEN 0 WHEN 'da_valutare' THEN 1 WHEN 'riserva' THEN 2 ELSE 3 END, review_score DESC",
    "updated": "updated_at DESC",
}
FILTER_COLUMNS = {
    "decision": "decision", "email_status": "email_status", "call_status": "call_status",
    "poc_status": "poc_status", "profile_code": "profile_code", "capacity": "capacity",
}


def list_candidates(connection: sqlite3.Connection, options: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    archived = options.get("archived")
    if archived in {True, "true", "archived"}:
        where.append("archived=1")
    elif archived != "all":
        where.append("archived=0")
    query = str(options.get("query") or "").strip()
    if query:
        probe = f"%{query}%"
        where.append("(name LIKE ? OR email LIKE ? OR city LIKE ? OR bio LIKE ? OR annotation LIKE ? OR specialty LIKE ? OR summary LIKE ? OR price_proposal LIKE ?)")
        params.extend([probe] * 8)
    for argument, column in FILTER_COLUMNS.items():
        candidate_value = str(options.get(argument) or "").strip()
        if candidate_value and candidate_value != "all":
            where.append(f"{column}=?")
            params.append(candidate_value)
    reviewed = options.get("reviewed")
    if reviewed in {True, "true", "reviewed"}:
        where.append("reviewed=1")
    elif reviewed in {False, "false", "not_reviewed"}:
        where.append("reviewed=0")
    if options.get("favorite") in {True, "true"}:
        where.append("favorite=1")
    work = str(options.get("work") or "all")
    if work == "vat": where.append("has_vat=1")
    elif work == "no_vat": where.append("work_status LIKE 'Non ho%'")
    elif work == "employee": where.append("work_status='Dipendente'")
    ids_were_supplied = isinstance(options.get("ids"), list)
    ids = [str(item) for item in options.get("ids", []) if str(item)] if ids_were_supplied else []
    if ids:
        where.append(f"id IN ({','.join('?' for _ in ids)})")
        params.extend(ids)
    elif ids_were_supplied:
        where.append("0=1")
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    total = connection.execute(f"SELECT count(*) FROM candidates{clause}", params).fetchone()[0]
    sort = SORTS.get(str(options.get("sort") or "review"), SORTS["review"])
    direction = " DESC" if str(options.get("direction") or "asc").lower() == "desc" and str(options.get("sort")) in {"name"} else ""
    limit = max(1, min(int(options.get("limit") or 200), 500))
    offset = max(0, int(options.get("offset") or 0))
    rows = connection.execute(f"SELECT * FROM candidates{clause} ORDER BY {sort}{direction} LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
    return [candidate_from_row(row) for row in rows], {"total": total, "offset": offset, "limit": limit, "has_more": offset + len(rows) < total}


def candidate_stats(connection: sqlite3.Connection) -> dict[str, Any]:
    total = connection.execute("SELECT count(*) FROM candidates WHERE archived=0").fetchone()[0]
    def counts(field: str) -> dict[str, int]:
        return {row[0]: row[1] for row in connection.execute(f"SELECT {field}, count(*) FROM candidates WHERE archived=0 GROUP BY {field}").fetchall()}
    return {
        "total": total,
        "reviewed": connection.execute("SELECT count(*) FROM candidates WHERE archived=0 AND reviewed=1").fetchone()[0],
        "favorites": connection.execute("SELECT count(*) FROM candidates WHERE archived=0 AND favorite=1").fetchone()[0],
        "due_actions": connection.execute("SELECT count(*) FROM candidates WHERE archived=0 AND next_action_due<>''").fetchone()[0],
        "decision": counts("decision"), "email": counts("email_status"),
        "call": counts("call_status"), "poc": counts("poc_status"),
    }
