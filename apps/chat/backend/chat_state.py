"""JSON-backed chat app state helpers."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import uuid4

from core.app_sdk.storage import read_json_state, update_json_state, write_json_state


def now_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()


def empty_state() -> dict:
    return {
        "schema_version": "2",
        "projects": [],
        "preferences": {"view_filter": default_view_filter()},
    }


def state_path(data_root: Path) -> Path:
    return data_root / "state.json"


def read_state(path: Path) -> dict:
    try:
        payload = read_json_state(path.parent, path.name, empty_state())
    except (ValueError, json.JSONDecodeError):
        return empty_state()
    return normalize_state(payload)


def normalize_state(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return empty_state()
    payload.setdefault("schema_version", "2")
    payload.setdefault("projects", [])
    if not isinstance(payload["projects"], list):
        payload["projects"] = []
    payload.setdefault("preferences", {})
    if not isinstance(payload["preferences"], dict):
        payload["preferences"] = {}
    payload["preferences"]["view_filter"] = normalize_view_filter(payload["preferences"].get("view_filter"))
    return payload


def write_state(path: Path, payload: dict) -> None:
    write_json_state(path.parent, path.name, payload)


def mutate_state(path: Path, mutator) -> tuple[dict, dict]:
    result: dict = {}

    def _update(payload: dict) -> dict:
        state = normalize_state(payload)
        result.update(mutator(state) or {})
        return state

    state = update_json_state(path.parent, path.name, _update, default=empty_state())
    return state, result


def project_payload(project: dict) -> dict:
    return {
        "project_id": str(project.get("project_id") or ""),
        "name": str(project.get("name") or "Untitled project"),
        "created_at": str(project.get("created_at") or ""),
        "updated_at": str(project.get("updated_at") or ""),
    }


def list_projects(state: dict) -> list[dict]:
    projects = [project_payload(project) for project in state.get("projects", []) if isinstance(project, dict)]
    return sorted(projects, key=lambda item: item["name"].casefold())


def project_exists(state: dict, project_id: str) -> bool:
    normalized_project_id = project_id.strip()
    if not normalized_project_id:
        return False
    return any(
        isinstance(project, dict) and project.get("project_id") == normalized_project_id
        for project in state.get("projects", [])
    )


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
    return len(state["projects"]) != original
