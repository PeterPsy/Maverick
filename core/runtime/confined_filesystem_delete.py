"""Quarantined version-fenced deletion for the confined filesystem."""

from __future__ import annotations

import os
import secrets
import stat

from core.runtime.confined_filesystem import (
    ConfinedFilesystemResult,
    ConfinedWorkspaceFilesystem,
)
from core.runtime.confined_filesystem_mutation_support import (
    lstat_entry,
    rename_noreplace,
    require_absent,
    require_supported_type,
    resource_kind,
    revalidate_entry,
    rollback_move,
    same_identity,
)
from core.runtime.tool_errors import RuntimeToolError


MAX_RECURSIVE_DELETE_ENTRIES = 10_000
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def delete_confined_path(
    filesystem: ConfinedWorkspaceFilesystem,
    relative_path: str,
    *,
    expected_resource_identity: str,
    expected_resource_revision: str,
    recursive: bool,
) -> ConfinedFilesystemResult:
    """Atomically hide one exact inode before bounded descriptor-only cleanup."""
    if not expected_resource_identity or not expected_resource_revision:
        raise RuntimeToolError("filesystem_expected_version_incomplete")
    components = filesystem._components(relative_path, allow_root=False)
    chain = filesystem._open_chain(components[:-1])
    trash_fd: int | None = None
    trash_name = f"delete-{secrets.token_hex(16)}"
    committed = False
    target_stat: os.stat_result | None = None
    try:
        target_stat = lstat_entry(chain.leaf_fd, components[-1])
        require_supported_type(target_stat)
        observation = filesystem._observation(
            resource_kind(target_stat),
            filesystem._relative(components),
            target_stat,
        )
        filesystem._require_expected(
            observation,
            identity=expected_resource_identity,
            revision=expected_resource_revision,
        )
        if stat.S_ISDIR(target_stat.st_mode):
            if not recursive:
                _require_empty_directory(chain.leaf_fd, components[-1], target_stat)
            else:
                _count_tree(
                    chain.leaf_fd,
                    components[-1],
                    target_stat,
                    remaining=MAX_RECURSIVE_DELETE_ENTRIES,
                )
        filesystem._hook("delete_before_commit", relative_path)
        revalidate_entry(filesystem, chain, components[-1], target_stat)
        trash_fd = _open_quarantine(filesystem)
        rename_noreplace(
            chain.leaf_fd,
            components[-1],
            trash_fd,
            trash_name,
        )
        quarantine_stat = lstat_entry(trash_fd, trash_name)
        if not same_identity(target_stat, quarantine_stat):
            restored = rollback_move(
                trash_fd,
                trash_name,
                chain.leaf_fd,
                components[-1],
                expected_identity=quarantine_stat,
            )
            if restored:
                raise RuntimeToolError("filesystem_resource_changed")
            raise RuntimeToolError("tool_execution_unknown")
        committed = True
        require_absent(chain.leaf_fd, components[-1])
        os.fsync(chain.leaf_fd)
        os.fsync(trash_fd)
        filesystem._hook("delete_committed", relative_path)
        filesystem._assert_chain(chain)
        deleted_entries, cleanup_reason = _cleanup_quarantine(
            trash_fd,
            trash_name,
            quarantine_stat,
            recursive=recursive,
        )
        return ConfinedFilesystemResult(
            {
                "path": observation.resource_ref,
                "deleted": True,
                "recursive": recursive,
                "deleted_entry_count": deleted_entries,
                "cleanup_pending": cleanup_reason is not None,
                "cleanup_reason": cleanup_reason,
                "resource_identity": observation.resource_identity,
                "resource_revision": observation.resource_revision,
                "resource_digest": observation.resource_digest,
            },
            filesystem._classification(observation, "tool_result"),
        )
    except RuntimeToolError as error:
        if committed and error.reason_code != "tool_execution_unknown":
            raise RuntimeToolError("tool_execution_unknown") from error
        raise
    except OSError as error:
        if committed:
            raise RuntimeToolError("tool_execution_unknown") from error
        raise RuntimeToolError("filesystem_delete_failed") from error
    finally:
        if trash_fd is not None:
            os.close(trash_fd)
        chain.close()


def _open_quarantine(filesystem: ConfinedWorkspaceFilesystem) -> int:
    root_fd = filesystem.duplicate_root_fd()
    runtime_fd: int | None = None
    try:
        try:
            os.mkdir("runtime", 0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        runtime_fd = os.open("runtime", _DIRECTORY_FLAGS, dir_fd=root_fd)
        try:
            os.mkdir("deletion-quarantine", 0o700, dir_fd=runtime_fd)
        except FileExistsError:
            pass
        quarantine_fd = os.open(
            "deletion-quarantine",
            _DIRECTORY_FLAGS,
            dir_fd=runtime_fd,
        )
        os.fchmod(quarantine_fd, 0o700)
        return quarantine_fd
    except OSError as error:
        raise RuntimeToolError("filesystem_delete_quarantine_unavailable") from error
    finally:
        if runtime_fd is not None:
            os.close(runtime_fd)
        os.close(root_fd)


def _require_empty_directory(
    parent_fd: int,
    name: str,
    expected: os.stat_result,
) -> None:
    directory_fd = _open_directory(parent_fd, name, expected)
    try:
        if os.listdir(directory_fd):
            raise RuntimeToolError("filesystem_directory_not_empty")
    finally:
        os.close(directory_fd)


def _count_tree(
    parent_fd: int,
    name: str,
    expected: os.stat_result,
    *,
    remaining: int,
) -> int:
    if remaining < 1:
        raise RuntimeToolError("filesystem_delete_too_large")
    directory_fd = _open_directory(parent_fd, name, expected)
    count = 1
    try:
        before = os.fstat(directory_fd)
        for child_name in sorted(os.listdir(directory_fd)):
            if child_name == ".git" or "\x00" in child_name:
                raise RuntimeToolError("filesystem_path_outside_workspace")
            child_stat = lstat_entry(directory_fd, child_name)
            if stat.S_ISDIR(child_stat.st_mode):
                count += _count_tree(
                    directory_fd,
                    child_name,
                    child_stat,
                    remaining=remaining - count,
                )
            elif stat.S_ISREG(child_stat.st_mode) or stat.S_ISLNK(child_stat.st_mode):
                count += 1
            else:
                raise RuntimeToolError("filesystem_path_type_denied")
            if count > remaining:
                raise RuntimeToolError("filesystem_delete_too_large")
        _assert_same_version(before, os.fstat(directory_fd))
        return count
    finally:
        os.close(directory_fd)


def _cleanup_quarantine(
    parent_fd: int,
    name: str,
    expected: os.stat_result,
    *,
    recursive: bool,
) -> tuple[int, str | None]:
    try:
        if stat.S_ISDIR(expected.st_mode):
            count = _delete_tree(
                parent_fd,
                name,
                expected,
                remaining=MAX_RECURSIVE_DELETE_ENTRIES,
            )
        else:
            current = lstat_entry(parent_fd, name)
            if not same_identity(current, expected):
                raise RuntimeToolError("filesystem_resource_changed")
            os.unlink(name, dir_fd=parent_fd)
            count = 1
        os.fsync(parent_fd)
        return count, None
    except Exception:
        # The requested path is already atomically absent.  Retain any cleanup
        # remainder under the platform-only runtime root and report it rather
        # than misrepresenting the user-visible delete as ambiguous.
        return 1, "filesystem_delete_cleanup_pending"


def _delete_tree(
    parent_fd: int,
    name: str,
    expected: os.stat_result,
    *,
    remaining: int,
) -> int:
    try:
        os.chmod(name, 0o700, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        pass
    directory_fd = _open_directory(parent_fd, name, expected, version=False)
    deleted = 1
    try:
        for child_name in sorted(os.listdir(directory_fd)):
            if child_name == ".git" or "\x00" in child_name:
                raise RuntimeToolError("filesystem_path_outside_workspace")
            if deleted >= remaining:
                raise RuntimeToolError("filesystem_delete_too_large")
            child_stat = lstat_entry(directory_fd, child_name)
            if stat.S_ISDIR(child_stat.st_mode):
                count = _delete_tree(
                    directory_fd,
                    child_name,
                    child_stat,
                    remaining=remaining - deleted,
                )
                deleted += count
            elif stat.S_ISREG(child_stat.st_mode) or stat.S_ISLNK(child_stat.st_mode):
                current = lstat_entry(directory_fd, child_name)
                if not same_identity(current, child_stat):
                    raise RuntimeToolError("filesystem_resource_changed")
                os.unlink(child_name, dir_fd=directory_fd)
                deleted += 1
            else:
                raise RuntimeToolError("filesystem_path_type_denied")
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    current = lstat_entry(parent_fd, name)
    if not same_identity(current, expected):
        raise RuntimeToolError("filesystem_resource_changed")
    os.rmdir(name, dir_fd=parent_fd)
    return deleted


def _open_directory(
    parent_fd: int,
    name: str,
    expected: os.stat_result,
    *,
    version: bool = True,
) -> int:
    try:
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    except OSError as error:
        raise RuntimeToolError("filesystem_resource_changed") from error
    current = os.fstat(descriptor)
    if not same_identity(current, expected):
        os.close(descriptor)
        raise RuntimeToolError("filesystem_resource_changed")
    if version:
        try:
            _assert_same_version(expected, current)
        except Exception:
            os.close(descriptor)
            raise
    return descriptor


def _assert_same_version(left: os.stat_result, right: os.stat_result) -> None:
    fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(left, field) != getattr(right, field) for field in fields):
        raise RuntimeToolError("filesystem_resource_changed")
