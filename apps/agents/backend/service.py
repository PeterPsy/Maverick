"""Agents app service shared by backend, MCP, and CLI."""

from __future__ import annotations

from pathlib import Path

from agent_definitions import (
    UPSERT_ERROR_HINT,
    catalog,
    compact_catalog,
    get_agent_definition,
    upsert_agent_definition,
)
from seeds import seed_defaults
from store import (
    AgentsValidationError,
    delete_agent_definition,
    list_agent_definitions,
)
from surface_manifest import OPERATIONS_MANIFEST
from view_state import (
    clear_custom_view_payload,
    load_view_state,
    set_custom_view_payload,
    set_view_filter_payload,
)


REFERENCE_MANIFEST = {
    "app_id": "agents",
    "schema_version": "2",
    "entity_types": [{
        "entity_type": "agent_type",
        "display_name": "Agent",
        "id_stability": "stable",
        "searchable": True,
        "resolvable": True,
        "summarizable": True,
        "deep_link_supported": True,
    }],
}
DATA_CHANGED_ACTIONS = {
    "upsert_agent_definition",
    "delete_agent_definition",
}
VIEW_STATE_ACTIONS = {"set_view_filter", "set_custom_view", "clear_custom_view"}


def app_events_for_action(action: str) -> list[dict]:
    if action in DATA_CHANGED_ACTIONS:
        return [{"type": "maverick.app.data-changed", "resource": "configuration"}]
    if action in VIEW_STATE_ACTIONS:
        return [{"type": "maverick.app.data-changed", "resource": "view-state"}]
    return []


def app_events_for_result(action: str, result: dict) -> list[dict]:
    if action == "upsert_agent_definition" and not (
        result.get("created") or result.get("changed")
    ):
        return []
    return app_events_for_action(action)


def validation_error_payload(error: AgentsValidationError, operation: str) -> dict:
    payload = {
        "error": "validation_error",
        "operation": operation,
        "detail": str(error),
    }
    if operation == "upsert_agent_definition":
        payload.update(UPSERT_ERROR_HINT)
    return payload


def _reference_items(data_root: Path) -> list[dict]:
    return [
        {
            "app_id": "agents",
            "entity_type": "agent_type",
            "entity_id": item["id"],
            "title": item["name"],
            "subtitle": "Agent",
            "summary": item.get("description", ""),
            "confidence": 1.0,
            "deep_link": f"/apps/agents/agent-types/{item['id']}",
        }
        for item in list_agent_definitions(data_root)
    ]


def _require_agent_entity_type(body: dict) -> None:
    entity_type = str(body.get("entity_type") or body.get("type") or "").strip()
    if entity_type != "agent_type":
        raise AgentsValidationError("Unsupported reference entity type")


def reference_search(data_root: Path, body: dict) -> dict:
    _require_agent_entity_type(body)
    query = str(body.get("query") or "").strip().casefold()
    try:
        limit = max(1, min(int(body.get("limit") or 10), 50))
    except (TypeError, ValueError) as error:
        raise AgentsValidationError("Field `limit` must be an integer.") from error
    items = _reference_items(data_root)
    if query:
        items = [
            item for item in items
            if any(
                query in str(item.get(field) or "").casefold()
                for field in ("title", "summary", "entity_id")
            )
        ]
    return {"results": items[:limit]}


def reference_resolve(data_root: Path, body: dict) -> dict:
    _require_agent_entity_type(body)
    entity_id = str(body.get("entity_id") or "").strip()
    item = next(
        (candidate for candidate in _reference_items(data_root) if candidate["entity_id"] == entity_id),
        None,
    )
    if item is None:
        return {
            "exists": False,
            "app_id": "agents",
            "entity_type": "agent_type",
            "entity_id": entity_id,
        }
    return {"exists": True, **item}


def reference_summarize(data_root: Path, body: dict) -> dict:
    resolved = reference_resolve(data_root, body)
    if not resolved.get("exists"):
        return {"summary": "", "safe_fields": {}, "source_updated_at": ""}
    return {
        "summary": resolved.get("summary") or resolved.get("title") or "",
        "safe_fields": {
            "title": resolved.get("title"),
            "subtitle": resolved.get("subtitle"),
        },
        "source_updated_at": "",
    }


def handle_action(data_root: Path, body: dict) -> tuple[int, dict]:
    action = str(body.get("action") or "operations.manifest")
    seed_defaults(data_root)
    if action == "operations.manifest":
        return 200, OPERATIONS_MANIFEST
    if action == "catalog.compact":
        return 200, compact_catalog(data_root, body)
    if action == "catalog":
        return 200, catalog(data_root)
    if action == "get_agent_definition":
        return 200, get_agent_definition(data_root, body)
    if action == "upsert_agent_definition":
        return 200, upsert_agent_definition(data_root, body)
    if action == "delete_agent_definition":
        deleted = delete_agent_definition(
            data_root,
            str(body.get("id") or body.get("agent_type_id") or ""),
        )
        return (200, {"deleted": True}) if deleted else (404, {"error": "agent_not_found"})
    if action == "view_filter":
        return 200, {"state": load_view_state(data_root)}
    if action == "set_view_filter":
        return 200, {"state": set_view_filter_payload(
            data_root=data_root,
            query=body.get("query"),
            entity_type=body.get("entity_type"),
            preserve_custom=bool(body.get("preserve_custom")),
        )}
    if action == "set_custom_view":
        return 200, {"state": set_custom_view_payload(
            data_root=data_root,
            title=body.get("title"),
            refs=body.get("refs"),
            query=body.get("query"),
            entity_type=body.get("entity_type"),
        )}
    if action == "clear_custom_view":
        return 200, {"state": clear_custom_view_payload(data_root=data_root)}
    if action == "health.check":
        return 200, {"status": "ok", "data_root": str(data_root)}
    if action == "references.manifest":
        return 200, REFERENCE_MANIFEST
    if action == "references.search":
        return 200, reference_search(data_root, body)
    if action == "references.resolve":
        return 200, reference_resolve(data_root, body)
    if action == "references.summarize":
        return 200, reference_summarize(data_root, body)
    return 400, {"error": "unsupported_action", "action": action}
