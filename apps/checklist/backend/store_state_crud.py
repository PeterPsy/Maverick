"""App-owned JSON store for the Checklist workspace app."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.app_sdk.storage import read_json_state, write_json_state


STATE_FILE = "state.json"
CHECKLIST_KIND = "checklist.design"
REFERENCE_ENTITY_TYPE = "checklist"
WIDGET_CONTENT_KIND = "checklist.design"


def now_iso() -> str:
    """Return an ISO timestamp suitable for persisted app records."""
    return datetime.now(timezone.utc).isoformat()



def empty_state() -> dict[str, Any]:
    """Return the default persisted state."""
    return {
        "schema_version": "3",
        "checklists": [],
        "view_state": {
            "mode": "default",
            "query": "",
            "title": "",
            "refs": [],
        },
    }



def load_state(data_root: Path) -> dict[str, Any]:
    """Load checklist state and normalize old SDK dogfood records in memory."""
    state = read_json_state(data_root, STATE_FILE, empty_state())
    state["schema_version"] = "3"
    state["checklists"] = [_normalize_checklist(item) for item in state.get("checklists", []) if isinstance(item, dict)]
    state["view_state"] = _normalize_view_state(state.get("view_state"))
    return state



def save_state(data_root: Path, state: dict[str, Any]) -> None:
    """Persist checklist state."""
    state["schema_version"] = "3"
    state["view_state"] = _normalize_view_state(state.get("view_state"))
    write_json_state(data_root, STATE_FILE, state)



def list_checklists(data_root: Path, *, profile: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    """Return checklists in stable creation order, newest created first."""
    state = load_state(data_root)
    items = list(state.get("checklists", []))
    if profile:
        items = [item for item in items if item.get("profile") == profile]
    items = _apply_view_state(items, state.get("view_state") or {})
    items.sort(key=lambda item: str(item.get("created_at") or item.get("updated_at") or ""), reverse=True)
    return deepcopy(items[:limit] if limit else items)



def read_checklist(data_root: Path, checklist_id: str) -> dict[str, Any]:
    """Read one checklist by id."""
    return deepcopy(_find_checklist(load_state(data_root), checklist_id))



def create_checklist(data_root: Path, payload: dict[str, Any], *, workspace_id: str) -> dict[str, Any]:
    """Create a design checklist."""
    state = load_state(data_root)
    timestamp = now_iso()
    sections = _normalize_sections(payload.get("sections"))
    title = _clean_text(payload.get("title"), "Checklist", max_length=240)
    summary = _summary_for(sections, _clean_text(payload.get("summary"), "", max_length=1000))
    checklist = {
        "id": _new_id("check"),
        "workspace_id": _required_workspace_id(workspace_id),
        "profile": _optional_text(payload.get("profile"), max_length=120),
        "kind": CHECKLIST_KIND,
        "title": title,
        "summary": summary,
        "sections": sections,
        "source_type": _clean_text(payload.get("source_type"), "chat_preview", max_length=80),
        "source_ref": _clean_text(payload.get("source_ref"), "", max_length=240),
        "status": _clean_text(payload.get("status"), "active", max_length=40),
        "metadata": _metadata(title=title, summary=summary, sections=sections, metadata=payload.get("metadata")),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    state["checklists"] = [*state.get("checklists", []), checklist]
    save_state(data_root, state)
    return deepcopy(_with_counts(checklist))



def update_checklist(data_root: Path, checklist_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Update one checklist using the current payload shape."""
    state = load_state(data_root)
    checklist = _find_checklist(state, checklist_id)
    if "sections" in payload:
        checklist["sections"] = _normalize_sections(payload.get("sections"))
    if "title" in payload:
        checklist["title"] = _clean_text(payload.get("title"), "Checklist", max_length=240)
    if "summary" in payload:
        checklist["summary"] = _summary_for(
            checklist["sections"],
            _clean_text(payload.get("summary"), "", max_length=1000),
        )
    elif _is_progress_summary(str(checklist.get("summary") or "")):
        checklist["summary"] = _summary_for(checklist["sections"], "")
    for key, max_length in {
        "source_type": 80,
        "source_ref": 240,
        "status": 40,
        "profile": 120,
    }.items():
        if key in payload:
            value = _optional_text(payload.get(key), max_length=max_length)
            checklist[key] = value if key == "profile" else value or ""
    if isinstance(payload.get("metadata"), dict):
        checklist["metadata"] = {**dict(checklist.get("metadata") or {}), **payload["metadata"]}
    checklist["metadata"] = _metadata(
        title=str(checklist.get("title") or "Checklist"),
        summary=str(checklist.get("summary") or ""),
        sections=list(checklist.get("sections") or []),
        metadata=checklist.get("metadata"),
    )
    checklist["updated_at"] = now_iso()
    save_state(data_root, state)
    return deepcopy(_with_counts(checklist))



def delete_checklist(data_root: Path, checklist_id: str) -> dict[str, str]:
    """Delete one checklist by id."""
    state = load_state(data_root)
    before = len(state.get("checklists", []))
    state["checklists"] = [item for item in state.get("checklists", []) if item.get("id") != checklist_id]
    if len(state["checklists"]) == before:
        raise ValueError(f"Checklist `{checklist_id}` was not found.")
    save_state(data_root, state)
    return {"status": "deleted", "deleted_id": checklist_id}



def add_task(data_root: Path, *, checklist_id: str, section_id: str | None, title: str) -> dict[str, Any]:
    """Add one task to a section."""
    checklist = read_checklist(data_root, checklist_id)
    sections = list(checklist.get("sections") or [])
    section = _find_or_create_section(sections, section_id)
    task = _normalize_task({"title": title}, len(sections), len(section.get("tasks", [])))
    if task is None:
        raise ValueError("Task title is required.")
    section.setdefault("tasks", []).append(task)
    update_checklist(data_root, checklist_id, {"sections": sections})
    return deepcopy(task)



def toggle_task(data_root: Path, *, checklist_id: str, section_id: str, task_id: str) -> dict[str, Any]:
    """Toggle one task's checked state."""
    checklist = read_checklist(data_root, checklist_id)
    sections = list(checklist.get("sections") or [])
    for section in sections:
        if section.get("id") != section_id:
            continue
        for task in section.get("tasks", []):
            if task.get("id") == task_id:
                task["checked"] = not bool(task.get("checked"))
                update_checklist(data_root, checklist_id, {"sections": sections})
                return deepcopy(task)
    raise ValueError(f"Task `{task_id}` was not found.")



def chat_render(checklist: dict[str, Any]) -> dict[str, Any]:
    """Return the chat widget render payload."""
    return {
        "kind": WIDGET_CONTENT_KIND,
        "memory": {"checklist_id": checklist["id"]},
        "payload": {"id": checklist["id"]},
    }



def reference_manifest() -> dict[str, Any]:
    """Return the reference manifest for checklist-owned entities."""
    return {
        "entity_types": [
            {
                "entity_type": REFERENCE_ENTITY_TYPE,
                "display_name": "Checklist",
                "searchable": True,
                "resolvable": True,
                "summarizable": True,
                "deep_link_supported": True,
            }
        ]
    }



def reference_search(data_root: Path, *, query: str, limit: int | None = None) -> dict[str, Any]:
    """Search checklist references by title, summary, and task text."""
    clean_query = query.strip().lower()
    items = list(load_state(data_root).get("checklists", []))
    if clean_query:
        items = [item for item in items if _matches_query(item, clean_query)]
    items.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
    if limit:
        items = items[:limit]
    return {
        "query": query,
        "results": [_reference_record(item) for item in items],
    }



def reference_resolve(data_root: Path, *, entity_type: str, entity_id: str) -> dict[str, Any]:
    """Resolve one checklist reference."""
    if entity_type != REFERENCE_ENTITY_TYPE:
        raise ValueError(f"Unsupported entity type `{entity_type}`.")
    try:
        checklist = read_checklist(data_root, entity_id)
    except ValueError:
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "exists": False,
        }
    return {
        **_reference_record(checklist),
        "exists": True,
        "payload": {
            "title": checklist["title"],
            "summary": checklist["summary"],
            "sections": deepcopy(checklist["sections"]),
        },
    }
