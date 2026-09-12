"""Candidate activity timeline persistence."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from domain import new_id
from schema import utcnow


def add_activity(
    connection: sqlite3.Connection,
    candidate_id: str,
    *,
    kind: str,
    summary: str,
    details: dict[str, Any] | None = None,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    if not summary.strip():
        raise ValueError("Activity summary is required.")
    activity = {
        "id": new_id("activity"),
        "candidate_id": candidate_id,
        "kind": kind.strip() or "note",
        "summary": summary.strip()[:2_000],
        "details": details or {},
        "occurred_at": occurred_at or utcnow(),
        "created_at": utcnow(),
    }
    connection.execute(
        "INSERT INTO activities(id,candidate_id,kind,summary,details_json,occurred_at,created_at) VALUES(?,?,?,?,?,?,?)",
        (
            activity["id"], candidate_id, activity["kind"], activity["summary"],
            json.dumps(activity["details"], ensure_ascii=False), activity["occurred_at"], activity["created_at"],
        ),
    )
    return activity


def list_activities(connection: sqlite3.Connection, candidate_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM activities WHERE candidate_id=? ORDER BY occurred_at DESC, created_at DESC LIMIT ?",
        (candidate_id, max(1, min(limit, 500))),
    ).fetchall()
    return [
        {
            "id": row["id"], "candidate_id": row["candidate_id"], "kind": row["kind"],
            "summary": row["summary"], "details": json.loads(row["details_json"] or "{}"),
            "occurred_at": row["occurred_at"], "created_at": row["created_at"],
        }
        for row in rows
    ]
