"""Deterministic structural comparison for immutable Project IR revisions."""

from __future__ import annotations

from typing import Any

from project_ir.canonical import canonical_copy


def compare_values(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            child_path = f"{path}/{_escape(key)}"
            if key not in before:
                changes.append({"change": "added", "path": child_path, "after": canonical_copy(after[key])})
            elif key not in after:
                changes.append({"change": "removed", "path": child_path, "before": canonical_copy(before[key])})
            else:
                changes.extend(compare_values(before[key], after[key], child_path))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        changes = []
        for index in range(max(len(before), len(after))):
            child_path = f"{path}/{index}"
            if index >= len(before):
                changes.append({"change": "added", "path": child_path, "after": canonical_copy(after[index])})
            elif index >= len(after):
                changes.append({"change": "removed", "path": child_path, "before": canonical_copy(before[index])})
            else:
                changes.extend(compare_values(before[index], after[index], child_path))
        return changes
    return [
        {
            "change": "replaced",
            "path": path or "",
            "before": canonical_copy(before),
            "after": canonical_copy(after),
        }
    ]


def _escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")
