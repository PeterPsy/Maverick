"""Candidate catalog CRUD and querying."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from activity_store import add_activity, list_activities
from domain import boolean, new_id, number, string_list, text, validate_status, value
from schema import utcnow

JSON_FIELDS = {"traits": "traits_json", "platforms": "platforms_json", "duplicate_submissions": "duplicate_submissions_json"}
COLUMN_FIELDS = [
    "source_response_number", "source_submitted_at", "name", "email", "city", "bio", "work_status",
    "has_vat", "profile_code", "profile_label", "profile_answer", "traits_json", "social_usage", "autonomy", "workflow", "platforms_json",
    "opportunity", "capacity", "price_proposal", "portfolio_url", "test_url", "additional_info",
    "duplicate_submissions_json", "privacy_accepted", "reviewed", "review_rank", "annotation", "specialty", "score_portfolio", "score_budget",
    "score_test", "review_score", "form_fit_score", "summary", "decision", "email_status", "call_status",
    "poc_status", "next_action", "next_action_due", "process_notes", "favorite", "archived",
]


def _json(raw: str, fallback: Any) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback


def candidate_from_row(row: sqlite3.Row, *, activities: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    candidate = {key: row[key] for key in row.keys() if key not in {"traits_json", "platforms_json", "duplicate_submissions_json"}}
    candidate.update(
        {
            "traits": _json(row["traits_json"], []),
            "platforms": _json(row["platforms_json"], []),
            "duplicate_submissions": _json(row["duplicate_submissions_json"], []),
            "has_vat": bool(row["has_vat"]), "privacy_accepted": bool(row["privacy_accepted"]), "reviewed": bool(row["reviewed"]),
            "favorite": bool(row["favorite"]), "archived": bool(row["archived"]),
        }
    )
    if activities is not None:
        candidate["activities"] = activities
    return candidate


def _normalized(payload: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
    base = current or {}
    scores = {
        field: number(payload, field, base.get(field))
        for field in ("score_portfolio", "score_budget", "score_test")
    }
    review_score_was_supplied = value(payload, "review_score") is not None
    supplied_review_score = number(payload, "review_score") if review_score_was_supplied else None
    score_was_supplied = any(
        field in payload or field.removeprefix("score_") in (payload.get("scores") or {})
        for field in ("score_portfolio", "score_budget", "score_test")
    )
    available_scores = [score for score in scores.values() if score is not None]
    if review_score_was_supplied:
        review_score = supplied_review_score
    elif score_was_supplied or not current:
        review_score = round(sum(available_scores) / len(available_scores), 1) if available_scores else None
    else:
        review_score = base.get("review_score")
    record: dict[str, Any] = {
        "source_response_number": value(payload, "source_response_number", base.get("source_response_number")),
        "source_submitted_at": text(payload, "source_submitted_at", base.get("source_submitted_at", ""), limit=200),
        "name": text(payload, "name", base.get("name", ""), limit=500),
        "email": text(payload, "email", base.get("email", ""), limit=500).lower(),
        "city": text(payload, "city", base.get("city", ""), limit=500),
        "bio": text(payload, "bio", base.get("bio", "")),
        "work_status": text(payload, "work_status", base.get("work_status", ""), limit=1_000),
        "has_vat": int(boolean(payload, "has_vat", base.get("has_vat", False))),
        "profile_code": text(payload, "profile_code", base.get("profile_code", ""), limit=20),
        "profile_label": text(payload, "profile_label", base.get("profile_label", ""), limit=1_000),
        "profile_answer": text(payload, "profile_answer", base.get("profile_answer", ""), limit=5_000),
        "traits_json": json.dumps(string_list(payload, "traits") if value(payload, "traits") is not None else base.get("traits", []), ensure_ascii=False),
        "social_usage": text(payload, "social_usage", base.get("social_usage", ""), limit=1_000),
        "autonomy": text(payload, "autonomy", base.get("autonomy", ""), limit=1_000),
        "workflow": text(payload, "workflow", base.get("workflow", ""), limit=5_000),
        "platforms_json": json.dumps(string_list(payload, "platforms") if value(payload, "platforms") is not None else base.get("platforms", []), ensure_ascii=False),
        "opportunity": text(payload, "opportunity", base.get("opportunity", ""), limit=2_000),
        "capacity": text(payload, "capacity", base.get("capacity", ""), limit=500),
        "price_proposal": text(payload, "price_proposal", base.get("price_proposal", "")),
        "portfolio_url": text(payload, "portfolio_url", base.get("portfolio_url", ""), limit=5_000),
        "test_url": text(payload, "test_url", base.get("test_url", ""), limit=5_000),
        "additional_info": text(payload, "additional_info", base.get("additional_info", "")),
        "duplicate_submissions_json": json.dumps(value(payload, "duplicate_submissions", base.get("duplicate_submissions", [])) or []),
        "privacy_accepted": int(boolean(payload, "privacy_accepted", base.get("privacy_accepted", False))),
        "reviewed": int(boolean(payload, "reviewed", base.get("reviewed", False))),
        "review_rank": value(payload, "review_rank", base.get("review_rank")),
        "annotation": text(payload, "annotation", base.get("annotation", "")),
        "specialty": text(payload, "specialty", base.get("specialty", ""), limit=1_000),
        **scores, "review_score": review_score,
        "form_fit_score": number(payload, "form_fit_score", base.get("form_fit_score")),
        "summary": text(payload, "summary", base.get("summary", ""), limit=5_000),
        "next_action": text(payload, "next_action", base.get("next_action", ""), limit=5_000),
        "next_action_due": text(payload, "next_action_due", base.get("next_action_due", ""), limit=100),
        "process_notes": text(payload, "process_notes", base.get("process_notes", "")),
        "favorite": int(boolean(payload, "favorite", base.get("favorite", False))),
        "archived": int(boolean(payload, "archived", base.get("archived", False))),
    }
    if not record["name"]:
        raise ValueError("Candidate name is required.")
    for field, default in (("decision", "da_valutare"), ("email_status", "da_contattare"), ("call_status", "non_prevista"), ("poc_status", "non_previsto")):
        record[field] = validate_status(field, text(payload, field, base.get(field, default), limit=100))
    for integer_field in ("source_response_number", "review_rank"):
        if record[integer_field] not in {None, ""}:
            record[integer_field] = int(record[integer_field])
        else:
            record[integer_field] = None
    return record


def create_candidate(connection: sqlite3.Connection, payload: dict[str, Any], *, activity_kind: str = "created") -> dict[str, Any]:
    record = _normalized(payload)
    candidate_id = str(payload.get("id") or new_id("candidate"))[:200]
    now = utcnow()
    columns = ["id", *COLUMN_FIELDS, "created_at", "updated_at"]
    values = [candidate_id, *(record[field] for field in COLUMN_FIELDS), now, now]
    connection.execute(
        f"INSERT INTO candidates({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
        values,
    )
    add_activity(connection, candidate_id, kind=activity_kind, summary="Candidatura importata" if activity_kind == "imported" else "Candidato creato")
    return read_candidate(connection, candidate_id)


def read_candidate(connection: sqlite3.Connection, candidate_id: str, *, include_activities: bool = True) -> dict[str, Any]:
    row = connection.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if row is None:
        raise ValueError("Candidate was not found.")
    activities = list_activities(connection, candidate_id) if include_activities else None
    return candidate_from_row(row, activities=activities)


def update_candidate(connection: sqlite3.Connection, candidate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    current = read_candidate(connection, candidate_id, include_activities=False)
    record = _normalized(payload, current)
    changed = {field: {"from": current.get(field), "to": record[field]} for field in COLUMN_FIELDS if record[field] != _stored_value(current, field)}
    if changed:
        assignments = ",".join(f"{field}=?" for field in COLUMN_FIELDS)
        connection.execute(
            f"UPDATE candidates SET {assignments}, updated_at=? WHERE id=?",
            [*(record[field] for field in COLUMN_FIELDS), utcnow(), candidate_id],
        )
        pipeline = any(field in changed for field in {"decision", "email_status", "call_status", "poc_status"})
        add_activity(connection, candidate_id, kind="pipeline" if pipeline else "updated", summary="Pipeline aggiornata" if pipeline else "Profilo aggiornato", details={"changes": changed})
    return read_candidate(connection, candidate_id)


def _stored_value(candidate: dict[str, Any], field: str) -> Any:
    if field in {"traits_json", "platforms_json", "duplicate_submissions_json"}:
        return json.dumps(candidate[field.removesuffix("_json")], ensure_ascii=False)
    if field in {"has_vat", "privacy_accepted", "reviewed", "favorite", "archived"}:
        return int(bool(candidate[field]))
    return candidate.get(field)


def bulk_update_candidates(connection: sqlite3.Connection, ids: list[str], payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not ids or len(ids) > 200:
        raise ValueError("Bulk update requires between 1 and 200 candidate ids.")
    return [update_candidate(connection, str(candidate_id), payload) for candidate_id in ids]


def delete_candidate(connection: sqlite3.Connection, candidate_id: str, *, confirmed: bool) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("Candidate deletion requires confirm=true.")
    cursor = connection.execute("DELETE FROM candidates WHERE id=?", (candidate_id,))
    if cursor.rowcount == 0:
        raise ValueError("Candidate was not found.")
    return {"deleted_id": candidate_id, "deleted": 1}
