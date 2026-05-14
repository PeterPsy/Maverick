"""Dynamic Views app service layer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re
import unicodedata
from typing import Any

from errors import DynamicViewsValidationError
from store import chat_render, create_instance, load_state, mutate_state, normalize_instance, seed_state

REFERENCE_MANIFEST = {
    "app_id": "dynamic-views",
    "schema_version": "1",
    "entity_types": [
        {"entity_type": "view", "display_name": "Dynamic View", "id_stability": "stable", "searchable": True, "resolvable": True, "summarizable": True, "deep_link_supported": True}
    ],
}


def app_events_for_action(action: str) -> list[dict]:
    if action in {"create", "delete"}:
        return [{"type": "maverick.app.data-changed", "resource": "views"}]
    if action in {"set_view_filter", "set_custom_view", "clear_custom_view"}:
        return [{"type": "maverick.app.data-changed", "resource": "view-state"}]
    return []


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _normalize_view_filter(raw_filter: object) -> dict[str, Any]:
    if not isinstance(raw_filter, dict):
        raw_filter = {}
    status = str(raw_filter.get("status") or "all").strip() or "all"
    if status not in {"all", "ready"}:
        status = "all"
    refs = []
    for item in raw_filter.get("refs") if isinstance(raw_filter.get("refs"), list) else []:
        if not isinstance(item, dict):
            continue
        entity_id = str(item.get("entity_id") or "").strip()
        if str(item.get("entity_type") or "") == "view" and entity_id:
            refs.append({"entity_type": "view", "entity_id": entity_id})
    return {
        "mode": "custom" if str(raw_filter.get("mode") or "") == "custom" else "search",
        "query": str(raw_filter.get("query") or "").strip(),
        "status": status,
        "title": str(raw_filter.get("title") or "").strip(),
        "refs": refs,
        "updated_at": str(raw_filter.get("updated_at") or _now()),
    }


def _view_state(data_root: Path) -> dict[str, Any]:
    state, _result = mutate_state(
        data_root,
        lambda current: current.update({"view_filter": _normalize_view_filter(current.get("view_filter"))}) or {},
    )
    return {"view_filter": state["view_filter"]}


def _set_view_filter(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    def _update(state: dict) -> dict:
        current = _normalize_view_filter(state.get("view_filter"))
        preserve_custom = bool(body.get("preserve_custom")) and current.get("mode") == "custom"
        state["view_filter"] = _normalize_view_filter(
            {
                "mode": "custom" if preserve_custom else "search",
                "query": body.get("query") if "query" in body else current.get("query"),
                "status": body.get("status") if "status" in body else current.get("status"),
                "title": current.get("title") if preserve_custom else "",
                "refs": current.get("refs") if preserve_custom else [],
                "updated_at": _now(),
            }
        )
        return {}

    state, _result = mutate_state(data_root, _update)
    return {"view_filter": state["view_filter"]}


def _set_custom_view(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    def _update(state: dict) -> dict:
        state["view_filter"] = _normalize_view_filter(
            {
                "mode": "custom",
                "query": body.get("query"),
                "status": body.get("status"),
                "title": body.get("title"),
                "refs": body.get("refs") if isinstance(body.get("refs"), list) else [],
                "updated_at": _now(),
            }
        )
        return {}

    state, _result = mutate_state(data_root, _update)
    return {"view_filter": state["view_filter"]}


def _clear_custom_view(data_root: Path) -> dict[str, Any]:
    def _update(state: dict) -> dict:
        current = _normalize_view_filter(state.get("view_filter"))
        state["view_filter"] = _normalize_view_filter(
            {
                "mode": "search",
                "query": current.get("query"),
                "status": current.get("status"),
                "title": "",
                "refs": [],
                "updated_at": _now(),
            }
        )
        return {}

    state, _result = mutate_state(data_root, _update)
    return {"view_filter": state["view_filter"]}


def _owner_user_id(body: dict[str, Any], source_instance_id: str | None) -> str:
    owner = str(body.get("owner_user_id") or "").strip()
    if owner:
        return owner
    source = str(source_instance_id or body.get("source_instance_id") or "").strip()
    return source or "workspace"


def _target_id(body: dict[str, Any]) -> str:
    return str(body.get("id") or body.get("target_id") or body.get("instance_id") or "").strip()


def _requested_view_ids(body: dict[str, Any]) -> list[str]:
    raw_value = body.get("view_ids") or body.get("ids")
    if raw_value is None:
        raw_value = body.get("refs")
    if not isinstance(raw_value, list):
        return []
    ids: list[str] = []
    for item in raw_value:
        if isinstance(item, dict):
            if str(item.get("entity_type") or "") != "view":
                continue
            value = str(item.get("entity_id") or "").strip()
        else:
            value = str(item or "").strip()
        if value and value not in ids:
            ids.append(value)
    return ids


def _normalize_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char)).casefold()


def _search_tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", _normalize_search_text(value)) if token]


def _token_matches(haystack: str, token: str) -> bool:
    if token in haystack:
        return True
    return len(token) > 3 and token.endswith("s") and token[:-1] in haystack


def _item_matches_query(item: dict, query: str) -> bool:
    if not query:
        return True
    package = item.get("package") if isinstance(item.get("package"), dict) else {}
    bindings = item.get("data_bindings") if isinstance(item.get("data_bindings"), list) else []
    searchable_values = [
        item.get("title"),
        item.get("summary"),
        item.get("id"),
        item.get("status"),
        item.get("snapshot_mode"),
        package.get("title"),
        package.get("summary"),
        package.get("renderer"),
        *list(package.get("tags") or []),
    ]
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        searchable_values.extend([binding.get("source_type"), binding.get("source_ref"), binding.get("query")])
    haystack = _normalize_search_text(" ".join(str(value or "") for value in searchable_values))
    normalized_query = _normalize_search_text(query)
    if normalized_query in haystack:
        return True
    tokens = _search_tokens(query)
    return bool(tokens) and all(_token_matches(haystack, token) for token in tokens)


def _filtered_items(items: list[dict], body: dict[str, Any]) -> list[dict]:
    requested_ids = _requested_view_ids(body)
    if requested_ids:
        by_id = {item["id"]: item for item in items}
        items = [by_id[item_id] for item_id in requested_ids if item_id in by_id]
    status = str(body.get("status") or "all").strip()
    if status == "ready":
        items = [item for item in items if str(item.get("status") or "ready") == "ready"]
    query = str(body.get("query") or "").strip()
    if query:
        items = [item for item in items if _item_matches_query(item, query)]
    return items


def _hydrate_all(state: dict) -> list[dict]:
    items: list[dict] = []
    for instance in state["instances"]:
        package = next((item for item in state["packages"] if item.get("id") == instance.get("package_id")), None)
        if package is not None:
            items.append(normalize_instance(instance, package))
    return sorted(items, key=lambda item: item["updated_at"], reverse=True)


def _view_reference(item: dict) -> dict:
    return {
        "app_id": "dynamic-views",
        "entity_type": "view",
        "entity_id": item["id"],
        "title": item["title"],
        "subtitle": item.get("status") or "ready",
        "summary": item.get("summary") or "",
        "confidence": 1.0,
        "deep_link": f"/apps/dynamic-views/{item['id']}",
    }


def _read_instance(data_root: Path, instance_id: str) -> dict:
    if not instance_id:
        raise DynamicViewsValidationError("Dynamic view id is required.")
    state = load_state(data_root)
    for item in _hydrate_all(state):
        if item["id"] == instance_id:
            return item
    raise DynamicViewsValidationError("Dynamic view instance not found.")


def _delete_instance(data_root: Path, instance_id: str) -> dict:
    if not instance_id:
        raise DynamicViewsValidationError("Dynamic view id is required.")

    def _update(state: dict) -> dict:
        before = len(state["instances"])
        state["instances"] = [item for item in state["instances"] if item.get("id") != instance_id]
        return {"deleted": before - len(state["instances"])}

    _state, result = mutate_state(data_root, _update)
    deleted = result["deleted"]
    return {"action": "delete", "summary": f"dynamic view delete | id={instance_id} | deleted={deleted}", "status": "ok", "deleted": deleted}


def handle_action(
    data_root: Path,
    *,
    workspace_id: str,
    source_instance_id: str | None,
    body: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    action = str(body.get("action") or "list").strip().lower()
    if action in {"catalog", "list"}:
        items = _filtered_items(_hydrate_all(load_state(data_root)), body)
        limit = max(1, min(int(body.get("limit") or 100), 500))
        return 200, {"action": "list", "summary": f"dynamic views list | count={len(items[:limit])}", "items": items[:limit]}
    if action == "view_filter":
        return 200, {"state": _view_state(data_root)}
    if action == "set_view_filter":
        return 200, {"state": _set_view_filter(data_root, body)}
    if action == "set_custom_view":
        return 200, {"state": _set_custom_view(data_root, body)}
    if action == "clear_custom_view":
        return 200, {"state": _clear_custom_view(data_root)}
    if action == "create":
        return 200, create_instance(
            data_root,
            workspace_id=workspace_id,
            owner_user_id=_owner_user_id(body, source_instance_id),
            source_instance_id=source_instance_id or str(body.get("source_instance_id") or "").strip() or None,
            payload=body,
        )
    if action in {"read", "recall"}:
        instance = _read_instance(data_root, _target_id(body))
        return 200, {
            "action": action,
            "summary": f"dynamic view {action} | id={instance['id']} | title={instance['title']}",
            "instance": instance,
            "chat_render": chat_render(instance),
        }
    if action == "delete":
        return 200, _delete_instance(data_root, _target_id(body))
    if action == "health.check":
        state = seed_state(data_root)
        return 200, {"status": "ok", "package_count": len(state["packages"]), "instance_count": len(state["instances"])}
    if action == "references.manifest":
        return 200, REFERENCE_MANIFEST
    if action == "references.search":
        query = str(body.get("query") or "").casefold()
        items = [_view_reference(item) for item in _hydrate_all(load_state(data_root))]
        if query:
            items = [item for item in items if query in item["title"].casefold() or query in item["summary"].casefold() or query in item["entity_id"].casefold()]
        return 200, {"results": items[: max(1, min(int(body.get("limit") or 10), 50))]}
    if action == "references.resolve":
        entity_id = str(body.get("entity_id") or "").strip()
        item = next((candidate for candidate in _hydrate_all(load_state(data_root)) if candidate["id"] == entity_id), None)
        return 200, {"exists": False, "app_id": "dynamic-views", "entity_type": "view", "entity_id": entity_id} if item is None else {"exists": True, **_view_reference(item)}
    if action == "references.summarize":
        entity_id = str(body.get("entity_id") or "").strip()
        item = next((candidate for candidate in _hydrate_all(load_state(data_root)) if candidate["id"] == entity_id), None)
        return 200, {"summary": "", "safe_fields": {}, "source_updated_at": ""} if item is None else {
            "summary": item.get("summary") or item.get("title") or "",
            "safe_fields": {"title": item.get("title"), "status": item.get("status")},
            "source_updated_at": item.get("updated_at", ""),
        }
    raise DynamicViewsValidationError(f"Unsupported dynamic view action: {action}")
