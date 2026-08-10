"""Transport-neutral project and revision action router."""

from __future__ import annotations

from pathlib import Path
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


def handle_action(
    data_root: str | Path,
    workspace_id: object,
    request: object,
) -> tuple[int, dict[str, Any]]:
    if not isinstance(request, dict):
        return _error(ProjectError("request_invalid", "Action request must be an object."))
    action = str(request.get("action") or "status").strip().lower()
    if action in FOUNDATION_ACTIONS:
        return handle_foundation_action(data_root, action)
    if action not in PROJECT_ACTIONS:
        return _error(ProjectError("unsupported_action", "Unsupported Video Studio action."))
    try:
        application = ProjectService(data_root, workspace_id=workspace_id)  # type: ignore[arg-type]
        result = _dispatch(application, action, request)
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


def _dispatch(application: ProjectService, action: str, request: dict[str, Any]) -> dict[str, Any]:
    if action == "project.create":
        return {"project": application.create_project(
            name=request.get("name"),
            project_id=request.get("project_id"),
            description=request.get("description", ""),
            actor=request.get("actor"),
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
            actor=request.get("actor"),
        )}
    if action == "project.duplicate":
        return {"project": application.duplicate_project(
            request.get("project_id"),
            name=request.get("name"),
            project_id=request.get("new_project_id"),
            actor=request.get("actor"),
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
            actor=request.get("actor"),
        )}
    if action == "operations.apply":
        return {"revision": application.apply_operations(request.get("batch"))}
    if action == "history.undo":
        return {"revision": application.undo(request.get("batch"))}
    if action == "history.redo":
        return {"revision": application.redo(request.get("batch"))}
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


def _error(error: ProjectError) -> tuple[int, dict[str, Any]]:
    return error.status_code, {"ok": False, "error": error.to_dict()}
