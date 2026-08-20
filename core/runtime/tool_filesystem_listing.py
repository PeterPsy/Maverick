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
    """List metadata using descriptor-relative traversal that never follows symlinks."""
    entries: list[dict[str, str]] = []
    scanned_entries = 0
    truncated = False
    try:
        relative_directory = directory.relative_to(root)
    except ValueError as error:
        raise RuntimeToolError("filesystem_path_outside_workspace") from error

    def visit(current_fd: int, relative_parts: tuple[str, ...], depth: int) -> None:
        nonlocal scanned_entries, truncated
        if truncated:
            return
        try:
            with os.scandir(current_fd) as iterator:
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
            child_parts = (*relative_parts, child.name)
            relative = Path(*child_parts).as_posix()
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
                child_fd = _open_directory(child.name, dir_fd=current_fd)
                try:
                    visit(child_fd, child_parts, depth + 1)
                    if truncated:
                        return
                finally:
                    os.close(child_fd)

    root_fd = _open_directory(root)
    try:
        directory_fd = _open_relative_directory(
            root_fd,
            tuple(relative_directory.parts),
        )
        try:
            visit(directory_fd, tuple(relative_directory.parts), 1)
        finally:
            os.close(directory_fd)
    finally:
        os.close(root_fd)
    return entries, truncated


def _open_relative_directory(root_fd: int, parts: tuple[str, ...]) -> int:
    """Open every already-confined component relative to its verified parent."""
    try:
        current_fd = os.dup(root_fd)
    except OSError as error:
        raise RuntimeToolError("filesystem_list_failed") from error
    try:
        for part in parts:
            next_fd = _open_directory(part, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _open_directory(path: str | Path, *, dir_fd: int | None = None) -> int:
    """Open one directory without resolving the final component as a symlink."""
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory is None:
        raise RuntimeToolError("filesystem_list_unsupported")
    flags = os.O_RDONLY | no_follow | directory | getattr(os, "O_CLOEXEC", 0)
    try:
        return os.open(path, flags, dir_fd=dir_fd)
    except OSError as error:
        raise RuntimeToolError("filesystem_list_failed") from error


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
