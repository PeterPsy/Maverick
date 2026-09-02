"""Descriptor-confined discovery of Git metadata hidden from hosted commands."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import stat
from typing import Literal

from core.runtime.confined_filesystem import MAX_CONFINED_PATH_COMPONENTS
from core.runtime.tool_errors import RuntimeToolError


_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
MAX_HOSTED_GIT_METADATA_ENTRIES = 1_024
MAX_HOSTED_GIT_SCAN_DIRECTORIES = 50_000
MAX_HOSTED_GIT_SCAN_ENTRIES = 250_000


@dataclass(frozen=True)
class HostedWorkspaceGitMetadata:
    """One exact workspace-relative Git metadata mount target."""

    path: str
    kind: Literal["directory", "file"]


@dataclass
class _ScanState:
    directories: int = 0
    entries: int = 0
    metadata: list[HostedWorkspaceGitMetadata] = field(default_factory=list)


def scan_hosted_workspace_git_metadata(
    root_fd: int,
) -> tuple[HostedWorkspaceGitMetadata, ...]:
    """Find every `.git` without following workspace-controlled symlinks."""
    state = _ScanState()
    duplicate = os.dup(root_fd)
    try:
        _scan_directory(duplicate, (), state)
    finally:
        os.close(duplicate)
    return tuple(
        sorted(
            state.metadata,
            key=lambda item: (item.path.count("/"), item.path),
        )
    )


def _scan_directory(
    directory_fd: int,
    components: tuple[str, ...],
    state: _ScanState,
) -> None:
    before = os.fstat(directory_fd)
    try:
        names: list[str] = []
        with os.scandir(directory_fd) as iterator:
            for entry in iterator:
                state.entries += 1
                if state.entries > MAX_HOSTED_GIT_SCAN_ENTRIES:
                    raise RuntimeToolError(
                        "workspace_shell_git_metadata_scan_too_large"
                    )
                names.append(entry.name)
        names.sort()
    except (OSError, UnicodeError) as error:
        raise RuntimeToolError("workspace_shell_git_metadata_scan_failed") from error
    for name in names:
        try:
            name.encode("utf-8", errors="strict")
            observed = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except UnicodeError as error:
            raise RuntimeToolError("workspace_shell_git_metadata_unsafe") from error
        except OSError as error:
            raise RuntimeToolError("workspace_shell_git_metadata_changed") from error
        path_components = (*components, name)
        if name == ".git":
            _record_git_metadata(path_components, observed, state)
            continue
        if not components and name == "runtime":
            # The platform runtime subtree is replaced by an empty tmpfs.
            continue
        if not stat.S_ISDIR(observed.st_mode):
            continue
        if len(path_components) >= MAX_CONFINED_PATH_COMPONENTS:
            raise RuntimeToolError("workspace_shell_git_metadata_scan_too_large")
        state.directories += 1
        if state.directories > MAX_HOSTED_GIT_SCAN_DIRECTORIES:
            raise RuntimeToolError("workspace_shell_git_metadata_scan_too_large")
        try:
            child_fd = os.open(
                name,
                os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
                dir_fd=directory_fd,
            )
        except OSError as error:
            raise RuntimeToolError("workspace_shell_git_metadata_changed") from error
        try:
            if not _same_entry(observed, os.fstat(child_fd)):
                raise RuntimeToolError("workspace_shell_git_metadata_changed")
            _scan_directory(child_fd, path_components, state)
        finally:
            os.close(child_fd)
    if not _same_directory_version(before, os.fstat(directory_fd)):
        raise RuntimeToolError("workspace_shell_git_metadata_changed")


def _record_git_metadata(
    components: tuple[str, ...],
    observed: os.stat_result,
    state: _ScanState,
) -> None:
    if stat.S_ISDIR(observed.st_mode):
        kind: Literal["directory", "file"] = "directory"
    elif stat.S_ISREG(observed.st_mode):
        kind = "file"
    else:
        raise RuntimeToolError("workspace_shell_git_metadata_unsafe")
    if len(state.metadata) >= MAX_HOSTED_GIT_METADATA_ENTRIES:
        raise RuntimeToolError("workspace_shell_git_metadata_scan_too_large")
    state.metadata.append(HostedWorkspaceGitMetadata("/".join(components), kind))


def _same_entry(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev,
        before.st_ino,
        before.st_mode,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_mode,
    )


def _same_directory_version(before: os.stat_result, after: os.stat_result) -> bool:
    return _same_entry(before, after) and (
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) == (
        after.st_mtime_ns,
        after.st_ctime_ns,
    )


__all__ = [
    "HostedWorkspaceGitMetadata",
    "MAX_HOSTED_GIT_METADATA_ENTRIES",
    "MAX_HOSTED_GIT_SCAN_DIRECTORIES",
    "MAX_HOSTED_GIT_SCAN_ENTRIES",
    "scan_hosted_workspace_git_metadata",
]
