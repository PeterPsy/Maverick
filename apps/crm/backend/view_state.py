"""CRM view-composition state helpers."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from database import normalize_entity_type
from errors import CrmValidationError


SCHEMA_VERSION = "1"
MAX_VIEW_QUERY_CHARS = 200
MAX_CUSTOM_VIEW_TITLE_CHARS = 140
MAX_CUSTOM_VIEW_REFS = 500
VIEW_ENTITY_TYPES = {"all", "account", "contact", "deal", "activity"}


def view_state_path(data_root: Path) -> Path:
    return data_root / "view_state.json"


def default_view_filter() -> dict[str, Any]:
    return {
        "mode": "search",
        "title": "",
        "query": "",
        "entity_type": "all",
        "refs": [],
        "updated_at": "",
    }


def _normalize_entity_filter(raw_entity_type: object) -> str:
    entity_type = str(raw_entity_type or "all").strip()
    if entity_type not in VIEW_ENTITY_TYPES:
        raise CrmValidationError(f"Unsupported view entity_type `{entity_type}`.")
    return entity_type


def _normalize_ref(raw_ref: object) -> dict[str, str] | None:
    if isinstance(raw_ref, str):
        entity_type, separator, entity_id = raw_ref.partition(":")
        if not separator:
            return None
        return {
            "entity_type": normalize_entity_type(entity_type),
            "entity_id": str(entity_id or "").strip(),
        }
    if not isinstance(raw_ref, dict):
        return None
    app_id = str(raw_ref.get("app_id") or "crm").strip()
    if app_id and app_id != "crm":
        raise CrmValidationError("CRM custom view refs must target app_id `crm`.")
    entity_type = normalize_entity_type(str(raw_ref.get("entity_type") or raw_ref.get("type") or ""))
    entity_id = str(raw_ref.get("entity_id") or raw_ref.get("id") or "").strip()
    if not entity_id:
        raise CrmValidationError("CRM custom view refs require entity_id.")
    return {"entity_type": entity_type, "entity_id": entity_id}


def _refs_from_typed_ids(body: dict[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    typed_keys = {
        "account_ids": "account",
        "contact_ids": "contact",
        "deal_ids": "deal",
        "activity_ids": "activity",
    }
    for key, entity_type in typed_keys.items():
        values = body.get(key)
        if values is None:
            continue
        if not isinstance(values, list):
            raise CrmValidationError(f"{key} must be a list.")
        for value in values:
            entity_id = str(value or "").strip()
            if entity_id:
                refs.append({"entity_type": entity_type, "entity_id": entity_id})
    return refs


def normalize_custom_refs(*, refs: object = None, entity_references: object = None, body: dict[str, Any] | None = None) -> list[dict[str, str]]:
    raw_refs: list[object] = []
    for value in (refs, entity_references):
        if value is None:
            continue
        if not isinstance(value, list):
            raise CrmValidationError("CRM custom view refs must be a list.")
        raw_refs.extend(value)
    normalized: list[dict[str, str]] = []
    if body is not None:
        normalized.extend(_refs_from_typed_ids(body))
    for raw_ref in raw_refs:
        ref = _normalize_ref(raw_ref)
        if ref is not None:
            normalized.append(ref)
    seen: set[tuple[str, str]] = set()
    unique_refs: list[dict[str, str]] = []
    for ref in normalized:
        key = (ref["entity_type"], ref["entity_id"])
        if key in seen:
            continue
        seen.add(key)
        unique_refs.append(ref)
        if len(unique_refs) > MAX_CUSTOM_VIEW_REFS:
            raise CrmValidationError(f"CRM custom views can include at most {MAX_CUSTOM_VIEW_REFS} refs.")
    return unique_refs


def normalize_view_filter(raw_filter: object) -> dict[str, Any]:
    if not isinstance(raw_filter, dict):
        return default_view_filter()
    mode = str(raw_filter.get("mode") or "search").strip()
    if mode not in {"search", "custom"}:
        raise CrmValidationError(f"Unsupported CRM view mode `{mode}`.")
    title = " ".join(str(raw_filter.get("title") or "").split())[:MAX_CUSTOM_VIEW_TITLE_CHARS]
    query = " ".join(str(raw_filter.get("query") or "").split())[:MAX_VIEW_QUERY_CHARS]
    return {
        "mode": mode,
        "title": title,
        "query": query,
        "entity_type": _normalize_entity_filter(raw_filter.get("entity_type")),
        "refs": normalize_custom_refs(refs=raw_filter.get("refs")),
        "updated_at": str(raw_filter.get("updated_at") or "").strip(),
    }


def load_view_state(data_root: Path) -> dict[str, Any]:
    data_root.mkdir(parents=True, exist_ok=True)
    path = view_state_path(data_root)
    if not path.exists():
        return write_view_state(data_root, {"schema_version": SCHEMA_VERSION, "view_filter": default_view_filter()})
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CrmValidationError("CRM view state must be a JSON object.")
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload["view_filter"] = normalize_view_filter(payload.get("view_filter"))
    return payload


def write_view_state(data_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    data_root.mkdir(parents=True, exist_ok=True)
    normalized = dict(payload)
    normalized["schema_version"] = SCHEMA_VERSION
    normalized["view_filter"] = normalize_view_filter(normalized.get("view_filter"))
    view_state_path(data_root).write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return normalized


def set_view_filter_payload(*, data_root: Path, query: object = None, entity_type: object = None, preserve_custom: bool = False) -> dict[str, Any]:
    state = load_view_state(data_root)
    current = normalize_view_filter(state.get("view_filter"))
    next_filter = {
        "mode": current["mode"] if preserve_custom else "search",
        "title": current["title"] if preserve_custom else "",
        "query": current["query"] if query is None else query,
        "entity_type": current["entity_type"] if entity_type is None else entity_type,
        "refs": current["refs"] if preserve_custom else [],
        "updated_at": datetime.now(tz=UTC).isoformat(),
    }
    state["view_filter"] = normalize_view_filter(next_filter)
    return {"state": write_view_state(data_root, state)}


def set_custom_view_payload(*, data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    refs = normalize_custom_refs(
        refs=body.get("refs"),
        entity_references=body.get("entity_references"),
        body=body,
    )
    state = load_view_state(data_root)
    state["view_filter"] = normalize_view_filter(
        {
            "mode": "custom",
            "title": body.get("title") or "Custom CRM view",
            "query": body.get("query") if "query" in body else "",
            "entity_type": body.get("entity_type") if "entity_type" in body else "all",
            "refs": refs,
            "updated_at": datetime.now(tz=UTC).isoformat(),
        }
    )
    return {"state": write_view_state(data_root, state)}


def clear_custom_view_payload(*, data_root: Path) -> dict[str, Any]:
    state = load_view_state(data_root)
    state["view_filter"] = default_view_filter() | {"updated_at": datetime.now(tz=UTC).isoformat()}
    return {"state": write_view_state(data_root, state)}
