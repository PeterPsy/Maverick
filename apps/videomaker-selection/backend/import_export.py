"""Deterministic candidate import and full app-owned export."""

from __future__ import annotations

import sqlite3
from typing import Any

from activity_store import add_activity
from candidate_queries import list_candidates
from candidate_store import create_candidate, read_candidate, update_candidate
from schema import SCHEMA_VERSION, utcnow


def import_candidates(connection: sqlite3.Connection, candidates: object) -> dict[str, Any]:
    if not isinstance(candidates, list):
        raise ValueError("candidates must be an array.")
    if len(candidates) > 1_000:
        raise ValueError("A single import cannot exceed 1000 candidates.")
    created = updated = 0
    ids: list[str] = []
    for raw in candidates:
        if not isinstance(raw, dict):
            raise ValueError("Each imported candidate must be an object.")
        email = str(raw.get("email") or "").strip().lower()
        existing = connection.execute("SELECT id FROM candidates WHERE lower(email)=?", (email,)).fetchone() if email else None
        if existing:
            item = update_candidate(connection, existing["id"], raw)
            add_activity(connection, item["id"], kind="import", summary="Candidatura aggiornata da import")
            updated += 1
        else:
            item = create_candidate(connection, raw, activity_kind="imported")
            created += 1
        ids.append(item["id"])
    return {"created": created, "updated": updated, "total": len(candidates), "candidate_ids": ids}


def export_catalog(connection: sqlite3.Connection) -> dict[str, Any]:
    candidates, _pagination = list_candidates(connection, {"limit": 500, "archived": "all", "sort": "name"})
    for candidate in candidates:
        candidate["activities"] = read_candidate(connection, candidate["id"])["activities"]
    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": utcnow(),
        "app_id": "videomaker-selection",
        "candidates": candidates,
    }
