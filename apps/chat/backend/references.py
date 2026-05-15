"""Chat app reference entity operations."""

from __future__ import annotations

from chat_state import list_projects
from errors import ChatValidationError

REFERENCE_ENTITY_TYPES = {"project"}

REFERENCE_MANIFEST = {
    "app_id": "chat",
    "schema_version": "1",
    "entity_types": [
        {
            "entity_type": "project",
            "display_name": "Chat Project",
            "id_stability": "stable",
            "searchable": True,
            "resolvable": True,
            "summarizable": True,
            "deep_link_supported": True,
        },
    ],
}


def reference_search(state: dict, body: dict) -> dict:
    entity_type = _reference_entity_type(body)
    query = str(body.get("query") if "query" in body else body.get("q") or "").strip().casefold()
    limit = _limit(body)
    items = _reference_items(state, entity_type)
    if query:
        items = [
            item
            for item in items
            if query in item["title"].casefold()
            or query in item["summary"].casefold()
            or query in item["entity_id"].casefold()
        ]
    return {"results": items[:limit], "payload_profile": "compact"}


def reference_resolve(state: dict, body: dict) -> dict:
    entity_type = _reference_entity_type(body)
    entity_id = _reference_entity_id(body)
    item = next((candidate for candidate in _reference_items(state, entity_type) if candidate["entity_id"] == entity_id), None)
    if item is None:
        return {"exists": False, "app_id": "chat", "entity_type": entity_type, "entity_id": entity_id}
    return {"exists": True, **item}


def reference_summarize(state: dict, body: dict) -> dict:
    resolved = reference_resolve(state, body)
    if not resolved.get("exists"):
        return {"summary": "", "safe_fields": {}, "source_updated_at": ""}
    return {
        "summary": resolved.get("summary") or resolved.get("title") or "",
        "safe_fields": {"title": resolved.get("title"), "entity_type": resolved.get("entity_type")},
        "source_updated_at": "",
    }


def _reference_items(state: dict, entity_type: str) -> list[dict]:
    if entity_type != "project":
        raise _entity_type_error(entity_type)
    return [
        {
            "app_id": "chat",
            "entity_type": "project",
            "entity_id": item["project_id"],
            "title": item["name"],
            "subtitle": "Chat project",
            "summary": f"Chat project updated at {item['updated_at']}" if item.get("updated_at") else "Chat project",
            "confidence": 1.0,
            "app_page": f"projects/{item['project_id']}",
            "deep_link": f"/app/chat/projects/{item['project_id']}",
        }
        for item in list_projects(state)
    ]


def _reference_entity_type(body: dict) -> str:
    entity_type = str(body.get("entity_type") or body.get("type") or "").strip()
    if entity_type not in REFERENCE_ENTITY_TYPES:
        raise _entity_type_error(entity_type)
    return entity_type


def _entity_type_error(entity_type: str) -> ChatValidationError:
    return ChatValidationError(
        f"Unsupported Chat reference entity type: {entity_type or '<empty>'}.",
        expected_fields=["entity_type"],
        accepted_aliases={"entity_type": ["type"]},
        allowed_values={"entity_type": sorted(REFERENCE_ENTITY_TYPES)},
        example={"action": "references.search", "entity_type": "project", "query": "client"},
    )


def _reference_entity_id(body: dict) -> str:
    entity_id = str(body.get("entity_id") or body.get("project_id") or body.get("id") or "").strip()
    if not entity_id:
        raise ChatValidationError(
            "Missing required field: entity_id.",
            expected_fields=["entity_id"],
            accepted_aliases={"entity_id": ["project_id", "id"]},
            example={"action": "references.resolve", "entity_type": "project", "entity_id": "project-uuid"},
        )
    return entity_id


def _limit(body: dict) -> int:
    raw_limit = body.get("limit", 10)
    try:
        return max(1, min(int(raw_limit), 50))
    except (TypeError, ValueError) as error:
        raise ChatValidationError(
            "Field limit must be an integer from 1 to 50.",
            expected_fields=["limit"],
            allowed_values={"limit": ["1..50"]},
            example={"action": "references.search", "entity_type": "project", "limit": 10},
        ) from error
