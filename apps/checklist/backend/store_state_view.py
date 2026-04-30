"""App-owned JSON store for the Checklist workspace app."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4



STATE_FILE = "state.json"
CHECKLIST_KIND = "checklist.design"
REFERENCE_ENTITY_TYPE = "checklist"
WIDGET_CONTENT_KIND = "checklist.design"


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
        "viewer": "checklist_design_v1",
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



def _required_workspace_id(value: Any) -> str:
    workspace_id = _optional_text(value, max_length=120)
    if not workspace_id:
        raise ValueError("workspace_id is required.")
    return workspace_id



def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"
