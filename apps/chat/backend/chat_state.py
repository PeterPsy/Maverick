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
        "preferences": {"active_thread_id": None, "view_filter": default_view_filter()},
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
    payload["preferences"].setdefault("active_thread_id", None)
    payload["preferences"]["view_filter"] = normalize_view_filter(payload["preferences"].get("view_filter"))
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
        "agent_label": str(thread.get("agent_label") or ""),
        "agent_type_id": str(thread.get("agent_type_id") or ""),
        "agent_role_id": str(thread.get("agent_role_id") or ""),
        "source_app_id": str(thread.get("source_app_id") or ""),
        "system_prompt": str(thread.get("system_prompt") or ""),
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


def default_view_filter() -> dict:
    return {
        "mode": "search",
        "query": "",
        "entity_type": "all",
        "title": "",
        "refs": [],
        "updated_at": now_timestamp(),
    }


def normalize_view_filter(raw_filter: object) -> dict:
    if not isinstance(raw_filter, dict):
        return default_view_filter()
    entity_type = str(raw_filter.get("entity_type") or "all").strip() or "all"
    if entity_type not in {"all", "thread", "project"}:
        entity_type = "all"
    refs = []
    for item in raw_filter.get("refs") if isinstance(raw_filter.get("refs"), list) else []:
        if not isinstance(item, dict):
            continue
        ref_entity_type = str(item.get("entity_type") or "").strip()
        ref_entity_id = str(item.get("entity_id") or "").strip()
        if ref_entity_type in {"thread", "project"} and ref_entity_id:
            refs.append({"entity_type": ref_entity_type, "entity_id": ref_entity_id})
    return {
        "mode": "custom" if str(raw_filter.get("mode") or "") == "custom" else "search",
        "query": str(raw_filter.get("query") or "").strip(),
        "entity_type": entity_type,
        "title": str(raw_filter.get("title") or "").strip(),
        "refs": refs,
        "updated_at": str(raw_filter.get("updated_at") or now_timestamp()),
    }


def set_view_filter(state: dict, body: dict) -> dict:
    current = normalize_view_filter(state.get("preferences", {}).get("view_filter"))
    preserve_custom = bool(body.get("preserve_custom")) and current.get("mode") == "custom"
    state["preferences"]["view_filter"] = normalize_view_filter(
        {
            "mode": "custom" if preserve_custom else "search",
            "query": str(body.get("query") if "query" in body else current.get("query") or "").strip(),
            "entity_type": str(body.get("entity_type") if "entity_type" in body else current.get("entity_type") or "all").strip() or "all",
            "title": current.get("title") if preserve_custom else "",
            "refs": current.get("refs") if preserve_custom else [],
            "updated_at": now_timestamp(),
        }
    )
    return state["preferences"]["view_filter"]


def set_custom_view(state: dict, body: dict) -> dict:
    state["preferences"]["view_filter"] = normalize_view_filter(
        {
            "mode": "custom",
            "query": str(body.get("query") or "").strip(),
            "entity_type": str(body.get("entity_type") or "all").strip() or "all",
            "title": str(body.get("title") or "").strip(),
            "refs": body.get("refs") if isinstance(body.get("refs"), list) else [],
            "updated_at": now_timestamp(),
        }
    )
    return state["preferences"]["view_filter"]


def clear_custom_view(state: dict) -> dict:
    current = normalize_view_filter(state.get("preferences", {}).get("view_filter"))
    state["preferences"]["view_filter"] = normalize_view_filter(
        {
            "mode": "search",
            "query": current.get("query"),
            "entity_type": current.get("entity_type"),
            "title": "",
            "refs": [],
            "updated_at": now_timestamp(),
        }
    )
    return state["preferences"]["view_filter"]


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


def find_thread(state: dict, thread_id: str) -> dict | None:
    for thread in state.get("threads", []):
        if isinstance(thread, dict) and thread.get("thread_id") == thread_id:
            return thread_payload(thread)
    return None


def find_thread_by_runtime_session(state: dict, runtime_session_id: str) -> dict | None:
    if not runtime_session_id:
        return None
    for thread in state.get("threads", []):
        if isinstance(thread, dict) and thread.get("runtime_session_id") == runtime_session_id:
            state["preferences"]["active_thread_id"] = thread.get("thread_id")
            return thread_payload(thread)
    return None


def create_thread(state: dict, body: dict) -> dict:
    timestamp = now_timestamp()
    title = str(body.get("title") or "").strip() or "New chat"
    runtime_session_id = str(body.get("runtime_session_id") or "").strip()
    existing_thread = find_thread_by_runtime_session(state, runtime_session_id)
    if existing_thread is not None:
        return existing_thread
    project_id = str(body.get("project_id") or "").strip() or None
    thread = {
        "thread_id": str(uuid4()),
        "runtime_session_id": runtime_session_id,
        "title": title[:80],
        "agent_label": str(body.get("agent_label") or "").strip()[:120],
        "agent_type_id": str(body.get("agent_type_id") or "").strip()[:120],
        "agent_role_id": str(body.get("agent_role_id") or "").strip()[:120],
        "source_app_id": str(body.get("source_app_id") or "").strip()[:80],
        "system_prompt": str(body.get("system_prompt") or "").strip(),
        "project_id": project_id,
        "archived": False,
        "availability": "free",
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    state["threads"].append(thread)
    state["preferences"]["active_thread_id"] = thread["thread_id"]
    return thread_payload(thread)


def delete_thread(state: dict, body: dict) -> dict | None:
    thread_id = str(body.get("thread_id") or "").strip()
    deleted_thread = find_thread(state, thread_id)
    if deleted_thread is None:
        return None
    state["threads"] = [
        thread for thread in state.get("threads", []) if isinstance(thread, dict) and thread.get("thread_id") != thread_id
    ]
    if state.get("preferences", {}).get("active_thread_id") == thread_id:
        state["preferences"]["active_thread_id"] = None
    return deleted_thread


def delete_threads_by_runtime_session_ids(state: dict, runtime_session_ids: list[str]) -> list[dict]:
    normalized_ids = {str(session_id).strip() for session_id in runtime_session_ids if str(session_id).strip()}
    if not normalized_ids:
        return []
    deleted_threads = [
        thread_payload(thread)
        for thread in state.get("threads", [])
        if isinstance(thread, dict) and str(thread.get("runtime_session_id") or "") in normalized_ids
    ]
    if not deleted_threads:
        return []
    deleted_thread_ids = {thread["thread_id"] for thread in deleted_threads}
    state["threads"] = [
        thread
        for thread in state.get("threads", [])
        if not (
            isinstance(thread, dict)
            and str(thread.get("runtime_session_id") or "") in normalized_ids
        )
    ]
    if state.get("preferences", {}).get("active_thread_id") in deleted_thread_ids:
        state["preferences"]["active_thread_id"] = None
    return deleted_threads


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
        if "agent_label" in body:
            thread["agent_label"] = str(body.get("agent_label") or "").strip()[:120]
        if "agent_type_id" in body:
            thread["agent_type_id"] = str(body.get("agent_type_id") or "").strip()[:120]
        if "agent_role_id" in body:
            thread["agent_role_id"] = str(body.get("agent_role_id") or "").strip()[:120]
        if "source_app_id" in body:
            thread["source_app_id"] = str(body.get("source_app_id") or "").strip()[:80]
        if "system_prompt" in body:
            thread["system_prompt"] = str(body.get("system_prompt") or "").strip()
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
