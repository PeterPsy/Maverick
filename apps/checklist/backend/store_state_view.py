"""App-owned JSON store for the Checklist workspace app."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4



STATE_FILE = "state.json"
SCHEMA_VERSION = "4"
CHECKLIST_KIND = "checklist.design"
REFERENCE_ENTITY_TYPE = "checklist"
WIDGET_CONTENT_KIND = "checklist.design"
TASK_STATUSES = {"pending", "in-progress", "need-help", "blocked", "completed", "failed"}
CHECKLIST_STATUSES = {"active", "in-progress", "blocked", "completed", "failed"}
PRIORITIES = {"low", "medium", "high", "critical"}


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
        str(checklist.get("id") or ""),
        "checklist checklists",
        f"checklists/{checklist.get('id') or ''}",
        f"/app/checklist/checklists/{checklist.get('id') or ''}",
    ]
    haystacks.extend(str(section.get("title") or "") for section in checklist.get("sections", []))
    haystacks.extend(
        str(task.get("title") or "")
        for section in checklist.get("sections", [])
        for task in section.get("tasks", [])
    )
    haystack = " ".join(text.lower() for text in haystacks)
    if query in haystack:
        return True
    return all(any(variant in haystack for variant in _query_token_variants(token)) for token in _query_tokens(query))


def _query_tokens(query: str) -> list[str]:
    return [token for token in query.split() if token]


def _query_token_variants(token: str) -> set[str]:
    variants = {token}
    if len(token) > 4 and token.endswith("s"):
        variants.add(token[:-1])
    return variants


def _reference_record(checklist: dict[str, Any]) -> dict[str, Any]:
    resolved = _with_counts(deepcopy(checklist))
    return {
        "app_id": "checklist",
        "entity_type": REFERENCE_ENTITY_TYPE,
        "entity_id": resolved["id"],
        "title": resolved["title"],
        "summary": resolved["summary"],
        "app_page": f"checklists/{resolved['id']}",
        "deep_link": f"/app/checklist/checklists/{resolved['id']}",
        "metadata": {
            "checked_count": resolved["checked_count"],
            "task_count": resolved["task_count"],
            "updated_at": resolved.get("updated_at"),
        },
    }



def _metadata(*, title: str, summary: str, sections: list[dict[str, Any]], metadata: Any) -> dict[str, Any]:
    tasks = [
        item
        for section in sections
        for task in section.get("tasks", [])
        for item in [task, *task.get("subtasks", [])]
    ]
    return {
        **(dict(metadata) if isinstance(metadata, dict) else {}),
        "checkedCount": sum(1 for task in tasks if task.get("checked") or task.get("status") == "completed"),
        "blockedCount": sum(1 for task in tasks if task.get("status") in {"blocked", "need-help"}),
        "sections": deepcopy(sections),
        "summary": summary,
        "title": title,
        "viewer": "checklist_agent_plan_v1",
    }



def _summary_for(sections: list[dict[str, Any]], requested: str) -> str:
    if requested.strip() and not _is_progress_summary(requested):
        return requested.strip()
    tasks = [
        item
        for section in sections
        for task in section.get("tasks", [])
        for item in [task, *task.get("subtasks", [])]
    ]
    checked = sum(1 for task in tasks if task.get("checked") or task.get("status") == "completed")
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



def _mode(value: Any) -> str:
    mode = str(value if value is not None else "").strip().lower().replace("-", "_")
    return mode if mode in {"simple", "agent_plan", "execution"} else "simple"



def _priority(value: Any) -> str:
    priority = str(value if value is not None else "").strip().lower()
    return priority if priority in PRIORITIES else "medium"



def _status(value: Any, *, default: str, allowed: set[str]) -> str:
    status = str(value if value is not None else "").strip().lower().replace("_", "-")
    return status if status in allowed else default



def _task_status(value: Any, *, checked: Any = None) -> str:
    status = _status(value, default="", allowed=TASK_STATUSES)
    if status:
        return status
    return "completed" if bool(checked) else "pending"



def _level(value: Any) -> int:
    try:
        return max(0, min(12, int(value)))
    except (TypeError, ValueError):
        return 0



def _string_list(value: Any, *, max_items: int, max_length: int) -> list[str]:
    items: list[str] = []
    for item in value if isinstance(value, list) else []:
        text = str(item if item is not None else "").strip()
        if text:
            items.append(text[:max_length])
        if len(items) >= max_items:
            break
    return items
