"""Maverick reference entity surface for candidates."""

from __future__ import annotations

import sqlite3
from typing import Any

from candidate_queries import list_candidates
from candidate_store import read_candidate

REFERENCE_MANIFEST = {
    "app_id": "videomaker-selection",
    "schema_version": "1",
    "entity_types": [
        {
            "entity_type": "candidate", "display_name": "Videomaker Candidate",
            "id_stability": "stable", "searchable": True, "resolvable": True,
            "summarizable": True, "deep_link_supported": True,
        }
    ],
}


def reference(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "app_id": "videomaker-selection", "entity_type": "candidate", "entity_id": candidate["id"],
        "title": candidate["name"], "subtitle": candidate["decision"],
        "summary": candidate.get("summary") or candidate.get("specialty") or "Videomaker candidate",
        "confidence": 1.0, "deep_link": f"/apps/videomaker-selection/candidates/{candidate['id']}",
    }


def search_references(connection: sqlite3.Connection, query: str, limit: int) -> dict[str, Any]:
    items, _ = list_candidates(connection, {"query": query, "limit": max(1, min(limit, 50)), "sort": "review"})
    return {"results": [reference(item) for item in items]}


def resolve_reference(connection: sqlite3.Connection, entity_id: str) -> dict[str, Any]:
    try:
        candidate = read_candidate(connection, entity_id, include_activities=False)
    except ValueError:
        return {"exists": False, "payload": None}
    return {"exists": True, "payload": reference(candidate)}


def summarize_reference(connection: sqlite3.Connection, entity_id: str) -> dict[str, Any]:
    candidate = read_candidate(connection, entity_id, include_activities=False)
    safe_fields = {
        "id": candidate["id"], "name": candidate["name"], "city": candidate["city"],
        "decision": candidate["decision"], "reviewed": candidate["reviewed"],
        "review_score": candidate["review_score"], "form_fit_score": candidate["form_fit_score"],
        "capacity": candidate["capacity"], "specialty": candidate["specialty"],
        "summary": candidate["summary"], "email_status": candidate["email_status"],
        "call_status": candidate["call_status"], "poc_status": candidate["poc_status"],
        "next_action": candidate["next_action"], "next_action_due": candidate["next_action_due"],
    }
    return {"summary": f"{candidate['name']} · {candidate['decision']} · {candidate['summary']}", "safe_fields": safe_fields}
