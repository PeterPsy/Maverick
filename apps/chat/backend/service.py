"""Chat app service layer shared by backend, MCP, and CLI."""

from __future__ import annotations

from pathlib import Path

from chat_state import (
    clear_custom_view,
    create_project,
    delete_project,
    list_projects,
    mutate_state,
    project_exists,
    read_state,
    set_custom_view,
    set_view_filter,
    state_path,
    update_project,
)
from errors import ChatValidationError
from references import REFERENCE_MANIFEST, reference_resolve, reference_search, reference_summarize
from surface_manifest import OPERATIONS_MANIFEST

DATA_CHANGED_ACTIONS = {
    "projects.create",
    "projects.update",
    "projects.delete",
}
VIEW_STATE_ACTIONS = {
    "set_view_filter",
    "set_custom_view",
    "clear_custom_view",
}


def app_events_for_action(action: str) -> list[dict]:
    if action in DATA_CHANGED_ACTIONS:
        return [{"type": "maverick.app.data-changed", "resource": "projects"}]
    if action in VIEW_STATE_ACTIONS:
        return [{"type": "maverick.app.data-changed", "resource": "view-state"}]
    return []


def app_events_for_result(action: str, result: dict) -> list[dict]:
    if result.get("runtime_cleanup_requests"):
        return []
    return app_events_for_action(action)


def validation_error_payload(error: ChatValidationError, operation: str) -> dict:
    payload = {
        "error": "validation_error",
        "operation": operation,
        "detail": str(error),
    }
    if error.expected_fields:
        payload["expected_fields"] = error.expected_fields
    if error.accepted_aliases:
        payload["accepted_aliases"] = error.accepted_aliases
    if error.allowed_values:
        payload["allowed_values"] = error.allowed_values
    if error.example:
        payload["example"] = error.example
    return payload


def unsupported_action_payload(action: str, *, allowed_actions: list[str] | None = None) -> dict:
    return {
        "error": "unsupported_action",
        "action": action,
        "detail": f"Unsupported Chat operation: {action or '<empty>'}.",
        "allowed_values": {
            "action": allowed_actions
            if allowed_actions is not None
            else sorted(OPERATIONS_MANIFEST["operations"]) + ["operations.manifest", "health.check"]
        },
        "example": {"action": "operations.manifest"},
    }


def handle_action(data_root: Path, body: dict, *, invocation_surface: str = "") -> tuple[int, dict]:
    action = str(body.get("action") or "operations.manifest").strip()
    path = state_path(data_root)

    if action == "operations.manifest":
        return 200, OPERATIONS_MANIFEST
    if action == "health.check":
        path.parent.mkdir(parents=True, exist_ok=True)
        return 200, {"status": "ok", "data_root": str(data_root)}

    if action == "projects.list":
        state = read_state(path)
        return 200, _project_catalog_payload(state)
    if action == "projects.create":
        state, result = mutate_state(path, lambda current: {"project": create_project(current, body)})
        return 201, {"project": result["project"], **_project_catalog_payload(state)}
    if action == "projects.update":
        state, result = mutate_state(path, lambda current: {"project": update_project(current, body)})
        project = result["project"]
        if project is None:
            return 404, {"error": "project_not_found", "project_id": str(body.get("project_id") or "")}
        return 200, {"project": project, **_project_catalog_payload(state)}
    if action == "projects.delete":
        return _prepare_project_delete(path, body)
    if action == "projects.delete.commit":
        return _commit_project_delete(path, body, invocation_surface=invocation_surface)
    if action == "runtime.cleanup_sessions":
        runtime_session_ids = body.get("runtime_session_ids") if isinstance(body.get("runtime_session_ids"), list) else []
        return 200, {"cleaned_runtime_session_ids": [str(item) for item in runtime_session_ids if str(item).strip()]}

    if action == "references.manifest":
        return 200, REFERENCE_MANIFEST
    if action == "references.search":
        state = read_state(path)
        return 200, reference_search(state, body)
    if action == "references.resolve":
        state = read_state(path)
        return 200, reference_resolve(state, body)
    if action == "references.summarize":
        state = read_state(path)
        return 200, reference_summarize(state, body)

    if action == "view_filter":
        state = read_state(path)
        return 200, {"state": {"view_filter": state.get("preferences", {}).get("view_filter")}}
    if action == "set_view_filter":
        state, result = mutate_state(path, lambda current: {"view_filter": set_view_filter(current, body)})
        return 200, {"state": {"view_filter": result["view_filter"]}}
    if action == "set_custom_view":
        _require_custom_view_refs(body)
        state, result = mutate_state(path, lambda current: {"view_filter": set_custom_view(current, body)})
        return 200, {"state": {"view_filter": result["view_filter"]}}
    if action == "clear_custom_view":
        state, result = mutate_state(path, lambda current: {"view_filter": clear_custom_view(current)})
        return 200, {"state": {"view_filter": result["view_filter"]}}

    return 400, unsupported_action_payload(action)


def _project_catalog_payload(state: dict) -> dict:
    return {
        "projects": list_projects(state),
        "preferences": state.get("preferences", {}),
        "payload_profile": "compact",
    }


def _prepare_project_delete(path: Path, body: dict) -> tuple[int, dict]:
    state = read_state(path)
    project_id = str(body.get("project_id") or "").strip()
    if not project_exists(state, project_id):
        return 404, {"error": "project_not_found", "project_id": project_id}
    return 200, {
        "project_id": project_id,
        "runtime_cleanup_requests": [
            {
                "project_id": project_id,
                "reason": "chat_project_deleted",
            }
        ],
        "runtime_cleanup_commit": {
            "action": "projects.delete.commit",
            "payload": {"project_id": project_id},
        },
    }


def _commit_project_delete(path: Path, body: dict, *, invocation_surface: str) -> tuple[int, dict]:
    if invocation_surface != "runtime_cleanup_commit":
        return 403, {"error": "project_delete_commit_forbidden"}
    state, result = mutate_state(path, lambda current: {"deleted": delete_project(current, body)})
    if not result["deleted"]:
        return 404, {"error": "project_not_found", "project_id": str(body.get("project_id") or "")}
    return 200, _project_catalog_payload(state)


def _require_custom_view_refs(body: dict) -> None:
    refs = body.get("refs")
    if not isinstance(refs, list):
        raise ChatValidationError(
            "Missing required field: refs.",
            expected_fields=["refs"],
            example={
                "action": "set_custom_view",
                "title": "Focused chats",
                "refs": [{"entity_type": "project", "entity_id": "project-uuid"}],
            },
        )
    for index, item in enumerate(refs):
        if not isinstance(item, dict):
            raise _invalid_ref_error(index)
        unexpected_fields = sorted(set(item) - {"entity_type", "entity_id"})
        if unexpected_fields:
            raise ChatValidationError(
                f"Unexpected field(s) in refs[{index}]: {', '.join(unexpected_fields)}.",
                expected_fields=[f"refs[{index}].entity_type", f"refs[{index}].entity_id"],
                allowed_values={"refs[].fields": ["entity_type", "entity_id"]},
                example={
                    "action": "set_custom_view",
                    "title": "Focused chats",
                    "refs": [{"entity_type": "project", "entity_id": "project-uuid"}],
                },
            )
        entity_type = str(item.get("entity_type") or "").strip()
        entity_id = str(item.get("entity_id") or "").strip()
        if entity_type not in {"project", "thread"} or not entity_id:
            raise _invalid_ref_error(index)


def _invalid_ref_error(index: int) -> ChatValidationError:
    return ChatValidationError(
        f"Invalid refs[{index}]: each ref requires entity_type and entity_id.",
        expected_fields=[f"refs[{index}].entity_type", f"refs[{index}].entity_id"],
        allowed_values={"refs[].entity_type": ["project", "thread"]},
        example={
            "action": "set_custom_view",
            "title": "Focused chats",
            "refs": [{"entity_type": "project", "entity_id": "project-uuid"}],
        },
    )
