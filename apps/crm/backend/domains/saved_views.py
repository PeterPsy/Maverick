"""Saved view and view-state service domain for CRM."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from errors import NotFoundError, ValidationError
from store import new_id, require_text, row_to_dict, utc_now, write_event


VIEW_ENTITY_TYPES = {"all", "lead", "account", "contact", "deal", "activity", "task", "note"}


def list_saved_views(db) -> list[dict[str, Any]]:
    rows = db.execute("SELECT * FROM saved_views ORDER BY updated_at DESC").fetchall()
    return [_saved_view_from_row(row) for row in rows]


def save_view(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    view_id = require_text(payload, "id") or new_id("view")
    title = require_text(payload, "title", required=True)
    entity_type = _view_entity_type(payload)
    query = require_text(payload, "query")
    filters = payload.get("filters") or {}
    refs = payload.get("refs") or []
    if not isinstance(filters, dict):
        raise ValidationError("`filters` must be an object.")
    if not isinstance(refs, list):
        raise ValidationError("`refs` must be an array.")
    db.execute(
        """
        INSERT INTO saved_views(id, title, entity_type, query, filters_json, refs_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET title = excluded.title, entity_type = excluded.entity_type, query = excluded.query,
          filters_json = excluded.filters_json, refs_json = excluded.refs_json, updated_at = excluded.updated_at
        """,
        (view_id, title, entity_type, query, json.dumps(filters, ensure_ascii=True, sort_keys=True), json.dumps(refs, ensure_ascii=True), now, now),
    )
    write_event(db, "saved_view.saved", "saved_view", view_id)
    return _saved_view_from_row(db.execute("SELECT * FROM saved_views WHERE id = ?", (view_id,)).fetchone())


def delete_saved_view(db, payload: dict[str, Any]) -> dict[str, Any]:
    view_id = require_text(payload, "id", required=True)
    db.execute("DELETE FROM saved_views WHERE id = ?", (view_id,))
    write_event(db, "saved_view.deleted", "saved_view", view_id)
    return {"ok": True, "id": view_id}


def apply_saved_view(db, data_root: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    view_id = require_text(payload, "id", required=True)
    row = db.execute("SELECT * FROM saved_views WHERE id = ?", (view_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"saved_view `{view_id}` was not found.")
    saved_view = _saved_view_from_row(row)
    refs = saved_view.get("refs") if isinstance(saved_view.get("refs"), list) else []
    if refs:
        return write_view_state(data_root, {"mode": "custom", "query": "", "entity_type": "all", "refs": refs, "title": saved_view["title"], "updated_at": utc_now()})
    return write_view_state(
        data_root,
        {
            "mode": "search",
            "query": str(saved_view.get("query") or ""),
            "entity_type": str(saved_view.get("entity_type") or "all"),
            "filters": saved_view.get("filters") or {},
            "refs": [],
            "title": saved_view["title"],
            "updated_at": utc_now(),
        },
    )


def read_view_state(data_root: str | Path) -> dict[str, Any]:
    path = Path(data_root) / "view_state.json"
    if not path.exists():
        return {"schema_version": "1", "view_filter": {"entity_type": "all", "mode": "search", "query": "", "refs": [], "title": "", "updated_at": ""}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValidationError("CRM view state is invalid.")
    return payload


def write_view_state(data_root: str | Path, view_filter: dict[str, Any]) -> dict[str, Any]:
    payload = {"schema_version": "1", "view_filter": view_filter}
    path = Path(data_root) / "view_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return payload


def _saved_view_from_row(row) -> dict[str, Any]:
    item = row_to_dict(row)
    item["filters"] = json.loads(str(item.pop("filters_json", "{}") or "{}")) if "filters_json" in item else item.get("filters", {})
    item["refs"] = json.loads(str(item.pop("refs_json", "[]") or "[]")) if "refs_json" in item else item.get("refs", [])
    return item


def _view_entity_type(payload: dict[str, Any]) -> str:
    entity_type = require_text(payload, "entity_type", default="all") or "all"
    if entity_type not in VIEW_ENTITY_TYPES:
        raise ValidationError("Unsupported CRM entity_type.", details={"entity_type": entity_type})
    return entity_type
