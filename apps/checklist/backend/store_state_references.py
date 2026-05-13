"""App-owned JSON store for the Checklist workspace app."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any



STATE_FILE = "state.json"
SCHEMA_VERSION = "4"
CHECKLIST_KIND = "checklist.design"
REFERENCE_ENTITY_TYPE = "checklist"
WIDGET_CONTENT_KIND = "checklist.design"
TASK_STATUSES = {"pending", "in-progress", "need-help", "blocked", "completed", "failed"}
CHECKLIST_STATUSES = {"active", "in-progress", "blocked", "completed", "failed"}
PRIORITIES = {"low", "medium", "high", "critical"}


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
    """Return a structured MCP/CLI payload for the checklist tasklist tool."""
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
            "workspace_id": _clean_text(value.get("workspace_id"), "legacy-unknown", max_length=120),
            "profile": _optional_text(value.get("profile"), max_length=120),
            "mode": _mode(value.get("mode")),
            "kind": CHECKLIST_KIND,
            "title": title,
            "summary": summary,
            "sections": sections,
            "source_type": _clean_text(value.get("source_type"), "chat_preview", max_length=80),
            "source_ref": _clean_text(value.get("source_ref"), "", max_length=240),
            "status": _status(value.get("status"), default="active", allowed=CHECKLIST_STATUSES),
            "priority": _priority(value.get("priority")),
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
    status = _task_status(value.get("status"), checked=value.get("checked") if "checked" in value else value.get("done"))
    return {
        "id": _clean_text(value.get("id"), f"task-{section_index + 1}-{task_index + 1}", max_length=200),
        "title": title,
        "description": _clean_text(value.get("description"), "", max_length=1200),
        "status": status,
        "checked": status == "completed",
        "priority": _priority(value.get("priority")),
        "level": _level(value.get("level")),
        "dependencies": _string_list(value.get("dependencies"), max_items=24, max_length=200),
        "tools": _string_list(value.get("tools"), max_items=24, max_length=120),
        "subtasks": _normalize_subtasks(value.get("subtasks"), section_index, task_index),
        "blocked_reason": _clean_text(value.get("blocked_reason"), "", max_length=500),
        "agent_ref": _clean_text(value.get("agent_ref"), "", max_length=240),
        "source_ref": _clean_text(value.get("source_ref"), "", max_length=240),
        "agent_dialogs": _dialog_refs(value.get("agent_dialogs") or value.get("dialogs")),
    }



def _normalize_subtasks(value: Any, section_index: int, task_index: int) -> list[dict[str, Any]]:
    raw_subtasks = value if isinstance(value, list) else []
    return [
        subtask
        for subtask_index, raw_subtask in enumerate(raw_subtasks)
        if (subtask := _normalize_subtask(raw_subtask, section_index, task_index, subtask_index)) is not None
    ]



def _normalize_subtask(value: Any, section_index: int, task_index: int, subtask_index: int) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    title = _clean_text(value.get("title") or value.get("text"), "", max_length=500)
    status = _task_status(value.get("status"), checked=value.get("checked") if "checked" in value else value.get("done"))
    return {
        "id": _clean_text(value.get("id"), f"subtask-{section_index + 1}-{task_index + 1}-{subtask_index + 1}", max_length=200),
        "title": title,
        "description": _clean_text(value.get("description"), "", max_length=1200),
        "status": status,
        "checked": status == "completed",
        "priority": _priority(value.get("priority")),
        "tools": _string_list(value.get("tools"), max_items=24, max_length=120),
        "blocked_reason": _clean_text(value.get("blocked_reason"), "", max_length=500),
        "agent_ref": _clean_text(value.get("agent_ref"), "", max_length=240),
        "source_ref": _clean_text(value.get("source_ref"), "", max_length=240),
        "agent_dialogs": _dialog_refs(value.get("agent_dialogs") or value.get("dialogs")),
    }



def _dialog_refs(value: Any) -> list[dict[str, str]]:
    raw_items = value if isinstance(value, list) else []
    refs: list[dict[str, str]] = []
    for index, item in enumerate(raw_items[:12]):
        if isinstance(item, str):
            ref = _clean_text(item, "", max_length=240)
            if ref:
                refs.append({"id": f"dialog-{index + 1}", "title": ref, "summary": "", "ref": ref, "agent_ref": ""})
            continue
        if not isinstance(item, dict):
            continue
        ref = _clean_text(item.get("ref") or item.get("source_ref") or item.get("id"), "", max_length=240)
        title = _clean_text(item.get("title"), ref or f"Agent dialog {index + 1}", max_length=180)
        if not ref and not title:
            continue
        refs.append(
            {
                "id": _clean_text(item.get("id"), f"dialog-{index + 1}", max_length=120),
                "title": title,
                "summary": _clean_text(item.get("summary") or item.get("description"), "", max_length=500),
                "ref": ref,
                "agent_ref": _clean_text(item.get("agent_ref"), "", max_length=240),
            }
        )
    return refs



def _with_counts(checklist: dict[str, Any]) -> dict[str, Any]:
    tasks = _all_tasks(checklist)
    checklist["task_count"] = len(tasks)
    checklist["checked_count"] = sum(1 for task in tasks if task.get("checked") or task.get("status") == "completed")
    checklist["blocked_count"] = sum(1 for task in tasks if task.get("status") in {"blocked", "need-help"})
    checklist["failed_count"] = sum(1 for task in tasks if task.get("status") == "failed")
    return checklist



def _all_tasks(checklist: dict[str, Any]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for section in checklist.get("sections", []):
        for task in section.get("tasks", []):
            tasks.append(task)
            tasks.extend(task.get("subtasks", []))
    return tasks



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
