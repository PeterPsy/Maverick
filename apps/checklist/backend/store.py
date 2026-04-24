"""App-owned JSON store for the Checklist workspace app."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.app_sdk.storage import read_json_state, write_json_state


STATE_FILE = "state.json"
CHECKLIST_KIND = "design_checklist"
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


def create_checklist(data_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Create a v2-style design checklist."""
    state = load_state(data_root)
    timestamp = now_iso()
    sections = _normalize_sections(payload.get("sections"))
    title = _clean_text(payload.get("title"), "Checklist", max_length=240)
    summary = _summary_for(sections, _clean_text(payload.get("summary"), "", max_length=1000))
    checklist = {
        "id": _new_id("check"),
        "workspace_id": _clean_text(payload.get("workspace_id"), "default", max_length=120),
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
    """Update one checklist using the v2 payload shape."""
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
    """Return the chat widget render payload used by the v2 app."""
    return {
        "kind": WIDGET_CONTENT_KIND,
        "legacy_kind": CHECKLIST_KIND,
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


def reference_summarize(data_root: Path, *, entity_type: str, entity_id: str) -> dict[str, Any]:
    """Summarize one checklist reference."""
    resolved = reference_resolve(data_root, entity_type=entity_type, entity_id=entity_id)
    if not resolved.get("exists"):
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "exists": False,
            "summary": "",
        }
    payload = resolved.get("payload") or {}
    sections = payload.get("sections") if isinstance(payload, dict) else []
    tasks = [task for section in sections if isinstance(section, dict) for task in section.get("tasks", []) if isinstance(task, dict)]
    checked = sum(1 for task in tasks if task.get("checked"))
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "exists": True,
        "title": resolved["title"],
        "summary": f"{resolved['title']} | {checked}/{len(tasks)} checked | {resolved['summary']}",
    }


def read_view_filter(data_root: Path) -> dict[str, Any]:
    """Return persisted view state for the checklist board."""
    return deepcopy(load_state(data_root).get("view_state") or _normalize_view_state(None))


def set_view_filter(data_root: Path, *, query: str) -> dict[str, Any]:
    """Persist the default board query filter."""
    state = load_state(data_root)
    view_state = _normalize_view_state(state.get("view_state"))
    view_state["mode"] = "default"
    view_state["query"] = query.strip()[:240]
    view_state["title"] = ""
    view_state["refs"] = []
    state["view_state"] = view_state
    save_state(data_root, state)
    return deepcopy(view_state)


def set_custom_view(data_root: Path, *, title: str, refs: Any) -> dict[str, Any]:
    """Persist a curated checklist board view."""
    clean_refs = _normalize_custom_view_refs(refs)
    state = load_state(data_root)
    view_state = _normalize_view_state(state.get("view_state"))
    view_state["mode"] = "custom"
    view_state["query"] = ""
    view_state["title"] = _clean_text(title, "Checklist view", max_length=240)
    view_state["refs"] = clean_refs
    state["view_state"] = view_state
    save_state(data_root, state)
    return deepcopy(view_state)


def clear_custom_view(data_root: Path) -> dict[str, Any]:
    """Reset the checklist board to the default view state."""
    state = load_state(data_root)
    state["view_state"] = _normalize_view_state(None)
    save_state(data_root, state)
    return deepcopy(state["view_state"])


def tool_payload(action: str, checklist: dict[str, Any]) -> dict[str, Any]:
    """Return a structured MCP/CLI payload compatible with the v2 tasklist tool."""
    checklist = _with_counts(checklist)
    return {
        "action": action,
        "summary": (
            f"tasklist {action} | id={checklist['id']} | title={checklist['title']} | "
            f"sections={len(checklist['sections'])} | tasks={checklist['task_count']} | checked={checklist['checked_count']}"
        ),
        "checklist": checklist,
        "chat_render": chat_render(checklist),
    }


def _find_checklist(state: dict[str, Any], checklist_id: str) -> dict[str, Any]:
    clean_id = checklist_id.strip()
    for checklist in state.get("checklists", []):
        if checklist.get("id") == clean_id:
            return checklist
    raise ValueError(f"Checklist `{checklist_id}` was not found.")


def _find_or_create_section(sections: list[dict[str, Any]], section_id: str | None) -> dict[str, Any]:
    clean_id = (section_id or "").strip()
    if clean_id:
        for section in sections:
            if section.get("id") == clean_id:
                return section
    if sections:
        return sections[0]
    section = {"id": "section-default", "title": "", "tasks": []}
    sections.append(section)
    return section


def _normalize_checklist(value: dict[str, Any]) -> dict[str, Any]:
    timestamp = str(value.get("created_at") or now_iso())
    if "sections" not in value and "items" in value:
        value = {
            **value,
            "sections": [
                {
                    "id": "section-default",
                    "title": "",
                    "tasks": [
                        {"id": item.get("id"), "title": item.get("text"), "checked": item.get("done")}
                        for item in value.get("items", [])
                        if isinstance(item, dict)
                    ],
                }
            ],
        }
    sections = _normalize_sections(value.get("sections"))
    title = _clean_text(value.get("title"), "Checklist", max_length=240)
    summary = _summary_for(sections, _clean_text(value.get("summary"), "", max_length=1000))
    return _with_counts(
        {
            "id": _clean_text(value.get("id"), _new_id("check"), max_length=200),
            "workspace_id": _clean_text(value.get("workspace_id"), "default", max_length=120),
            "profile": _optional_text(value.get("profile"), max_length=120),
            "kind": CHECKLIST_KIND,
            "title": title,
            "summary": summary,
            "sections": sections,
            "source_type": _clean_text(value.get("source_type"), "chat_preview", max_length=80),
            "source_ref": _clean_text(value.get("source_ref"), "", max_length=240),
            "status": _clean_text(value.get("status"), "active", max_length=40),
            "metadata": _metadata(title=title, summary=summary, sections=sections, metadata=value.get("metadata")),
            "created_at": timestamp,
            "updated_at": str(value.get("updated_at") or timestamp),
        }
    )


def _normalize_sections(value: Any) -> list[dict[str, Any]]:
    raw_sections = value if isinstance(value, list) else []
    sections = [
        section
        for index, item in enumerate(raw_sections)
        if (section := _normalize_section(item, index)) is not None
    ]
    return sections or [{"id": "section-default", "title": "", "tasks": []}]


def _normalize_section(value: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    raw_tasks = value.get("tasks") if isinstance(value.get("tasks"), list) else []
    tasks = [
        task
        for task_index, raw_task in enumerate(raw_tasks)
        if (task := _normalize_task(raw_task, index, task_index)) is not None
    ]
    return {
        "id": _clean_text(value.get("id"), f"section-{index + 1}", max_length=200),
        "title": _clean_text(value.get("title"), "", max_length=240),
        "tasks": tasks,
    }


def _normalize_task(value: Any, section_index: int, task_index: int) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    title = _clean_text(value.get("title") or value.get("text"), "", max_length=500)
    return {
        "id": _clean_text(value.get("id"), f"task-{section_index + 1}-{task_index + 1}", max_length=200),
        "title": title,
        "checked": bool(value.get("checked") if "checked" in value else value.get("done")),
    }


def _with_counts(checklist: dict[str, Any]) -> dict[str, Any]:
    tasks = [task for section in checklist.get("sections", []) for task in section.get("tasks", [])]
    checklist["task_count"] = len(tasks)
    checklist["checked_count"] = sum(1 for task in tasks if task.get("checked"))
    return checklist


def _normalize_view_state(value: Any) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    mode = str(payload.get("mode") or "default").strip().lower()
    if mode not in {"default", "custom"}:
        mode = "default"
    return {
        "mode": mode,
        "query": _clean_text(payload.get("query"), "", max_length=240),
        "title": _clean_text(payload.get("title"), "", max_length=240),
        "refs": _normalize_custom_view_refs(payload.get("refs")),
    }


def _normalize_custom_view_refs(value: Any) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        app_id = _clean_text(item.get("app_id"), "", max_length=120)
        entity_type = _clean_text(item.get("entity_type"), "", max_length=120)
        entity_id = _clean_text(item.get("entity_id"), "", max_length=200)
        if app_id != "checklist" or entity_type != REFERENCE_ENTITY_TYPE or not entity_id:
            continue
        refs.append(
            {
                "app_id": app_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
            }
        )
    if isinstance(value, list) and value and not refs:
        raise ValueError("Custom view refs must target checklist-owned checklist entities.")
    return refs


def _apply_view_state(items: list[dict[str, Any]], view_state: dict[str, Any]) -> list[dict[str, Any]]:
    refs = {
        str(item.get("entity_id") or "")
        for item in (view_state.get("refs") if isinstance(view_state.get("refs"), list) else [])
        if isinstance(item, dict)
    }
    query = str(view_state.get("query") or "").strip().lower()
    filtered = list(items)
    if refs:
        filtered = [item for item in filtered if str(item.get("id") or "") in refs]
    if query:
        filtered = [item for item in filtered if _matches_query(item, query)]
    return filtered


def _matches_query(checklist: dict[str, Any], query: str) -> bool:
    haystacks = [
        str(checklist.get("title") or ""),
        str(checklist.get("summary") or ""),
    ]
    haystacks.extend(
        str(task.get("title") or "")
        for section in checklist.get("sections", [])
        for task in section.get("tasks", [])
    )
    return any(query in text.lower() for text in haystacks)


def _reference_record(checklist: dict[str, Any]) -> dict[str, Any]:
    resolved = _with_counts(deepcopy(checklist))
    return {
        "app_id": "checklist",
        "entity_type": REFERENCE_ENTITY_TYPE,
        "entity_id": resolved["id"],
        "title": resolved["title"],
        "summary": resolved["summary"],
        "metadata": {
            "checked_count": resolved["checked_count"],
            "task_count": resolved["task_count"],
            "updated_at": resolved.get("updated_at"),
        },
    }


def _metadata(*, title: str, summary: str, sections: list[dict[str, Any]], metadata: Any) -> dict[str, Any]:
    tasks = [task for section in sections for task in section.get("tasks", [])]
    return {
        **(dict(metadata) if isinstance(metadata, dict) else {}),
        "checkedCount": sum(1 for task in tasks if task.get("checked")),
        "sections": deepcopy(sections),
        "summary": summary,
        "title": title,
        "viewer": "design_checklist_mcp_v1",
    }


def _summary_for(sections: list[dict[str, Any]], requested: str) -> str:
    if requested.strip() and not _is_progress_summary(requested):
        return requested.strip()
    tasks = [task for section in sections for task in section.get("tasks", [])]
    checked = sum(1 for task in tasks if task.get("checked"))
    return f"{checked}/{len(tasks)} checked"


def _is_progress_summary(value: str) -> bool:
    parts = value.strip().lower().split()
    return len(parts) == 2 and parts[1] == "checked" and "/" in parts[0]


def _clean_text(value: Any, default: str, *, max_length: int) -> str:
    text = str(value if value is not None else "").strip()
    return (text or default)[:max_length]


def _optional_text(value: Any, *, max_length: int) -> str | None:
    text = str(value if value is not None else "").strip()
    return text[:max_length] if text else None


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"
