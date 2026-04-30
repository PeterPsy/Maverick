"""Chat app backend entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from chat_state import (
    create_project,
    clear_custom_view,
    delete_project,
    list_projects,
    mutate_state,
    read_state,
    set_custom_view,
    set_view_filter,
    state_path,
    update_project,
)

DATA_CHANGED_ACTIONS = {
    "projects.create",
    "projects.update",
    "projects.delete",
    "view_filter.set",
    "view_filter.custom",
    "view_filter.clear",
}


def app_events_for_action(action: str) -> list[dict]:
    if action.startswith("projects.") and action in DATA_CHANGED_ACTIONS:
        return [{"type": "maverick.app.data-changed", "resource": "projects"}]
    if action.startswith("view_filter.") and action in DATA_CHANGED_ACTIONS:
        return [{"type": "maverick.app.data-changed", "resource": "view-state"}]
    return []


def _response(status_code: int, payload: dict) -> None:
    response = {"status_code": status_code, "json": payload}
    if status_code < 400:
        response["app_events"] = app_events_for_action(str(payload.pop("_action", "")))
    print(json.dumps(response, ensure_ascii=False))


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    action = str(body.get("action") or "projects.list")
    data_root = Path(payload["data_root"])
    path = state_path(data_root)
    state = read_state(path)

    if action == "projects.list":
        _response(200, {"projects": list_projects(state), "preferences": state.get("preferences", {})})
        return
    if action == "projects.create":
        state, result = mutate_state(path, lambda current: {"project": create_project(current, body)})
        project = result["project"]
        _response(201, {"project": project, "projects": list_projects(state), "preferences": state.get("preferences", {}), "_action": action})
        return
    if action == "projects.update":
        state, result = mutate_state(path, lambda current: {"project": update_project(current, body)})
        project = result["project"]
        if project is None:
            _response(404, {"error": "project_not_found"})
            return
        _response(200, {"project": project, "projects": list_projects(state), "preferences": state.get("preferences", {}), "_action": action})
        return
    if action == "projects.delete":
        state, result = mutate_state(path, lambda current: {"deleted": delete_project(current, body)})
        if not result["deleted"]:
            _response(404, {"error": "project_not_found"})
            return
        _response(200, {"projects": list_projects(state), "preferences": state.get("preferences", {}), "_action": action})
        return
    if action == "view_filter":
        _response(200, {"state": {"view_filter": state.get("preferences", {}).get("view_filter")}})
        return
    if action == "set_view_filter":
        state, result = mutate_state(path, lambda current: {"view_filter": set_view_filter(current, body)})
        view_filter = result["view_filter"]
        _response(200, {"state": {"view_filter": view_filter}, "_action": "view_filter.set"})
        return
    if action == "set_custom_view":
        state, result = mutate_state(path, lambda current: {"view_filter": set_custom_view(current, body)})
        view_filter = result["view_filter"]
        _response(200, {"state": {"view_filter": view_filter}, "_action": "view_filter.custom"})
        return
    if action == "clear_custom_view":
        state, result = mutate_state(path, lambda current: {"view_filter": clear_custom_view(current)})
        view_filter = result["view_filter"]
        _response(200, {"state": {"view_filter": view_filter}, "_action": "view_filter.clear"})
        return
    if action == "health.check":
        path.parent.mkdir(parents=True, exist_ok=True)
        _response(200, {"status": "ok", "data_root": str(data_root)})
        return
    _response(400, {"error": "unsupported_action", "action": action})


if __name__ == "__main__":
    main()
