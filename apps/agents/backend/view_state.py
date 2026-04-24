"""Persisted view-surface state for the Agents app."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from store import AgentsValidationError


SCHEMA_VERSION = "1"
VIEW_STATE_FILENAME = "view_state.json"


def utcnow() -> str:
    return datetime.now(tz=UTC).isoformat()


def state_path(data_root: Path) -> Path:
    return data_root / VIEW_STATE_FILENAME


def default_view_filter() -> dict[str, Any]:
    return {
        "mode": "search",
        "query": "",
        "entity_type": "all",
        "title": "",
        "refs": [],
        "updated_at": utcnow(),
    }


def normalize_view_filter(raw_filter: object) -> dict[str, Any]:
    if not isinstance(raw_filter, dict):
        return default_view_filter()
    entity_type = str(raw_filter.get("entity_type") or "all").strip() or "all"
    if entity_type not in {"all", "agent_type", "role_prompt"}:
        raise AgentsValidationError("entity_type must be one of: all, agent_type, role_prompt")
    refs: list[dict[str, str]] = []
    for item in raw_filter.get("refs") if isinstance(raw_filter.get("refs"), list) else []:
        if not isinstance(item, dict):
            continue
        ref_entity_type = str(item.get("entity_type") or "").strip()
        ref_entity_id = str(item.get("entity_id") or "").strip()
        if ref_entity_type not in {"agent_type", "role_prompt"} or not ref_entity_id:
            raise AgentsValidationError("custom view refs must target agent_type or role_prompt entities")
        refs.append({"entity_type": ref_entity_type, "entity_id": ref_entity_id})
    return {
        "mode": "custom" if str(raw_filter.get("mode") or "") == "custom" else "search",
        "query": str(raw_filter.get("query") or "").strip(),
        "entity_type": entity_type,
        "title": str(raw_filter.get("title") or "").strip(),
        "refs": refs,
        "updated_at": str(raw_filter.get("updated_at") or utcnow()),
    }


def write_view_state(data_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    data_root.mkdir(parents=True, exist_ok=True)
    state_path(data_root).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def load_view_state(data_root: Path) -> dict[str, Any]:
    path = state_path(data_root)
    if not path.exists():
        return write_view_state(data_root, {"schema_version": SCHEMA_VERSION, "view_filter": default_view_filter()})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload["schema_version"] = SCHEMA_VERSION
    payload["view_filter"] = normalize_view_filter(payload.get("view_filter"))
    return write_view_state(data_root, payload)


def set_view_filter_payload(*, data_root: Path, query: object = None, entity_type: object = None, preserve_custom: bool = False) -> dict[str, Any]:
    state = load_view_state(data_root)
    current = normalize_view_filter(state.get("view_filter"))
    state["view_filter"] = normalize_view_filter(
        {
            "mode": "custom" if preserve_custom and current.get("mode") == "custom" else "search",
            "query": str(query if query is not None else current.get("query") or "").strip(),
            "entity_type": str(entity_type if entity_type is not None else current.get("entity_type") or "all").strip() or "all",
            "title": str(current.get("title") or "") if preserve_custom and current.get("mode") == "custom" else "",
            "refs": list(current.get("refs") or []) if preserve_custom and current.get("mode") == "custom" else [],
            "updated_at": utcnow(),
        }
    )
    return write_view_state(data_root, state)


def set_custom_view_payload(*, data_root: Path, title: object = None, refs: object = None, query: object = None, entity_type: object = None) -> dict[str, Any]:
    state = load_view_state(data_root)
    state["view_filter"] = normalize_view_filter(
        {
            "mode": "custom",
            "query": str(query or "").strip(),
            "entity_type": str(entity_type or "all").strip() or "all",
            "title": str(title or "").strip(),
            "refs": refs if isinstance(refs, list) else [],
            "updated_at": utcnow(),
        }
    )
    return write_view_state(data_root, state)


def clear_custom_view_payload(*, data_root: Path) -> dict[str, Any]:
    state = load_view_state(data_root)
    current = normalize_view_filter(state.get("view_filter"))
    state["view_filter"] = normalize_view_filter(
        {
            "mode": "search",
            "query": current.get("query"),
            "entity_type": current.get("entity_type"),
            "title": "",
            "refs": [],
            "updated_at": utcnow(),
        }
    )
    return write_view_state(data_root, state)
