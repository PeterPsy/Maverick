"""Linux descriptor-relative primitives shared by confined mutations."""

from __future__ import annotations

import ctypes
import errno
import os
import stat

from core.runtime.tool_errors import RuntimeToolError


_RENAME_NOREPLACE = 1
_RENAME_EXCHANGE = 2


def lstat_entry(parent_fd: int, name: str) -> os.stat_result:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError as error:
        raise RuntimeToolError("filesystem_path_not_found") from error
    except OSError as error:
        raise RuntimeToolError("filesystem_resource_changed") from error


def revalidate_entry(filesystem, chain, name: str, expected: os.stat_result) -> None:
    current = lstat_entry(chain.leaf_fd, name)
    filesystem._assert_same_version(
        expected,
        current,
        "filesystem_resource_changed",
    )
    filesystem._assert_chain(chain)


def require_supported_type(value: os.stat_result) -> None:
    if stat.S_ISLNK(value.st_mode):
        raise RuntimeToolError("filesystem_symlink_denied")
    if not (stat.S_ISREG(value.st_mode) or stat.S_ISDIR(value.st_mode)):
        raise RuntimeToolError("filesystem_path_type_denied")


def resource_kind(value: os.stat_result) -> str:
    return "filesystem_directory" if stat.S_ISDIR(value.st_mode) else "filesystem_file"


def rename_noreplace(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
) -> None:
    _renameat2(
        source_parent_fd,
        source_name,
        destination_parent_fd,
        destination_name,
        flags=_RENAME_NOREPLACE,
    )


def rename_exchange(
    left_parent_fd: int,
    left_name: str,
    right_parent_fd: int,
    right_name: str,
) -> None:
    """Atomically exchange two existing directory entries."""
    _renameat2(
        left_parent_fd,
        left_name,
        right_parent_fd,
        right_name,
        flags=_RENAME_EXCHANGE,
    )


def _renameat2(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
    *,
    flags: int,
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise RuntimeToolError("filesystem_atomic_move_unavailable")
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        source_parent_fd,
        os.fsencode(source_name),
        destination_parent_fd,
        os.fsencode(destination_name),
        flags,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST and flags == _RENAME_NOREPLACE:
        raise RuntimeToolError("filesystem_path_exists")
    if error_number in {errno.ENOSYS, errno.EINVAL}:
        raise RuntimeToolError("filesystem_atomic_move_unavailable")
    raise OSError(error_number, os.strerror(error_number))


def rollback_move(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
    *,
    expected_identity: os.stat_result,
) -> bool:
    try:
        rename_noreplace(
            source_parent_fd,
            source_name,
            destination_parent_fd,
            destination_name,
        )
        restored = lstat_entry(destination_parent_fd, destination_name)
        return same_identity(restored, expected_identity)
    except Exception:
        return False


def require_absent(parent_fd: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise RuntimeToolError("filesystem_resource_changed")


def same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)
