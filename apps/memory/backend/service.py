"""Memory app service layer shared by backend, CLI, and MCP."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from database import normalize_limit
from errors import MemoryValidationError
from store import (
    add_external_ref,
    audit_events,
    cancel_job,
    claim_job,
    clear_custom_view_payload,
    complete_job,
    compile_node,
    context_payload,
    create_edge,
    create_node,
    enqueue_job,
    fetch_chunks,
    fail_job,
    graph_payload,
    health_payload,
    ingest_source,
    inspect_node,
    inspect_source,
    lint_memory,
    list_jobs,
    load_view_state,
    run_next_job,
    search_nodes,
    set_custom_view_payload,
    set_view_filter_payload,
    soft_delete_edge,
    soft_delete_node,
    source_query,
    update_node,
    wiki_query,
)
from storage_ingestion import ingest_storage_source
from storage_staleness import apply_storage_staleness


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
    "ingest_source",
    "ingest_storage_source",
    "apply_storage_staleness",
    "attach_entity",
    "attach_app_entity",
    "compile",
    "lint",
    "jobs_enqueue",
    "jobs_claim",
    "jobs_complete",
    "jobs_fail",
    "jobs_cancel",
    "jobs_run",
}
VIEW_STATE_ACTIONS = {"set_view_filter", "set_custom_view", "clear_custom_view"}
WIKI_ACTIONS = {"compile", "lint"}
GRAPH_AND_WIKI_ACTIONS = {"ingest_source", "ingest_storage_source", "jobs_run"}
MCP_TOOL_ACTIONS = {
    "memory_context": "context",
    "memory_search": "search",
    "memory_remember": "remember",
    "memory_update_node": "update_node",
    "memory_soft_delete_node": "delete_node",
    "memory_link_nodes": "link",
    "memory_unlink_nodes": "unlink",
    "memory_attach_file": "attach_file",
    "memory_ingest_source": "ingest_source",
    "memory_ingest_storage_source": "ingest_storage_source",
    "memory_apply_storage_staleness": "apply_storage_staleness",
    "memory_attach_app_entity": "attach_entity",
    "memory_inspect_node": "inspect",
    "memory_compile": "compile",
    "memory_lint": "lint",
    "memory_wiki_query": "wiki_query",
    "memory_source_query": "source_query",
    "memory_fetch_chunks": "fetch_chunks",
    "memory_inspect_source": "inspect_source",
    "memory_jobs": "jobs_list",
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


def app_events_for_action(action: str) -> list[dict[str, str]]:
    if action not in DATA_CHANGED_RESOURCES:
        return []
    if action == "apply_storage_staleness":
        return [
            {"type": "maverick.app.data-changed", "resource": "graph"},
            {"type": "maverick.app.data-changed", "resource": "wiki"},
        ]
    if action in GRAPH_AND_WIKI_ACTIONS:
        return [
            {"type": "maverick.app.data-changed", "resource": "graph"},
            {"type": "maverick.app.data-changed", "resource": "wiki"},
        ]
    if action in VIEW_STATE_ACTIONS:
        resource = "view-state"
    elif action in WIKI_ACTIONS:
        resource = "wiki"
    else:
        resource = "graph"
    return [{"type": "maverick.app.data-changed", "resource": resource}]


def action_from_tool(tool_name: str, fallback: str) -> str:
    return MCP_TOOL_ACTIONS.get(tool_name, fallback)


def reference_manifest_payload(app_id: str) -> dict[str, Any]:
    return {**REFERENCE_MANIFEST, "app_id": app_id}


def node_deep_link(app_id: str, node_id: str) -> str:
    return f"/app/{app_id}/nodes/{node_id}"


def handle_action(data_root: Path, body: dict[str, Any], *, app_id: str = "memory") -> tuple[int, dict[str, Any]]:
    try:
        return _handle_action(data_root, body, app_id=app_id)
    except sqlite3.IntegrityError as error:
        raise MemoryValidationError(sqlite_integrity_detail(error)) from error


def sqlite_integrity_detail(error: sqlite3.IntegrityError) -> str:
    message = str(error).lower()
    if "unique" in message:
        return "record already exists."
    if "foreign key" in message:
        return "referenced record was not found."
    if "not null" in message:
        return "required field is missing."
    return "database constraint failed."


def _handle_action(data_root: Path, body: dict[str, Any], *, app_id: str = "memory") -> tuple[int, dict[str, Any]]:
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
    if action == "ingest_source":
        return 200, ingest_source(data_root, body)
    if action == "ingest_storage_source":
        return 200, ingest_storage_source(data_root, body)
    if action == "apply_storage_staleness":
        return 200, apply_storage_staleness(data_root, body)
    if action in {"attach_entity", "attach_app_entity"}:
        return 200, {"external_ref": add_external_ref(data_root, body, ref_kind="app_entity")}
    if action == "inspect":
        node_id = str(body.get("node_id") or body.get("entity_id") or body.get("id") or "").strip()
        return 200, {"node": inspect_node(data_root, node_id)}
    if action == "search":
        query = str(body.get("query") or "").strip()
        limit = normalize_limit(body.get("limit"), default=10, minimum=1, maximum=50)
        return 200, {"results": search_nodes(data_root, query, limit=limit)}
    if action == "compile":
        return 200, compile_node(data_root, body)
    if action == "lint":
        return 200, lint_memory(data_root, body)
    if action == "wiki_query":
        query = str(body.get("query") or "").strip()
        limit = normalize_limit(body.get("limit"), default=10, minimum=1, maximum=50)
        return 200, wiki_query(data_root, query, limit=limit)
    if action == "source_query":
        query = str(body.get("query") or "").strip()
        limit = normalize_limit(body.get("limit"), default=10, minimum=1, maximum=50)
        return 200, source_query(data_root, query, limit=limit)
    if action == "fetch_chunks":
        return 200, fetch_chunks(
            data_root,
            body.get("chunk_ids"),
            limit=normalize_limit(body.get("limit"), default=20, minimum=1, maximum=20),
        )
    if action == "inspect_source":
        return 200, inspect_source(data_root, body)
    if action == "jobs_enqueue":
        return 200, {"job": enqueue_job(data_root, body)}
    if action == "jobs_claim":
        return 200, claim_job(data_root, body)
    if action == "jobs_complete":
        return 200, complete_job(data_root, body)
    if action == "jobs_fail":
        return 200, fail_job(data_root, body)
    if action == "jobs_cancel":
        return 200, cancel_job(data_root, body)
    if action == "jobs_run":
        return 200, run_next_job(data_root, body)
    if action == "jobs_list":
        operation = str(body.get("operation") or "list").strip()
        if operation == "enqueue":
            return 200, {"job": enqueue_job(data_root, body), "_event_action": "jobs_enqueue"}
        if operation == "claim":
            result = claim_job(data_root, body)
            result["_event_action"] = "jobs_claim"
            return 200, result
        if operation == "complete":
            result = complete_job(data_root, body)
            result["_event_action"] = "jobs_complete"
            return 200, result
        if operation == "fail":
            result = fail_job(data_root, body)
            result["_event_action"] = "jobs_fail"
            return 200, result
        if operation == "cancel":
            result = cancel_job(data_root, body)
            result["_event_action"] = "jobs_cancel"
            return 200, result
        if operation in {"run", "run_next"}:
            result = run_next_job(data_root, body)
            result["_event_action"] = "jobs_run" if result.get("ran") else "jobs_list"
            return 200, result
        if operation != "list":
            raise MemoryValidationError("unsupported jobs operation.")
        return 200, list_jobs(data_root, body)
    if action == "context":
        query = str(body.get("query") or "").strip()
        return 200, context_payload(
            data_root,
            query,
            limit=normalize_limit(body.get("limit"), default=8, minimum=1, maximum=50),
            record_access_event=bool(body.get("record_access_event")),
        )
    if action == "graph":
        return 200, graph_payload(
            data_root,
            query=str(body.get("query") or "").strip(),
            node_ids=body.get("node_ids"),
            limit=normalize_limit(body.get("limit"), default=200, minimum=1, maximum=500),
        )
    if action == "audit":
        limit = normalize_limit(body.get("limit"), default=50, minimum=1, maximum=200)
        return 200, {"events": audit_events(data_root, limit=limit)}
    if action == "view_filter":
        return 200, {"state": load_view_state(data_root)}
    if action == "set_view_filter":
        return 200, set_view_filter_payload(
            data_root=data_root,
            query=body.get("query") if "query" in body else None,
            preserve_custom=bool(body.get("preserve_custom")),
        )
    if action == "set_custom_view":
        return 200, set_custom_view_payload(data_root=data_root, body=body, app_id=app_id)
    if action == "clear_custom_view":
        return 200, clear_custom_view_payload(data_root=data_root)
    if action == "health.check":
        return 200, health_payload(data_root)
    if action == "references.manifest":
        return 200, reference_manifest_payload(app_id)
    if action == "references.search":
        query = str(body.get("query") or "").strip()
        results = []
        limit = normalize_limit(body.get("limit"), default=10, minimum=1, maximum=50)
        for node in search_nodes(data_root, query, limit=limit):
            results.append(
                {
                    "app_id": app_id,
                    "entity_type": "node",
                    "entity_id": node["id"],
                    "title": node["title"],
                    "subtitle": node["type"],
                    "summary": node["summary"] or node["body_text"][:240],
                    "confidence": node["confidence"],
                    "deep_link": node_deep_link(app_id, node["id"]),
                }
            )
        return 200, {"results": results}
    if action == "references.resolve":
        node_id = str(body.get("entity_id") or body.get("node_id") or "").strip()
        node = inspect_node(data_root, node_id)
        return 200, {
            "exists": node.get("status") != "deleted",
            "app_id": app_id,
            "entity_type": "node",
            "entity_id": node["id"],
            "title": node["title"],
            "subtitle": node["type"],
            "deep_link": node_deep_link(app_id, node["id"]),
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
