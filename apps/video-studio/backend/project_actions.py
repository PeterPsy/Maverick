"""Transport-neutral project and revision action router."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
import sqlite3
from typing import Any

from foundation.database import FoundationDatabaseError
from foundation.service import FOUNDATION_ACTIONS
from projects import ProjectError, ProjectService

from service import handle_foundation_action


PROJECT_ACTIONS = (
    "project.create",
    "project.list",
    "project.get",
    "project.rename",
    "project.duplicate",
    "project.archive",
    "project.restore",
    "revision.get",
    "revision.compare",
    "native.export",
    "native.import",
    "operations.apply",
    "history.undo",
    "history.redo",
)
ALL_ACTIONS = (*FOUNDATION_ACTIONS, *PROJECT_ACTIONS)
MUTATING_ACTIONS = {
    "project.create",
    "project.rename",
    "project.duplicate",
    "project.archive",
    "project.restore",
    "native.import",
    "operations.apply",
    "history.undo",
    "history.redo",
}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ACTION_FIELDS = {
    "project.create": {"action", "name", "project_id", "description", "project_ir"},
    "project.list": {"action", "include_archived"},
    "project.get": {"action", "project_id"},
    "project.rename": {"action", "project_id", "name", "base_revision_id", "operation_batch_id"},
    "project.duplicate": {"action", "project_id", "new_project_id", "name"},
    "project.archive": {"action", "project_id"},
    "project.restore": {"action", "project_id"},
    "revision.get": {"action", "project_id", "revision_id"},
    "revision.compare": {"action", "project_id", "before_revision_id", "after_revision_id"},
    "native.export": {"action", "project_id", "revision_id"},
    "native.import": {"action", "native_project", "project_id", "name"},
    "operations.apply": {"action", "batch"},
    "history.undo": {"action", "batch"},
    "history.redo": {"action", "batch"},
}


def handle_action(
    data_root: str | Path,
    workspace_id: object,
    request: object,
    *,
    trusted_actor: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    if not isinstance(request, dict):
        return _error(ProjectError("request_invalid", "Action request must be an object."))
    action = str(request.get("action") or "status").strip().lower()
    if action in FOUNDATION_ACTIONS:
        return handle_foundation_action(data_root, action)
    if action not in PROJECT_ACTIONS:
        return _error(ProjectError("unsupported_action", "Unsupported Video Studio action."))
    try:
        unknown = sorted(set(request) - _ACTION_FIELDS[action])
        if unknown:
            raise ProjectError(
                "request_shape_invalid",
                "Action request contains undeclared fields.",
                details={"unknown": unknown},
            )
        application = ProjectService(data_root, workspace_id=workspace_id)  # type: ignore[arg-type]
        result = _dispatch(
            application,
            action,
            request,
            trusted_actor or {"kind": "system", "id": "video-studio"},
        )
    except ProjectError as error:
        return _error(error)
    except FoundationDatabaseError:
        return 503, {
            "ok": False,
            "error": {
                "code": "project_store_unavailable",
                "path": "",
                "message": "Video Studio project storage is unavailable.",
                "details": {},
            },
        }
    except sqlite3.Error:
        return 503, {
            "ok": False,
            "error": {
                "code": "project_store_failure",
                "path": "",
                "message": "Video Studio project storage operation failed.",
                "details": {},
            },
        }
    return 200, {"ok": True, "action": action, **result}


def _dispatch(
    application: ProjectService,
    action: str,
    request: dict[str, Any],
    actor: dict[str, str],
) -> dict[str, Any]:
    if action == "project.create":
        return {"project": application.create_project(
            name=request.get("name"),
            project_id=request.get("project_id"),
            description=request.get("description", ""),
            actor=actor,
            project_ir=request.get("project_ir"),
        )}
    if action == "project.list":
        return {"projects": application.list_projects(include_archived=_boolean(request, "include_archived", False))}
    if action == "project.get":
        return {"project": application.get_project(request.get("project_id"))}
    if action == "project.rename":
        return {"revision": application.rename_project(
            request.get("project_id"),
            name=request.get("name"),
            base_revision_id=request.get("base_revision_id"),
            operation_batch_id=request.get("operation_batch_id"),
            actor=actor,
        )}
    if action == "project.duplicate":
        return {"project": application.duplicate_project(
            request.get("project_id"),
            name=request.get("name"),
            project_id=request.get("new_project_id"),
            actor=actor,
        )}
    if action in {"project.archive", "project.restore"}:
        method = application.archive_project if action.endswith("archive") else application.restore_project
        return {"project": method(request.get("project_id"))}
    if action == "revision.get":
        return {"revision": application.get_revision(request.get("project_id"), request.get("revision_id"))}
    if action == "revision.compare":
        return {"comparison": application.compare_revisions(
            request.get("project_id"),
            request.get("before_revision_id"),
            request.get("after_revision_id"),
        )}
    if action == "native.export":
        return {"native_project": application.export_native(request.get("project_id"), request.get("revision_id"))}
    if action == "native.import":
        return {"project": application.import_native(
            request.get("native_project"),
            project_id=request.get("project_id"),
            name=request.get("name"),
            actor=actor,
        )}
    if action == "operations.apply":
        return {"revision": application.apply_operations(_authoritative_batch(request.get("batch"), actor))}
    if action == "history.undo":
        return {"revision": application.undo(_authoritative_batch(request.get("batch"), actor))}
    if action == "history.redo":
        return {"revision": application.redo(_authoritative_batch(request.get("batch"), actor))}
    raise ProjectError("unsupported_action", "Unsupported Video Studio action.")


def app_events_for_result(action: str, result: dict[str, Any]) -> list[dict[str, str]]:
    resources: list[str] = []
    if action in {"project.create", "project.duplicate", "native.import"}:
        resources = ["projects", "revisions"]
    elif action in {"project.archive", "project.restore"}:
        resources = ["projects"]
    elif action == "project.rename":
        resources = ["project-metadata", "revisions"]
    elif action == "operations.apply":
        resources = ["revisions"]
        operations = result.get("revision", {}).get("applied_operations", [])
        if "project.rename" in operations:
            resources.insert(0, "project-metadata")
    elif action in {"history.undo", "history.redo"}:
        resources = ["revisions"]
    return [
        {
            "type": "maverick.app.data-changed",
            "owner_app_id": "video-studio",
            "resource": resource,
        }
        for resource in resources
    ]


def _boolean(request: dict[str, Any], field: str, default: bool) -> bool:
    value = request.get(field, default)
    if not isinstance(value, bool):
        raise ProjectError("boolean_invalid", "Action value must be boolean.", path=f"/{field}")
    return value


def actor_from_entrypoint(raw: dict[str, Any]) -> dict[str, str]:
    """Build audit identity only from the host-owned entrypoint envelope."""

    agent_id = raw.get("agent_id")
    if isinstance(agent_id, str) and _IDENTIFIER.fullmatch(agent_id):
        return {"kind": "agent", "id": agent_id}
    user_id = raw.get("user_id")
    if isinstance(user_id, str) and _IDENTIFIER.fullmatch(user_id):
        return {"kind": "user", "id": user_id}
    return {"kind": "system", "id": "video-studio"}


def _authoritative_batch(value: object, actor: dict[str, str]) -> object:
    if not isinstance(value, dict):
        return value
    batch = deepcopy(value)
    batch["actor"] = dict(actor)
    return batch


def _error(error: ProjectError) -> tuple[int, dict[str, Any]]:
    return error.status_code, {"ok": False, "error": error.to_dict()}
