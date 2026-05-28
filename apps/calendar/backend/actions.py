"""Calendar backend action and MCP dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from availability import check_availability, conflicts_for_event, find_free_time
from constants import AGENT_DEFAULT_LIST_LIMIT, MUTATING_ACTIONS, SCHEMA_VERSION, VIEW_STATE_ACTIONS
from errors import CalendarConflictError, CalendarRevisionConflictError
from event_records import filter_events
from google_oauth import (
    CalendarOAuthError,
    complete_oauth,
    disconnect_connection,
    list_connections,
    provider_status,
    start_oauth,
)
from google_mutations import (
    REMOTE_MUTATION_FLAG,
    attach_google_event,
    create_google_event,
    delete_google_event_local_first_validated,
    is_google_create_request,
    is_google_event,
    move_google_event,
    update_google_event,
)
from google_calendars import list_calendars, select_calendar
from google_sync import sync_google_calendar
from scalars import optional_bool, optional_int
from operations import create_event, delete_event, get_event, list_events, move_event, update_event
from references import reference_resolve, reference_search, reference_summarize
from request_inputs import (
    conflict_policy_from_body,
    event_payload,
    expected_revision,
    filter_kwargs,
    reference_id,
    required_string,
)
from surface_contract import (
    conflict_error,
    normalize_action,
    not_found_error,
    operations_manifest,
    revision_conflict_error,
    reference_manifest,
    unsupported_action,
    validation_error,
)
from view_state import clear_custom_view, read_view_filter, set_custom_view, set_view_filter
from store import read_state


def handle_action(
    data_root: Path,
    body: dict[str, Any],
    *,
    app_id: str = "calendar",
    workspace_id: str | None = None,
    app_secrets: dict[str, str] | None = None,
    app_secret_errors: list[dict[str, Any]] | None = None,
    allow_platform_secret_writes: bool = False,
    oauth_transport=None,
    oauth_now=None,
) -> tuple[int, dict[str, Any]]:
    """Dispatch backend, CLI, and MCP actions."""
    action = normalize_action(body.get("action") or "list")
    try:
        if action == "operations.manifest":
            return 200, operations_manifest(app_id)
        if action in {"status", "describe"}:
            return 200, describe(data_root, app_id=app_id)
        if action in {"provider_status", "calendar_connections.provider_status"}:
            return 200, provider_status(data_root, app_secrets=app_secrets, app_secret_errors=app_secret_errors)
        if action == "calendar_connections.list":
            return 200, list_connections(data_root)
        if action == "calendar_calendars.list":
            return 200, list_calendars(data_root, body)
        if action == "calendar_calendars.select":
            return 200, select_calendar(data_root, body, now=oauth_now)
        if action == "calendar_connections.start_oauth":
            return 200, start_oauth(
                data_root,
                body,
                app_id=app_id,
                app_secrets=app_secrets,
                app_secret_errors=app_secret_errors,
                now=oauth_now,
            )
        if action == "calendar_connections.complete_oauth":
            return 200, complete_oauth(
                data_root,
                body,
                app_id=app_id,
                app_secrets=app_secrets,
                app_secret_errors=app_secret_errors,
                allow_platform_secret_writes=allow_platform_secret_writes,
                transport=oauth_transport,
                now=oauth_now,
            )
        if action == "calendar_connections.disconnect":
            return 200, disconnect_connection(
                data_root,
                body,
                app_secrets=app_secrets,
                app_secret_errors=app_secret_errors,
                transport=oauth_transport,
                now=oauth_now,
            )
        if action == "calendar_sync":
            return 200, sync_google_calendar(
                data_root,
                body,
                app_secrets=app_secrets,
                app_secret_errors=app_secret_errors,
                transport=oauth_transport,
                now=oauth_now,
            )
        if action == "list":
            return 200, list_payload(data_root, body)
        if action == "create":
            selected_conflict_policy = conflict_policy_from_body(body)
            payload = event_payload(body)
            remote_mutation = is_google_create_request(payload)
            if remote_mutation:
                event, idempotent_replay = create_google_event(
                    data_root,
                    payload,
                    conflict_policy=selected_conflict_policy,
                    app_secrets=app_secrets,
                    app_secret_errors=app_secret_errors,
                    transport=oauth_transport,
                )
            else:
                event, idempotent_replay = create_event(data_root, payload, conflict_policy=selected_conflict_policy)
            return 200 if idempotent_replay else 201, _mutation_payload(
                "create",
                event,
                data_root,
                conflict_policy=selected_conflict_policy,
                idempotent_replay=idempotent_replay,
                remote_mutation=remote_mutation and not idempotent_replay,
            )
        if action == "update":
            event_id = required_string(body, "id")
            selected_conflict_policy = conflict_policy_from_body(body)
            current_event = get_event(data_root, event_id)
            payload = event_payload(body)
            remote_mutation = bool(current_event and (is_google_event(current_event) or is_google_create_request(payload)))
            if remote_mutation:
                if current_event and is_google_event(current_event):
                    event = update_google_event(
                        data_root,
                        event_id,
                        payload,
                        conflict_policy=selected_conflict_policy,
                        expected_revision=expected_revision(body),
                        app_secrets=app_secrets,
                        app_secret_errors=app_secret_errors,
                        transport=oauth_transport,
                    )
                else:
                    event = attach_google_event(
                        data_root,
                        event_id,
                        payload,
                        conflict_policy=selected_conflict_policy,
                        expected_revision=expected_revision(body),
                        app_secrets=app_secrets,
                        app_secret_errors=app_secret_errors,
                        transport=oauth_transport,
                    )
            else:
                event = update_event(
                    data_root,
                    event_id,
                    payload,
                    conflict_policy=selected_conflict_policy,
                    expected_revision=expected_revision(body),
                )
            return 200, _mutation_payload("update", event, data_root, conflict_policy=selected_conflict_policy, remote_mutation=remote_mutation)
        if action == "delete":
            event_id = required_string(body, "id")
            current_event = get_event(data_root, event_id)
            remote_mutation = bool(current_event and is_google_event(current_event))
            if remote_mutation:
                delete_google_event_local_first_validated(
                    data_root,
                    event_id,
                    expected_revision=expected_revision(body),
                    app_secrets=app_secrets,
                    app_secret_errors=app_secret_errors,
                    transport=oauth_transport,
                )
            else:
                delete_event(data_root, event_id, expected_revision=expected_revision(body))
            result = {"action": "delete", "deleted": True, "id": event_id}
            if remote_mutation:
                result[REMOTE_MUTATION_FLAG] = True
            return 200, result
        if action == "move":
            event_id = required_string(body, "id")
            selected_conflict_policy = conflict_policy_from_body(body)
            current_event = get_event(data_root, event_id)
            remote_mutation = bool(current_event and is_google_event(current_event))
            if remote_mutation:
                event = move_google_event(
                    data_root,
                    event_id,
                    body,
                    conflict_policy=selected_conflict_policy,
                    expected_revision=expected_revision(body),
                    app_secrets=app_secrets,
                    app_secret_errors=app_secret_errors,
                    transport=oauth_transport,
                )
            else:
                event = move_event(
                    data_root,
                    event_id,
                    body,
                    conflict_policy=selected_conflict_policy,
                    expected_revision=expected_revision(body),
                )
            return 200, _mutation_payload("move", event, data_root, conflict_policy=selected_conflict_policy, remote_mutation=remote_mutation)
        if action == "check_availability":
            return 200, check_availability(data_root, body)
        if action == "find_free_time":
            return 200, find_free_time(data_root, body)
        if action == "view_filter":
            return 200, {"action": "view_filter", "view_state": read_view_filter(data_root)}
        if action == "set_view_filter":
            return 200, {"action": "set_view_filter", "view_state": set_view_filter(data_root, body)}
        if action == "set_custom_view":
            return 200, {"action": "set_custom_view", "view_state": set_custom_view(data_root, body, app_id=app_id)}
        if action == "clear_custom_view":
            return 200, {"action": "clear_custom_view", "view_state": clear_custom_view(data_root)}
        if action == "references.manifest":
            return 200, reference_manifest(app_id)
        if action == "references.search":
            return 200, reference_search(
                data_root,
                app_id=app_id,
                entity_type=str(body.get("entity_type") or "event"),
                query=str(body.get("query") or ""),
                limit=optional_int(body.get("limit"), field="limit", minimum=1, maximum=50) or 20,
            )
        if action == "references.resolve":
            return 200, reference_resolve(data_root, reference_id(body), app_id=app_id)
        if action == "references.summarize":
            return 200, reference_summarize(data_root, reference_id(body), app_id=app_id)
    except CalendarRevisionConflictError as error:
        return 409, revision_conflict_error(
            action,
            str(error),
            event_id=error.event_id,
            expected_revision=error.expected_revision,
            actual_revision=error.actual_revision,
            current_event=error.current_event,
        )
    except CalendarConflictError as error:
        return 409, conflict_error(action, str(error), error.conflicts)
    except CalendarOAuthError as error:
        result = {"action": action, "error": error.code, "detail": error.detail}
        result.update(error.extra)
        return error.status_code, result
    except ValueError as error:
        detail = str(error)
        if " was not found." in detail:
            return 404, not_found_error(action, detail)
        return 400, validation_error(action, detail)
    return 400, unsupported_action(action)


def list_payload(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    total = len(filter_events(list_events(data_root), **filter_kwargs(body)))
    offset = optional_int(body.get("offset"), field="offset", minimum=0) or 0
    limit = optional_int(body.get("limit"), field="limit", minimum=1, maximum=500)
    profile = str(body.get("profile") or "full").strip().lower()
    if profile not in {"compact", "full"}:
        raise ValueError("`profile` must be `compact` or `full`.")
    include_description = optional_bool(body.get("include_description"), default=profile == "full")
    events = list_events(
        data_root,
        limit=limit,
        offset=offset,
        include_description=include_description,
        profile=profile,
        **filter_kwargs(body),
    )
    return {
        "action": "list",
        "events": events,
        "content_profile": profile,
        "pagination": {
            "offset": offset,
            "limit": limit,
            "total": total,
            "has_more": bool(limit and offset + limit < total),
        },
    }


def app_events_for_action(action: str, *, app_id: str = "calendar") -> list[dict[str, str]]:
    normalized = normalize_action(action)
    if normalized in MUTATING_ACTIONS:
        return [{"type": "maverick.app.data-changed", "owner_app_id": app_id, "resource": "events"}]
    if normalized == "calendar_sync":
        return [
            {"type": "maverick.app.data-changed", "owner_app_id": app_id, "resource": "events"},
            {"type": "maverick.app.data-changed", "owner_app_id": app_id, "resource": "calendars"},
            {"type": "maverick.app.data-changed", "owner_app_id": app_id, "resource": "connections"},
        ]
    if normalized == "calendar_calendars.select":
        return [
            {"type": "maverick.app.data-changed", "owner_app_id": app_id, "resource": "calendars"},
            {"type": "maverick.app.data-changed", "owner_app_id": app_id, "resource": "events"},
        ]
    if normalized in {"calendar_connections.start_oauth", "calendar_connections.complete_oauth", "calendar_connections.disconnect"}:
        return [{"type": "maverick.app.data-changed", "owner_app_id": app_id, "resource": "connections"}]
    if normalized in VIEW_STATE_ACTIONS:
        return [{"type": "maverick.app.data-changed", "owner_app_id": app_id, "resource": "view-state"}]
    return []


def health_payload(data_root: Path) -> dict[str, Any]:
    state = read_state(data_root)
    events = list_events(data_root)
    return {
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "event_count": len(events),
        "connection_count": len(state.get("connections", [])),
        "calendar_count": len(state.get("calendars", [])),
        "sync_cursor_count": len(state.get("sync_state", [])),
    }


def describe(data_root: Path, *, app_id: str = "calendar") -> dict[str, Any]:
    events = list_events(data_root, limit=1)
    return {
        "action": "describe",
        "app_id": app_id,
        "status": "ready",
        "schema_version": SCHEMA_VERSION,
        "event_count": len(list_events(data_root)),
        "latest": events[0] if events else None,
        "reference_manifest": reference_manifest(app_id),
        "view_state": read_view_filter(data_root),
        "operations": operations_manifest(app_id)["operations"],
    }


def mcp_result_for_tool(
    data_root: Path,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    app_id: str = "calendar",
    workspace_id: str | None = None,
    app_secrets: dict[str, str] | None = None,
    app_secret_errors: list[dict[str, Any]] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Map MCP tools to Calendar app actions."""
    if tool_name == "calendar_operations_manifest":
        return 200, operations_manifest(app_id)
    action_by_tool = {
        "calendar_list_events": "list",
        "calendar_create_event": "create",
        "calendar_update_event": "update",
        "calendar_delete_event": "delete",
        "calendar_move_event": "move",
        "calendar_check_availability": "check_availability",
        "calendar_find_free_time": "find_free_time",
        "calendar_view_filter": "view_filter",
        "calendar_set_view_filter": "set_view_filter",
        "calendar_set_custom_view": "set_custom_view",
        "calendar_clear_custom_view": "clear_custom_view",
        "calendar_reference_manifest": "references.manifest",
        "calendar_reference_search": "references.search",
        "calendar_reference_resolve": "references.resolve",
        "calendar_reference_summarize": "references.summarize",
        "calendar_connections.list": "calendar_connections.list",
        "calendar_calendars.list": "calendar_calendars.list",
        "calendar_calendars.select": "calendar_calendars.select",
        "calendar_connections.start_oauth": "calendar_connections.start_oauth",
        "calendar_connections.disconnect": "calendar_connections.disconnect",
        "calendar_sync": "calendar_sync",
    }
    if tool_name not in action_by_tool:
        return 404, {
            "error": "unsupported_tool",
            "detail": f"Unsupported Calendar MCP tool `{tool_name}`.",
            "allowed_values": ["calendar_operations_manifest", *sorted(action_by_tool)],
        }
    arguments.setdefault("action", action_by_tool[tool_name])
    if tool_name == "calendar_list_events":
        arguments.setdefault("profile", "compact")
        arguments.setdefault("include_description", False)
        arguments.setdefault("limit", AGENT_DEFAULT_LIST_LIMIT)
    return handle_action(
        data_root,
        arguments,
        app_id=app_id,
        workspace_id=workspace_id,
        app_secrets=app_secrets,
        app_secret_errors=app_secret_errors,
    )


def _mutation_payload(
    action: str,
    event: dict[str, Any],
    data_root: Path,
    *,
    conflict_policy: str,
    idempotent_replay: bool = False,
    remote_mutation: bool = False,
) -> dict[str, Any]:
    conflicts = conflicts_for_event(list_events(data_root), event, ignore_event_id=event["id"])
    result: dict[str, Any] = {
        "action": action,
        "event": event,
        "conflict_policy": conflict_policy,
        "idempotent_replay": idempotent_replay,
        "availability": {
            "status": "free" if not conflicts else "conflicting",
            "conflict_count": len(conflicts),
        },
    }
    if remote_mutation:
        result[REMOTE_MUTATION_FLAG] = True
    if conflicts:
        result["conflicts"] = conflicts
    if conflict_policy == "warn" and conflicts:
        result["warnings"] = [
            {
                "type": "calendar_conflict",
                "detail": f"Calendar event overlaps {len(conflicts)} existing event(s).",
                "conflicts": conflicts,
            }
        ]
    return result
