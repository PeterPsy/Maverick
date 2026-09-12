"""Application service dispatch for every official surface."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from activity_store import add_activity, list_activities
from candidate_queries import candidate_stats, list_candidates
from candidate_store import bulk_update_candidates, create_candidate, delete_candidate, read_candidate, update_candidate
from import_export import export_catalog, import_candidates
from references import REFERENCE_MANIFEST, resolve_reference, search_references, summarize_reference
from schema import SCHEMA_VERSION, connect, database_path
from surface_contract import operations_manifest
from view_state import DEFAULT_VIEW, read_view_state, write_view_state

CANDIDATE_MUTATIONS = {"create", "update", "bulk_update", "delete", "activity.add", "import"}
VIEW_MUTATIONS = {"set_view_filter", "set_custom_view", "clear_custom_view"}
MCP_ACTIONS = {
    "videomaker_selection_candidate_list": "list", "videomaker_selection_candidate_read": "read",
    "videomaker_selection_candidate_update": "update", "videomaker_selection_candidate_stats": "stats",
    "videomaker_selection_reference_manifest": "references.manifest", "videomaker_selection_reference_search": "references.search",
    "videomaker_selection_reference_resolve": "references.resolve", "videomaker_selection_reference_summarize": "references.summarize",
    "videomaker_selection_view_filter": "view_filter", "videomaker_selection_set_view_filter": "set_view_filter",
    "videomaker_selection_set_custom_view": "set_custom_view", "videomaker_selection_clear_custom_view": "clear_custom_view",
}


def handle_action(data_root: Path, body: dict[str, Any], *, workspace_id: str) -> tuple[int, dict[str, Any]]:
    action = str(body.get("action") or "operations.manifest").strip().lower()
    try:
        with connect(data_root) as connection:
            if action in {"operations.manifest", "manifest", "help"}:
                return 200, operations_manifest()
            if action in {"status", "describe", "health.check"}:
                return 200, {"status": "ok", "schema_version": SCHEMA_VERSION, "database": database_path(data_root).name, "stats": candidate_stats(connection)}
            if action == "stats":
                return 200, {"stats": candidate_stats(connection)}
            if action == "list":
                options = dict(body)
                if bool(body.get("apply_view_state")):
                    view = read_view_state(connection)
                    options.setdefault("query", view.get("query"))
                    options.setdefault("decision", view.get("decision"))
                    options.setdefault("email_status", view.get("email_status"))
                    if view.get("mode") == "custom":
                        options["ids"] = [ref["entity_id"] for ref in view.get("refs", [])]
                items, pagination = list_candidates(connection, options)
                return 200, {"items": items, "pagination": pagination}
            if action in {"read", "get", "recall"}:
                return 200, {"candidate": read_candidate(connection, required_id(body))}
            if action == "create":
                return 201, {"candidate": create_candidate(connection, payload(body))}
            if action == "update":
                return 200, {"candidate": update_candidate(connection, required_id(body), payload(body))}
            if action == "bulk_update":
                return 200, {"candidates": bulk_update_candidates(connection, list(body.get("ids") or []), payload(body))}
            if action == "delete":
                return 200, delete_candidate(connection, required_id(body), confirmed=bool(body.get("confirm")))
            if action == "activity.list":
                return 200, {"activities": list_activities(connection, required_id(body), limit=int(body.get("limit") or 100))}
            if action == "activity.add":
                candidate_id = required_id(body)
                read_candidate(connection, candidate_id, include_activities=False)
                activity = add_activity(connection, candidate_id, kind=str(body.get("kind") or "note"), summary=str(body.get("summary") or ""), details=body.get("details") if isinstance(body.get("details"), dict) else None, occurred_at=str(body.get("occurred_at") or "") or None)
                return 201, {"activity": activity, "candidate": read_candidate(connection, candidate_id)}
            if action == "import":
                return 200, {"import": import_candidates(connection, body.get("candidates"))}
            if action == "export":
                return 200, {"export": export_catalog(connection)}
            if action == "references.manifest":
                return 200, REFERENCE_MANIFEST
            if action == "references.search":
                return 200, search_references(connection, str(body.get("query") or ""), int(body.get("limit") or 10))
            if action == "references.resolve":
                return 200, resolve_reference(connection, reference_id(body))
            if action == "references.summarize":
                return 200, summarize_reference(connection, reference_id(body))
            if action == "view_filter":
                return 200, {"view_state": read_view_state(connection)}
            if action == "set_view_filter":
                current = read_view_state(connection)
                return 200, {"view_state": write_view_state(connection, {**current, "mode": "search", "query": body.get("query", current["query"]), "decision": body.get("decision", current["decision"]), "email_status": body.get("email_status", current["email_status"]), "title": "", "refs": []})}
            if action == "set_custom_view":
                return 200, {"view_state": write_view_state(connection, {"mode": "custom", "title": body.get("title") or "Candidate selection", "query": body.get("query") or "", "decision": body.get("decision") or "all", "email_status": body.get("email_status") or "all", "refs": body.get("refs") or []})}
            if action == "clear_custom_view":
                return 200, {"view_state": write_view_state(connection, DEFAULT_VIEW)}
    except sqlite3.IntegrityError as error:
        return 409, {"error": "conflict", "detail": str(error)}
    except ValueError as error:
        return (404 if "not found" in str(error).lower() else 400), {"error": "validation_error", "detail": str(error)}
    return 400, {"error": "unsupported_action", "detail": f"Unsupported action: {action}"}


def payload(body: dict[str, Any]) -> dict[str, Any]:
    return dict(body.get("payload")) if isinstance(body.get("payload"), dict) else {key: value for key, value in body.items() if key not in {"action", "id", "candidate_id"}}


def required_id(body: dict[str, Any]) -> str:
    candidate_id = str(body.get("id") or body.get("candidate_id") or "").strip()
    if not candidate_id: raise ValueError("Candidate id is required.")
    return candidate_id


def reference_id(body: dict[str, Any]) -> str:
    if str(body.get("entity_type") or "candidate") != "candidate": raise ValueError("Unsupported reference entity type.")
    return required_id({"id": body.get("entity_id") or body.get("id")})


def app_events_for_action(action: str) -> list[dict[str, str]]:
    if action in CANDIDATE_MUTATIONS:
        return [{"type": "maverick.app.data-changed", "owner_app_id": "videomaker-selection", "resource": "candidates"}]
    if action in VIEW_MUTATIONS:
        return [{"type": "maverick.app.data-changed", "owner_app_id": "videomaker-selection", "resource": "view-state"}]
    return []


def mcp_result_for_tool(data_root: Path, tool_name: str, arguments: dict[str, Any], *, workspace_id: str) -> tuple[int, dict[str, Any]]:
    body = {**arguments, "action": mcp_action_for_tool(tool_name, arguments)}
    return handle_action(data_root, body, workspace_id=workspace_id)


def mcp_action_for_tool(tool_name: str, arguments: dict[str, Any]) -> str:
    return MCP_ACTIONS.get(tool_name, str(arguments.get("action") or "operations.manifest"))
