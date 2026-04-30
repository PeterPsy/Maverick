"""Memory view-composition state helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.app_sdk.storage import read_json_state, write_json_state
from errors import MemoryValidationError


SCHEMA_VERSION = "1"
MAX_VIEW_QUERY_CHARS = 200
MAX_CUSTOM_VIEW_TITLE_CHARS = 140
MAX_CUSTOM_VIEW_REFS = 500


def view_state_path(data_root: Path) -> Path:
    return data_root / "view_state.json"


def default_view_filter() -> dict[str, Any]:
    return {
        "mode": "search",
        "title": "",
        "query": "",
        "refs": [],
        "updated_at": "",
    }


def _normalize_ref(raw_ref: object) -> dict[str, str] | None:
    if isinstance(raw_ref, str):
        entity_type, separator, entity_id = raw_ref.partition(":")
        if not separator:
            entity_type = "node"
            entity_id = raw_ref
        if entity_type != "node":
            raise MemoryValidationError("Memory custom view refs must target entity_type `node`.")
        node_id = str(entity_id or "").strip()
        return {"entity_type": "node", "entity_id": node_id} if node_id else None
    if not isinstance(raw_ref, dict):
        return None
    app_id = str(raw_ref.get("app_id") or "memory").strip()
    if app_id and app_id != "memory":
        raise MemoryValidationError("Memory custom view refs must target app_id `memory`.")
    entity_type = str(raw_ref.get("entity_type") or raw_ref.get("type") or "node").strip()
    if entity_type != "node":
        raise MemoryValidationError("Memory custom view refs must target entity_type `node`.")
    entity_id = str(raw_ref.get("entity_id") or raw_ref.get("node_id") or raw_ref.get("id") or "").strip()
    if not entity_id:
        raise MemoryValidationError("Memory custom view refs require entity_id.")
    return {"entity_type": "node", "entity_id": entity_id}


def _refs_from_node_ids(body: dict[str, Any]) -> list[dict[str, str]]:
    values = body.get("node_ids")
    if values is None:
        return []
    if not isinstance(values, list):
        raise MemoryValidationError("node_ids must be a list.")
    return [{"entity_type": "node", "entity_id": str(value or "").strip()} for value in values if str(value or "").strip()]


def normalize_custom_refs(*, refs: object = None, entity_references: object = None, body: dict[str, Any] | None = None) -> list[dict[str, str]]:
    raw_refs: list[object] = []
    for value in (refs, entity_references):
        if value is None:
            continue
        if not isinstance(value, list):
            raise MemoryValidationError("Memory custom view refs must be a list.")
        raw_refs.extend(value)
    normalized = _refs_from_node_ids(body) if body is not None else []
    for raw_ref in raw_refs:
        ref = _normalize_ref(raw_ref)
        if ref is not None:
            normalized.append(ref)
    seen: set[str] = set()
    unique_refs: list[dict[str, str]] = []
    for ref in normalized:
        entity_id = ref["entity_id"]
        if entity_id in seen:
            continue
        seen.add(entity_id)
        unique_refs.append(ref)
        if len(unique_refs) > MAX_CUSTOM_VIEW_REFS:
            raise MemoryValidationError(f"Memory custom views can include at most {MAX_CUSTOM_VIEW_REFS} refs.")
    return unique_refs


def normalize_view_filter(raw_filter: object) -> dict[str, Any]:
    if not isinstance(raw_filter, dict):
        return default_view_filter()
    mode = str(raw_filter.get("mode") or "search").strip()
    if mode not in {"search", "custom"}:
        raise MemoryValidationError(f"Unsupported Memory view mode `{mode}`.")
    title = " ".join(str(raw_filter.get("title") or "").split())[:MAX_CUSTOM_VIEW_TITLE_CHARS]
    query = " ".join(str(raw_filter.get("query") or "").split())[:MAX_VIEW_QUERY_CHARS]
    return {
        "mode": mode,
        "title": title,
        "query": query,
        "refs": normalize_custom_refs(refs=raw_filter.get("refs")),
        "updated_at": str(raw_filter.get("updated_at") or "").strip(),
    }


def load_view_state(data_root: Path) -> dict[str, Any]:
    data_root.mkdir(parents=True, exist_ok=True)
    path = view_state_path(data_root)
    if not path.exists():
        return write_view_state(data_root, {"schema_version": SCHEMA_VERSION, "view_filter": default_view_filter()})
    payload = read_json_state(data_root, "view_state.json")
    if not isinstance(payload, dict):
        raise MemoryValidationError("Memory view state must be a JSON object.")
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload["view_filter"] = normalize_view_filter(payload.get("view_filter"))
    return payload


def write_view_state(data_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    data_root.mkdir(parents=True, exist_ok=True)
    normalized = dict(payload)
    normalized["schema_version"] = SCHEMA_VERSION
    normalized["view_filter"] = normalize_view_filter(normalized.get("view_filter"))
    write_json_state(data_root, "view_state.json", normalized)
    return normalized


def set_view_filter_payload(*, data_root: Path, query: object = None, preserve_custom: bool = False) -> dict[str, Any]:
    state = load_view_state(data_root)
    current = normalize_view_filter(state.get("view_filter"))
    state["view_filter"] = normalize_view_filter(
        {
            "mode": current["mode"] if preserve_custom else "search",
            "title": current["title"] if preserve_custom else "",
            "query": current["query"] if query is None else query,
            "refs": current["refs"] if preserve_custom else [],
            "updated_at": datetime.now(tz=UTC).isoformat(),
        }
    )
    return {"state": write_view_state(data_root, state)}


def set_custom_view_payload(*, data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    refs = normalize_custom_refs(refs=body.get("refs"), entity_references=body.get("entity_references"), body=body)
    state = load_view_state(data_root)
    state["view_filter"] = normalize_view_filter(
        {
            "mode": "custom",
            "title": body.get("title") or "Custom Memory view",
            "query": body.get("query") if "query" in body else "",
            "refs": refs,
            "updated_at": datetime.now(tz=UTC).isoformat(),
        }
    )
    return {"state": write_view_state(data_root, state)}


def clear_custom_view_payload(*, data_root: Path) -> dict[str, Any]:
    state = load_view_state(data_root)
    state["view_filter"] = default_view_filter() | {"updated_at": datetime.now(tz=UTC).isoformat()}
    return {"state": write_view_state(data_root, state)}
