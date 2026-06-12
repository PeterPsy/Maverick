"""Persisted Mail view state helpers."""

from __future__ import annotations

import json
from pathlib import Path

from database import now_timestamp


def load_view_state(data_root: Path) -> dict[str, object]:
    path = data_root / "view_state.json"
    if not path.exists():
        return {"schema_version": "1", "view_filter": _default_view_filter()}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raw = {}
    view_filter = raw.get("view_filter") if isinstance(raw, dict) else None
    return {"schema_version": "1", "view_filter": view_filter if isinstance(view_filter, dict) else _default_view_filter()}


def set_view_filter(data_root: Path, query: object = None, mailbox: object = None, preserve_custom: bool = False) -> dict[str, object]:
    current = load_view_state(data_root)
    current_filter = current.get("view_filter") if isinstance(current.get("view_filter"), dict) else {}
    next_filter = dict(current_filter) if preserve_custom and current_filter.get("mode") == "custom" else _default_view_filter()
    next_filter["query"] = str(query or "").strip()
    next_filter["mailbox"] = str(mailbox or "inbox").strip() or "inbox"
    next_filter["updated_at"] = now_timestamp()
    return _write_view_state(data_root, next_filter)


def set_custom_view(data_root: Path, title: object = None, refs: object = None) -> dict[str, object]:
    view_filter = _default_view_filter()
    view_filter.update({"mode": "custom", "title": str(title or "Custom mail view").strip(), "refs": refs if isinstance(refs, list) else [], "updated_at": now_timestamp()})
    return _write_view_state(data_root, view_filter)


def clear_custom_view(data_root: Path) -> dict[str, object]:
    view_filter = _default_view_filter()
    view_filter["updated_at"] = now_timestamp()
    return _write_view_state(data_root, view_filter)


def _default_view_filter() -> dict[str, object]:
    return {"mode": "search", "query": "", "mailbox": "inbox", "refs": [], "updated_at": None}


def _write_view_state(data_root: Path, view_filter: dict[str, object]) -> dict[str, object]:
    data_root.mkdir(parents=True, exist_ok=True)
    state = {"schema_version": "1", "view_filter": view_filter}
    (data_root / "view_state.json").write_text(json.dumps(state, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return state
