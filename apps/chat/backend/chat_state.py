"""JSON-backed chat app state helpers."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import uuid4


def now_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()


def empty_state() -> dict:
    return {
        "schema_version": "2",
        "projects": [],
        "threads": [],
        "preferences": {"active_thread_id": None},
    }


def threads_path(data_root: Path) -> Path:
    return data_root / "threads.json"


def read_state(path: Path) -> dict:
    if not path.is_file():
        return empty_state()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return empty_state()
    if not isinstance(payload, dict):
        return empty_state()
    payload.setdefault("schema_version", "2")
    payload.setdefault("projects", [])
    payload.setdefault("threads", [])
    payload.setdefault("preferences", {"active_thread_id": None})
    if not isinstance(payload["preferences"], dict):
        payload["preferences"] = {"active_thread_id": None}
    return payload


def write_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def project_payload(project: dict) -> dict:
    return {
        "project_id": str(project.get("project_id") or ""),
        "name": str(project.get("name") or "Untitled project"),
        "created_at": str(project.get("created_at") or ""),
        "updated_at": str(project.get("updated_at") or ""),
    }


def thread_payload(thread: dict) -> dict:
    return {
        "thread_id": str(thread.get("thread_id") or ""),
        "runtime_session_id": str(thread.get("runtime_session_id") or ""),
        "title": str(thread.get("title") or "New chat"),
        "project_id": str(thread.get("project_id") or "") or None,
        "archived": bool(thread.get("archived", False)),
        "availability": str(thread.get("availability") or "free"),
        "created_at": str(thread.get("created_at") or ""),
        "updated_at": str(thread.get("updated_at") or ""),
    }


def list_projects(state: dict) -> list[dict]:
    projects = [project_payload(project) for project in state.get("projects", []) if isinstance(project, dict)]
    return sorted(projects, key=lambda item: item["name"].casefold())


def list_threads(state: dict) -> list[dict]:
    threads = [thread_payload(thread) for thread in state.get("threads", []) if isinstance(thread, dict)]
    return sorted(threads, key=lambda item: item["updated_at"], reverse=True)


def create_project(state: dict, body: dict) -> dict:
    timestamp = now_timestamp()
    name = str(body.get("name") or "").strip() or "New project"
    project = {
        "project_id": str(uuid4()),
        "name": name[:80],
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    state["projects"].append(project)
    return project_payload(project)


def update_project(state: dict, body: dict) -> dict | None:
    project_id = str(body.get("project_id") or "").strip()
    timestamp = now_timestamp()
    for project in state.get("projects", []):
        if not isinstance(project, dict) or project.get("project_id") != project_id:
            continue
        if "name" in body:
            name = str(body.get("name") or "").strip()
            if name:
                project["name"] = name[:80]
        project["updated_at"] = timestamp
        return project_payload(project)
    return None


def delete_project(state: dict, body: dict) -> bool:
    project_id = str(body.get("project_id") or "").strip()
    original = len(state.get("projects", []))
    state["projects"] = [
        project for project in state.get("projects", []) if isinstance(project, dict) and project.get("project_id") != project_id
    ]
    for thread in state.get("threads", []):
        if isinstance(thread, dict) and thread.get("project_id") == project_id:
            thread["project_id"] = None
            thread["updated_at"] = now_timestamp()
    return len(state["projects"]) != original


def create_thread(state: dict, body: dict) -> dict:
    timestamp = now_timestamp()
    title = str(body.get("title") or "").strip() or "New chat"
    runtime_session_id = str(body.get("runtime_session_id") or "").strip()
    project_id = str(body.get("project_id") or "").strip() or None
    thread = {
        "thread_id": str(uuid4()),
        "runtime_session_id": runtime_session_id,
        "title": title[:80],
        "project_id": project_id,
        "archived": False,
        "availability": "free",
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    state["threads"].append(thread)
    state["preferences"]["active_thread_id"] = thread["thread_id"]
    return thread_payload(thread)


def update_thread(state: dict, body: dict) -> dict | None:
    thread_id = str(body.get("thread_id") or "").strip()
    timestamp = now_timestamp()
    for thread in state.get("threads", []):
        if not isinstance(thread, dict) or thread.get("thread_id") != thread_id:
            continue
        if "title" in body:
            title = str(body.get("title") or "").strip()
            if title:
                thread["title"] = title[:80]
        if "runtime_session_id" in body:
            thread["runtime_session_id"] = str(body.get("runtime_session_id") or "").strip()
        if "project_id" in body:
            thread["project_id"] = str(body.get("project_id") or "").strip() or None
        if "archived" in body:
            thread["archived"] = bool(body.get("archived"))
        if "availability" in body:
            thread["availability"] = str(body.get("availability") or "free")
        thread["updated_at"] = timestamp
        state["preferences"]["active_thread_id"] = thread["thread_id"]
        return thread_payload(thread)
    return None


def sidebar_snapshot(state: dict) -> dict:
    return {
        "projects": list_projects(state),
        "threads": list_threads(state),
        "preferences": state.get("preferences", {}),
    }
