"""CRM bootstrap payload assembly."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from errors import NotFoundError
from domains.custom_fields import schema_config
from domains.operations import find_duplicates
from domains.record_intelligence import intelligent_next_actions
from domains.saved_views import list_saved_views, read_view_state
from domains.workflow import list_workflow_proposals
from store import count_tables, get_record, list_rows, row_to_dict


ENTITY_TABLES = {
    "lead": "leads",
    "account": "accounts",
    "contact": "contacts",
    "deal": "deals",
    "activity": "activities",
    "task": "tasks",
    "note": "notes",
}


def bootstrap_payload(db, data_root: str | Path) -> dict[str, Any]:
    view_state = read_view_state(data_root)
    payload = {
        "ok": True,
        "leads": list_rows(db, "leads", limit=100),
        "accounts": list_rows(db, "accounts", limit=100),
        "contacts": list_rows(db, "contacts", limit=100),
        "deals": list_rows(db, "deals", limit=100),
        "tasks": list_rows(db, "tasks", limit=50),
        "notes": list_rows(db, "notes", limit=50),
        "activities": list_rows(db, "activities", limit=50),
        "pipelines": [row_to_dict(row) for row in db.execute("SELECT * FROM pipelines ORDER BY name").fetchall()],
        "pipeline_stages": [row_to_dict(row) for row in db.execute("SELECT * FROM pipeline_stages ORDER BY position").fetchall()],
        "saved_views": list_saved_views(db),
        "duplicates": find_duplicates(db, {"limit": 10}),
        "schema": schema_config(db),
        "next_action_suggestions": intelligent_next_actions(db, {"limit": 8}),
        "workflow_proposals": list_workflow_proposals(db, {"status": "active", "limit": 20}),
        "counts": count_tables(db, ["leads", "accounts", "contacts", "deals", "activities", "tasks", "notes"]),
        "view_state": view_state,
    }
    _hydrate_custom_view_records(db, payload, view_state)
    return payload


def _hydrate_custom_view_records(db, payload: dict[str, Any], view_state: dict[str, Any]) -> None:
    view_filter = view_state.get("view_filter") if isinstance(view_state, dict) else {}
    if not isinstance(view_filter, dict) or view_filter.get("mode") != "custom":
        return
    refs = view_filter.get("refs") or []
    if not isinstance(refs, list):
        return
    for ref in refs:
        parsed = _parse_view_ref(ref)
        if parsed is None:
            continue
        entity_type, entity_id = parsed
        table = ENTITY_TABLES.get(entity_type)
        if not table:
            continue
        try:
            record = get_record(db, entity_type, entity_id)
        except NotFoundError:
            continue
        existing_ids = {str(item.get("id")) for item in payload.get(table, []) if isinstance(item, dict)}
        if record["id"] not in existing_ids:
            payload.setdefault(table, []).append(record)


def _parse_view_ref(ref: Any) -> tuple[str, str] | None:
    if not isinstance(ref, dict):
        return None
    entity_type = str(ref.get("entity_type") or "").strip()
    raw_id = str(ref.get("entity_id") or ref.get("id") or "").strip()
    if not entity_type or not raw_id:
        return None
    entity_id = raw_id.split(":", 1)[1] if ":" in raw_id else raw_id
    return entity_type, entity_id
