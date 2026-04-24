"""CRM app service layer shared by backend, CLI, and MCP."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from errors import CrmValidationError
from store import (
    REFERENCE_MANIFEST,
    add_activity,
    create_account,
    create_contact,
    create_deal,
    health_payload,
    inspect_entity,
    link_entities,
    list_deals,
    list_recent,
    load_view_state,
    reference_resolve,
    reference_search,
    reference_summarize,
    search_records,
    clear_custom_view_payload,
    set_custom_view_payload,
    set_view_filter_payload,
    update_entity,
)


DATA_CHANGED_ACTIONS = {
    "add_activity",
    "create_account",
    "create_activity",
    "create_contact",
    "create_deal",
    "link",
    "link_entities",
    "update",
    "update_entity",
}
VIEW_STATE_ACTIONS = {"clear_custom_view", "set_custom_view", "set_view_filter"}


def app_events_for_action(action: str) -> list[dict[str, str]]:
    if action in DATA_CHANGED_ACTIONS:
        return [{"type": "maverick.app.data-changed", "owner_app_id": "crm", "resource": "records"}]
    if action in VIEW_STATE_ACTIONS:
        return [{"type": "maverick.app.data-changed", "owner_app_id": "crm", "resource": "view-state"}]
    return []


def action_from_tool(tool_name: str, fallback: str) -> str:
    mapping = {
        "crm_search": "search",
        "crm_get": "get",
        "crm_list_recent": "list_recent",
        "crm_list_deals": "list_deals",
        "crm_create_account": "create_account",
        "crm_create_contact": "create_contact",
        "crm_create_deal": "create_deal",
        "crm_add_activity": "add_activity",
        "crm_link_entities": "link_entities",
        "crm_reference_manifest": "references.manifest",
        "crm_reference_search": "references.search",
        "crm_reference_resolve": "references.resolve",
        "crm_reference_summarize": "references.summarize",
        "crm_view_filter": "view_filter",
        "crm_set_view_filter": "set_view_filter",
        "crm_set_custom_view": "set_custom_view",
        "crm_clear_custom_view": "clear_custom_view",
    }
    return mapping.get(tool_name, fallback)


def entity_id_from(body: dict[str, Any]) -> str:
    return str(body.get("entity_id") or body.get("id") or "").strip()


def handle_action(data_root: Path, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    action = str(body.get("action") or "search").strip()
    if action == "create_account":
        return 200, {"account": create_account(data_root, body)}
    if action == "create_contact":
        return 200, {"contact": create_contact(data_root, body)}
    if action == "create_deal":
        return 200, {"deal": create_deal(data_root, body)}
    if action in {"add_activity", "create_activity"}:
        return 200, {"activity": add_activity(data_root, body)}
    if action in {"update", "update_entity"}:
        entity_type = str(body.get("entity_type") or body.get("type") or "").strip()
        return 200, {"entity": update_entity(data_root, body), "entity_type": entity_type}
    if action in {"link_entities", "link"}:
        return 200, {"relationship": link_entities(data_root, body)}
    if action == "get":
        entity_type = str(body.get("entity_type") or body.get("type") or "").strip()
        return 200, {"entity": inspect_entity(data_root, entity_type, entity_id_from(body))}
    if action == "search":
        query = str(body.get("query") or "").strip()
        return 200, {"results": search_records(data_root, query, limit=int(body.get("limit") or 10))}
    if action == "list_recent":
        return 200, list_recent(data_root, limit=int(body.get("limit") or 20))
    if action == "list_deals":
        return 200, {"deals": list_deals(data_root, stage=str(body.get("stage") or "").strip(), limit=int(body.get("limit") or 50))}
    if action == "view_filter":
        return 200, {"state": load_view_state(data_root)}
    if action == "set_view_filter":
        return 200, set_view_filter_payload(
            data_root=data_root,
            query=body.get("query") if "query" in body else None,
            entity_type=body.get("entity_type") if "entity_type" in body else None,
            preserve_custom=bool(body.get("preserve_custom")),
        )
    if action == "set_custom_view":
        return 200, set_custom_view_payload(data_root=data_root, body=body)
    if action == "clear_custom_view":
        return 200, clear_custom_view_payload(data_root=data_root)
    if action == "references.manifest":
        return 200, REFERENCE_MANIFEST
    if action == "references.search":
        return 200, {"results": reference_search(data_root, str(body.get("query") or "").strip(), limit=int(body.get("limit") or 10))}
    if action == "references.resolve":
        return 200, reference_resolve(data_root, str(body.get("entity_type") or "").strip(), entity_id_from(body))
    if action == "references.summarize":
        return 200, reference_summarize(data_root, str(body.get("entity_type") or "").strip(), entity_id_from(body))
    if action == "health.check":
        return 200, health_payload(data_root)
    raise CrmValidationError(f"Unknown action `{action}`.")
