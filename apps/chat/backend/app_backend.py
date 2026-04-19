"""Chat app backend entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from chat_state import (
    create_project,
    create_thread,
    delete_project,
    list_projects,
    list_threads,
    read_state,
    sidebar_snapshot,
    threads_path,
    update_project,
    update_thread,
    write_state,
)


def _response(status_code: int, payload: dict) -> None:
    print(json.dumps({"status_code": status_code, "json": payload}, ensure_ascii=False))


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    action = str(body.get("action") or "threads.list")
    data_root = Path(payload["data_root"])
    path = threads_path(data_root)
    state = read_state(path)

    if action == "threads.list":
        _response(200, {"threads": list_threads(state), "preferences": state.get("preferences", {})})
        return
    if action == "threads.create":
        thread = create_thread(state, body)
        write_state(path, state)
        _response(201, {"thread": thread, "threads": list_threads(state), "projects": list_projects(state)})
        return
    if action == "threads.update":
        thread = update_thread(state, body)
        if thread is None:
            _response(404, {"error": "thread_not_found"})
            return
        write_state(path, state)
        _response(200, {"thread": thread, "threads": list_threads(state), "projects": list_projects(state)})
        return
    if action == "projects.list":
        _response(200, {"projects": list_projects(state), "threads": list_threads(state)})
        return
    if action == "projects.create":
        project = create_project(state, body)
        write_state(path, state)
        _response(201, {"project": project, **sidebar_snapshot(state)})
        return
    if action == "projects.update":
        project = update_project(state, body)
        if project is None:
            _response(404, {"error": "project_not_found"})
            return
        write_state(path, state)
        _response(200, {"project": project, **sidebar_snapshot(state)})
        return
    if action == "projects.delete":
        if not delete_project(state, body):
            _response(404, {"error": "project_not_found"})
            return
        write_state(path, state)
        _response(200, sidebar_snapshot(state))
        return
    if action == "sidebar.snapshot":
        _response(200, sidebar_snapshot(state))
        return
    if action == "health.check":
        path.parent.mkdir(parents=True, exist_ok=True)
        _response(200, {"status": "ok", "data_root": str(data_root)})
        return
    _response(400, {"error": "unsupported_action", "action": action})


if __name__ == "__main__":
    main()
