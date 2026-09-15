"""Persisted search and curated-view state for agent definitions."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from core.app_sdk.storage import read_json_state, write_json_state
from store import AgentsValidationError


SCHEMA_VERSION = "2"
VIEW_STATE_FILENAME = "view_state.json"


def utcnow() -> str:
    return datetime.now(tz=UTC).isoformat()


def default_view_filter() -> dict[str, Any]:
    return {
        "mode": "search",
        "query": "",
        "entity_type": "all",
        "title": "",
        "refs": [],
        "updated_at": utcnow(),
    }


def normalize_view_filter(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return default_view_filter()
    entity_type = str(value.get("entity_type") or "all").strip()
    if entity_type not in {"all", "agent_type"}:
        raise AgentsValidationError("entity_type must be all or agent_type")
    refs: list[dict[str, str]] = []
    for item in value.get("refs") if isinstance(value.get("refs"), list) else []:
        if not isinstance(item, dict):
            continue
        entity_id = str(item.get("entity_id") or "").strip()
        if item.get("entity_type") != "agent_type" or not entity_id:
            raise AgentsValidationError("custom view refs must target agent_type")
        refs.append({"entity_type": "agent_type", "entity_id": entity_id})
    return {
        "mode": "custom" if value.get("mode") == "custom" else "search",
        "query": str(value.get("query") or "").strip(),
        "entity_type": entity_type,
        "title": str(value.get("title") or "").strip(),
        "refs": refs,
        "updated_at": str(value.get("updated_at") or utcnow()),
    }


def _write(data_root: Path, view_filter: dict[str, Any]) -> dict[str, Any]:
    data_root.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": SCHEMA_VERSION, "view_filter": view_filter}
    write_json_state(data_root, VIEW_STATE_FILENAME, payload)
    return payload


def load_view_state(data_root: Path) -> dict[str, Any]:
    try:
        payload = read_json_state(data_root, VIEW_STATE_FILENAME, {})
    except (ValueError, json.JSONDecodeError):
        payload = {}
    normalized = normalize_view_filter(
        payload.get("view_filter") if isinstance(payload, dict) else None
    )
    return _write(data_root, normalized)


def set_view_filter_payload(
    *, data_root: Path, query: object, entity_type: object, preserve_custom: bool
) -> dict[str, Any]:
    current = load_view_state(data_root)["view_filter"]
    if preserve_custom and current["mode"] == "custom":
        return {"schema_version": SCHEMA_VERSION, "view_filter": current}
    return _write(data_root, normalize_view_filter({
        "query": query,
        "entity_type": entity_type or "all",
    }))


def set_custom_view_payload(
    *, data_root: Path, title: object, refs: object, query: object, entity_type: object
) -> dict[str, Any]:
    return _write(data_root, normalize_view_filter({
        "mode": "custom",
        "title": title,
        "refs": refs,
        "query": query,
        "entity_type": entity_type or "all",
    }))


def clear_custom_view_payload(*, data_root: Path) -> dict[str, Any]:
    return _write(data_root, default_view_filter())
