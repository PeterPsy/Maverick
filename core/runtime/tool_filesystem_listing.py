"""Bounded, content-free workspace filesystem listing."""

from __future__ import annotations

import os
from pathlib import Path

from core.runtime.tool_errors import RuntimeToolError


MAX_FILESYSTEM_LIST_DEPTH = 4
MAX_FILESYSTEM_LIST_RESULTS = 500
MAX_FILESYSTEM_LIST_SCANNED_ENTRIES = 10_000


def list_workspace_entries(
    root: Path,
    directory: Path,
    *,
    max_depth: int,
    max_results: int,
) -> tuple[list[dict[str, str]], bool]:
    """List relative metadata deterministically without following symlinks."""
    entries: list[dict[str, str]] = []
    scanned_entries = 0
    truncated = False

    def visit(current: Path, depth: int) -> None:
        nonlocal scanned_entries, truncated
        if truncated:
            return
        try:
            with os.scandir(current) as iterator:
                children = []
                for child in iterator:
                    scanned_entries += 1
                    if scanned_entries > MAX_FILESYSTEM_LIST_SCANNED_ENTRIES:
                        raise RuntimeToolError("filesystem_list_too_large")
                    children.append(child)
        except RuntimeToolError:
            raise
        except OSError as error:
            raise RuntimeToolError("filesystem_list_failed") from error
        for child in sorted(children, key=lambda item: item.name):
            if len(entries) >= max_results:
                truncated = True
                return
            child_path = Path(child.path)
            relative = child_path.relative_to(root).as_posix()
            try:
                if child.is_symlink():
                    entry_type = "symlink"
                elif child.is_dir(follow_symlinks=False):
                    entry_type = "directory"
                elif child.is_file(follow_symlinks=False):
                    entry_type = "file"
                else:
                    entry_type = "other"
            except OSError as error:
                raise RuntimeToolError("filesystem_list_failed") from error
            entries.append({"path": relative, "type": entry_type})
            if entry_type == "directory" and depth < max_depth:
                visit(child_path, depth + 1)
                if truncated:
                    return

    visit(directory, 1)
    return entries, truncated


def filesystem_list_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1, "maxLength": 4096},
            "max_depth": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_FILESYSTEM_LIST_DEPTH,
            },
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_FILESYSTEM_LIST_RESULTS,
            },
        },
        "additionalProperties": False,
    }
