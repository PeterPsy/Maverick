"""Memory app service layer shared by backend, CLI, and MCP."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from errors import MemoryValidationError
from store import (
    add_external_ref,
    audit_events,
    clear_custom_view_payload,
    context_payload,
    create_edge,
    create_node,
    graph_payload,
    health_payload,
    inspect_node,
    load_view_state,
    search_nodes,
    set_custom_view_payload,
    set_view_filter_payload,
    soft_delete_edge,
    soft_delete_node,
    update_node,
)


REFERENCE_MANIFEST = {
    "app_id": "memory",
    "schema_version": "1",
    "entity_types": [
        {
            "entity_type": "node",
            "display_name": "Memory Node",
            "id_stability": "stable",
            "searchable": True,
            "resolvable": True,
            "summarizable": True,
            "deep_link_supported": True,
        }
    ],
}

DATA_CHANGED_RESOURCES = {
    "clear_custom_view",
    "remember",
    "create_node",
    "set_custom_view",
    "set_view_filter",
    "update_node",
    "delete_node",
    "soft_delete_node",
    "link",
    "link_nodes",
    "unlink",
    "unlink_nodes",
    "attach_file",
    "attach_entity",
    "attach_app_entity",
}
VIEW_STATE_ACTIONS = {"set_view_filter", "set_custom_view", "clear_custom_view"}


def app_events_for_action(action: str) -> list[dict[str, str]]:
    if action not in DATA_CHANGED_RESOURCES:
        return []
    resource = "view-state" if action in VIEW_STATE_ACTIONS else "graph"
    return [{"type": "maverick.app.data-changed", "resource": resource}]


def action_from_tool(tool_name: str, fallback: str) -> str:
    mapping = {
        "memory_context": "context",
        "memory_search": "search",
        "memory_remember": "remember",
        "memory_update_node": "update_node",
        "memory_soft_delete_node": "delete_node",
        "memory_link_nodes": "link",
        "memory_unlink_nodes": "unlink",
        "memory_attach_file": "attach_file",
        "memory_attach_app_entity": "attach_entity",
        "memory_inspect_node": "inspect",
        "memory_audit": "audit",
        "memory_view_filter": "view_filter",
        "memory_set_view_filter": "set_view_filter",
        "memory_set_custom_view": "set_custom_view",
        "memory_clear_custom_view": "clear_custom_view",
        "memory_reference_manifest": "references.manifest",
        "memory_reference_search": "references.search",
        "memory_reference_resolve": "references.resolve",
        "memory_reference_summarize": "references.summarize",
    }
    return mapping.get(tool_name, fallback)


def handle_action(data_root: Path, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    action = str(body.get("action") or "context").strip()
    if action in {"remember", "create_node"}:
        return 200, {"node": create_node(data_root, body)}
    if action == "update_node":
        return 200, {"node": update_node(data_root, body)}
    if action in {"delete_node", "soft_delete_node"}:
        return 200, soft_delete_node(data_root, body)
    if action in {"link", "link_nodes"}:
        return 200, {"edge": create_edge(data_root, body)}
    if action in {"unlink", "unlink_nodes"}:
        edge_id = str(body.get("edge_id") or body.get("id") or "").strip()
        if not edge_id:
            raise MemoryValidationError("edge_id is required.")
        return 200, soft_delete_edge(data_root, edge_id)
    if action == "attach_file":
        return 200, {"external_ref": add_external_ref(data_root, body, ref_kind="workspace_file")}
    if action in {"attach_entity", "attach_app_entity"}:
        return 200, {"external_ref": add_external_ref(data_root, body, ref_kind="app_entity")}
    if action == "inspect":
        node_id = str(body.get("node_id") or body.get("entity_id") or body.get("id") or "").strip()
        return 200, {"node": inspect_node(data_root, node_id)}
    if action == "search":
        query = str(body.get("query") or "").strip()
        return 200, {"results": search_nodes(data_root, query, limit=int(body.get("limit") or 10))}
    if action == "context":
        query = str(body.get("query") or "").strip()
        return 200, context_payload(data_root, query, limit=int(body.get("limit") or 8))
    if action == "graph":
        return 200, graph_payload(
            data_root,
            query=str(body.get("query") or "").strip(),
            node_ids=body.get("node_ids"),
            limit=int(body.get("limit") or 200),
        )
    if action == "audit":
        return 200, {"events": audit_events(data_root, limit=int(body.get("limit") or 50))}
    if action == "view_filter":
        return 200, {"state": load_view_state(data_root)}
    if action == "set_view_filter":
        return 200, set_view_filter_payload(
            data_root=data_root,
            query=body.get("query") if "query" in body else None,
            preserve_custom=bool(body.get("preserve_custom")),
        )
    if action == "set_custom_view":
        return 200, set_custom_view_payload(data_root=data_root, body=body)
    if action == "clear_custom_view":
        return 200, clear_custom_view_payload(data_root=data_root)
    if action == "health.check":
        return 200, health_payload(data_root)
    if action == "references.manifest":
        return 200, REFERENCE_MANIFEST
    if action == "references.search":
        query = str(body.get("query") or "").strip()
        results = []
        for node in search_nodes(data_root, query, limit=int(body.get("limit") or 10)):
            results.append(
                {
                    "app_id": "memory",
                    "entity_type": "node",
                    "entity_id": node["id"],
                    "title": node["title"],
                    "subtitle": node["type"],
                    "summary": node["summary"] or node["body_text"][:240],
                    "confidence": node["confidence"],
                    "deep_link": f"/apps/memory/nodes/{node['id']}",
                }
            )
        return 200, {"results": results}
    if action == "references.resolve":
        node_id = str(body.get("entity_id") or body.get("node_id") or "").strip()
        node = inspect_node(data_root, node_id)
        return 200, {
            "exists": node.get("status") != "deleted",
            "app_id": "memory",
            "entity_type": "node",
            "entity_id": node["id"],
            "title": node["title"],
            "subtitle": node["type"],
            "deep_link": f"/apps/memory/nodes/{node['id']}",
            "updated_at": node["updated_at"],
        }
    if action == "references.summarize":
        node_id = str(body.get("entity_id") or body.get("node_id") or "").strip()
        node = inspect_node(data_root, node_id)
        return 200, {
            "summary": node["summary"] or node["body_text"][:500],
            "safe_fields": {"type": node["type"], "title": node["title"]},
            "source_updated_at": node["updated_at"],
        }
    raise MemoryValidationError(f"Unknown action `{action}`.")
