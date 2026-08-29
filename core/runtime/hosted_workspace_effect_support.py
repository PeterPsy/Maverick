"""Descriptor-confined overlay storage and diff scanning for hosted commands."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import stat
from uuid import uuid4

from core.runtime.confined_filesystem import ConfinedWorkspaceFilesystem
from core.runtime.tool_errors import RuntimeToolError


MAX_HOSTED_EFFECT_FILES = 128
MAX_HOSTED_EFFECT_ENTRIES = 1_024
MAX_HOSTED_EFFECT_FILE_BYTES = 1_048_576
MAX_HOSTED_EFFECT_TOTAL_BYTES = 4_194_304
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


@dataclass
class _OverlayScanState:
    changes: list[tuple[str, bytes]] = field(default_factory=list)
    entry_count: int = 0
    total_bytes: int = 0


def create_hosted_effect_overlay_directories(
    filesystem: ConfinedWorkspaceFilesystem,
    *,
    runtime_root: Path,
) -> tuple[Path, Path, Path]:
    """Create the private overlay upper/work directories below platform runtime."""
    runtime_fd = filesystem.open_platform_runtime_fd(runtime_root)
    parent_fd: int | None = None
    effect_fd: int | None = None
    name = f"effect-{uuid4().hex}"
    try:
        try:
            os.mkdir("agent-workspace-effects", 0o700, dir_fd=runtime_fd)
        except FileExistsError:
            pass
        parent_fd = os.open(
            "agent-workspace-effects",
            os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
            dir_fd=runtime_fd,
        )
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        effect_fd = os.open(
            name,
            os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
            dir_fd=parent_fd,
        )
        os.mkdir("upper", 0o700, dir_fd=effect_fd)
        os.mkdir("work", 0o700, dir_fd=effect_fd)
    except OSError as error:
        raise RuntimeToolError("workspace_effect_overlay_unavailable") from error
    finally:
        if effect_fd is not None:
            os.close(effect_fd)
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(runtime_fd)
    root = runtime_root / "agent-workspace-effects" / name
    return root, root / "upper", root / "work"


def scan_hosted_effect_overlay_upper(upper: Path) -> tuple[tuple[str, bytes], ...]:
    """Return a stable regular-file diff and reject opaque or special effects."""
    try:
        root_fd = os.open(
            upper,
            os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
        )
    except OSError as error:
        raise RuntimeToolError("workspace_effect_diff_unavailable") from error
    state = _OverlayScanState()
    try:
        _reject_overlay_metadata(root_fd)
        _scan_upper_directory(root_fd, (), state)
    finally:
        os.close(root_fd)
    state.changes.sort(key=lambda item: item[0])
    return tuple(state.changes)


def _scan_upper_directory(
    directory_fd: int,
    components: tuple[str, ...],
    state: _OverlayScanState,
) -> None:
    try:
        iterator = os.scandir(directory_fd)
    except OSError as error:
        raise RuntimeToolError("workspace_effect_diff_unavailable") from error
    with iterator:
        for entry in iterator:
            state.entry_count += 1
            if state.entry_count > MAX_HOSTED_EFFECT_ENTRIES:
                raise RuntimeToolError("workspace_effect_entry_limit_exceeded")
            name = entry.name
            path_components = (*components, name)
            path = "/".join(path_components)
            if name in {"", ".", ".."} or (
                not components and name in {".git", "runtime"}
            ):
                raise RuntimeToolError("workspace_effect_outside_declared_scope")
            try:
                item = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as error:
                raise RuntimeToolError("workspace_effect_diff_changed") from error
            if stat.S_ISDIR(item.st_mode):
                child_fd = os.open(
                    name,
                    os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
                    dir_fd=directory_fd,
                )
                try:
                    _reject_overlay_metadata(child_fd)
                    _scan_upper_directory(child_fd, path_components, state)
                finally:
                    os.close(child_fd)
                continue
            if not stat.S_ISREG(item.st_mode):
                raise RuntimeToolError("workspace_effect_type_unsupported")
            if len(state.changes) >= MAX_HOSTED_EFFECT_FILES:
                raise RuntimeToolError("workspace_effect_file_limit_exceeded")
            fd = os.open(
                name,
                os.O_RDONLY | _NOFOLLOW | _CLOEXEC,
                dir_fd=directory_fd,
            )
            try:
                _reject_overlay_metadata(fd)
                if item.st_size > MAX_HOSTED_EFFECT_FILE_BYTES:
                    raise RuntimeToolError("workspace_effect_file_too_large")
                if state.total_bytes + item.st_size > MAX_HOSTED_EFFECT_TOTAL_BYTES:
                    raise RuntimeToolError("workspace_effect_total_too_large")
                content = os.pread(fd, item.st_size + 1, 0)
                after = os.fstat(fd)
                if (
                    after.st_dev != item.st_dev
                    or after.st_ino != item.st_ino
                    or after.st_size != item.st_size
                    or len(content) != item.st_size
                ):
                    raise RuntimeToolError("workspace_effect_diff_changed")
                state.changes.append((path, content))
                state.total_bytes += len(content)
            finally:
                os.close(fd)


def _reject_overlay_metadata(fd: int) -> None:
    try:
        names = os.listxattr(fd)
    except OSError as error:
        raise RuntimeToolError("workspace_effect_metadata_unavailable") from error
    if any(name.endswith((".opaque", ".redirect", ".metacopy")) for name in names):
        raise RuntimeToolError("workspace_effect_type_unsupported")


__all__ = [
    "MAX_HOSTED_EFFECT_FILES",
    "MAX_HOSTED_EFFECT_FILE_BYTES",
    "MAX_HOSTED_EFFECT_TOTAL_BYTES",
    "create_hosted_effect_overlay_directories",
    "scan_hosted_effect_overlay_upper",
]
