"""Descriptor-confined overlay storage and diff scanning for hosted commands."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import stat
from uuid import uuid4

from core.runtime.confined_filesystem import ConfinedWorkspaceFilesystem
from core.runtime.confined_filesystem_metadata import (
    ConfinedPathMetadata,
    capture_fd_metadata,
)
from core.runtime.tool_errors import RuntimeToolError


MAX_HOSTED_EFFECT_FILES = 128
MAX_HOSTED_EFFECT_ENTRIES = 1_024
MAX_HOSTED_EFFECT_FILE_BYTES = 1_048_576
MAX_HOSTED_EFFECT_TOTAL_BYTES = 4_194_304
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_ROOT_ATIME_SENTINEL_OFFSET_NS = 86_400_000_000_000
_OVERLAY_INFRASTRUCTURE_XATTRS = {
    f"{namespace}.{name}"
    for namespace in ("trusted.overlay", "user.overlay")
    for name in ("impure", "origin", "uuid")
}


@dataclass
class _OverlayScanState:
    changes: list["HostedEffectFile"] = field(default_factory=list)
    directories: list["HostedEffectDirectory"] = field(default_factory=list)
    entry_count: int = 0
    total_bytes: int = 0


@dataclass(frozen=True)
class HostedEffectFile:
    path: str
    content: bytes
    metadata: ConfinedPathMetadata


@dataclass(frozen=True)
class HostedEffectDirectory:
    path: str
    metadata: ConfinedPathMetadata


@dataclass(frozen=True)
class HostedEffectOverlayDiff:
    """Complete representable upper-layer entries."""

    root_metadata: ConfinedPathMetadata
    files: tuple[HostedEffectFile, ...]
    directories: tuple[HostedEffectDirectory, ...]


def create_hosted_effect_overlay_directories(
    filesystem: ConfinedWorkspaceFilesystem,
    *,
    runtime_root: Path,
) -> tuple[Path, Path, Path, ConfinedPathMetadata]:
    """Create the private overlay upper/work directories below platform runtime."""
    runtime_fd = filesystem.open_platform_runtime_fd(runtime_root)
    parent_fd: int | None = None
    effect_fd: int | None = None
    upper_fd: int | None = None
    upper_metadata: ConfinedPathMetadata | None = None
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
        os.mkdir("transaction", 0o700, dir_fd=effect_fd)
        upper_fd = os.open(
            "upper",
            os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
            dir_fd=effect_fd,
        )
        # The upper root doubles as a metadata sentinel for mutations to `.`.
        # Its parent remains private even when the workspace root is 0755.
        os.fchmod(upper_fd, filesystem.path_mode(".", directory=True))
        upper_stat = os.fstat(upper_fd)
        # Keep ordinary relatime traversal from changing the sentinel. Any
        # command-owned root atime mutation then remains distinguishable.
        os.utime(
            upper_fd,
            ns=(
                max(
                    upper_stat.st_atime_ns,
                    upper_stat.st_mtime_ns,
                    upper_stat.st_ctime_ns,
                )
                + _ROOT_ATIME_SENTINEL_OFFSET_NS,
                upper_stat.st_mtime_ns,
            ),
        )
        upper_metadata = capture_fd_metadata(
            upper_fd,
            unavailable_reason="workspace_effect_metadata_unavailable",
        )
    except OSError as error:
        raise RuntimeToolError("workspace_effect_overlay_unavailable") from error
    finally:
        if upper_fd is not None:
            os.close(upper_fd)
        if effect_fd is not None:
            os.close(effect_fd)
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(runtime_fd)
    root = runtime_root / "agent-workspace-effects" / name
    if upper_metadata is None:
        raise RuntimeToolError("workspace_effect_overlay_unavailable")
    return root, root / "upper", root / "work", upper_metadata


def scan_hosted_effect_overlay_upper(upper: Path) -> HostedEffectOverlayDiff:
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
        root_metadata = _overlay_metadata(root_fd)
        _scan_upper_directory(root_fd, (), state)
    finally:
        os.close(root_fd)
    state.changes.sort(key=lambda item: item.path)
    state.directories.sort(key=lambda item: item.path)
    return HostedEffectOverlayDiff(
        root_metadata=root_metadata,
        files=tuple(state.changes),
        directories=tuple(state.directories),
    )


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
                    metadata = _overlay_metadata(child_fd)
                    state.directories.append(
                        HostedEffectDirectory(path, metadata)
                    )
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
                metadata = _overlay_metadata(fd)
                if item.st_size > MAX_HOSTED_EFFECT_FILE_BYTES:
                    raise RuntimeToolError("workspace_effect_file_too_large")
                if state.total_bytes + item.st_size > MAX_HOSTED_EFFECT_TOTAL_BYTES:
                    raise RuntimeToolError("workspace_effect_total_too_large")
                content = os.pread(fd, item.st_size + 1, 0)
                after = os.fstat(fd)
                if not _same_scanned_version(item, after) or len(content) != item.st_size:
                    raise RuntimeToolError("workspace_effect_diff_changed")
                state.changes.append(
                    HostedEffectFile(
                        path,
                        content,
                        metadata,
                    )
                )
                state.total_bytes += len(content)
            finally:
                os.close(fd)


def _overlay_metadata(fd: int) -> ConfinedPathMetadata:
    try:
        metadata = capture_fd_metadata(
            fd,
            unavailable_reason="workspace_effect_metadata_unavailable",
        )
    except RuntimeToolError as error:
        if error.reason_code == "filesystem_resource_changed":
            raise RuntimeToolError("workspace_effect_diff_changed") from error
        raise
    retained: list[tuple[str, bytes]] = []
    for name, value in metadata.xattrs:
        if name in _OVERLAY_INFRASTRUCTURE_XATTRS:
            continue
        if name.startswith(("trusted.overlay.", "user.overlay.")):
            raise RuntimeToolError("workspace_effect_type_unsupported")
        retained.append((name, value))
    return ConfinedPathMetadata(
        device=metadata.device,
        inode=metadata.inode,
        file_type=metadata.file_type,
        mode=metadata.mode,
        uid=metadata.uid,
        gid=metadata.gid,
        link_count=metadata.link_count,
        size_bytes=metadata.size_bytes,
        atime_ns=metadata.atime_ns,
        mtime_ns=metadata.mtime_ns,
        ctime_ns=metadata.ctime_ns,
        xattrs=tuple(retained),
    )


def _same_scanned_version(left: os.stat_result, right: os.stat_result) -> bool:
    return all(
        getattr(left, field) == getattr(right, field)
        for field in (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
    )


__all__ = [
    "MAX_HOSTED_EFFECT_FILES",
    "MAX_HOSTED_EFFECT_FILE_BYTES",
    "MAX_HOSTED_EFFECT_TOTAL_BYTES",
    "HostedEffectDirectory",
    "HostedEffectFile",
    "HostedEffectOverlayDiff",
    "create_hosted_effect_overlay_directories",
    "scan_hosted_effect_overlay_upper",
]
