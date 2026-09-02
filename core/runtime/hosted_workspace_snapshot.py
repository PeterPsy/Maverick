"""Immutable, descriptor-confined workspace views for hosted commands."""

from __future__ import annotations

from dataclasses import dataclass, field
import errno
import fcntl
import os
from pathlib import Path
import shutil
import stat
from uuid import uuid4

from core.runtime.confined_filesystem import (
    MAX_CONFINED_PATH_COMPONENTS,
    ConfinedWorkspaceFilesystem,
)
from core.runtime.confined_filesystem_metadata import (
    ConfinedPathMetadata,
    apply_preserved_file_metadata,
    capture_fd_metadata,
)
from core.runtime.tool_errors import RuntimeToolError


MAX_HOSTED_WORKSPACE_SNAPSHOT_DIRECTORIES = 50_000
MAX_HOSTED_WORKSPACE_SNAPSHOT_ENTRIES = 250_000
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_NOATIME = getattr(os, "O_NOATIME", 0)
_FICLONE = 0x40049409
_COPY_CHUNK_BYTES = 1_048_576
_SNAPSHOT_PARENT = "agent-workspace-snapshots"


@dataclass
class _SnapshotState:
    directories: int = 0
    entries: int = 0


@dataclass
class HostedWorkspaceSnapshot:
    """One immutable staged workspace whose namespace excludes protected data."""

    root: Path
    _root_fd: int = field(repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    @classmethod
    def create(
        cls,
        filesystem: ConfinedWorkspaceFilesystem,
        *,
        runtime_root: Path,
    ) -> "HostedWorkspaceSnapshot":
        """Materialize a stable view, failing closed on namespace/content races."""
        runtime_fd = filesystem.open_platform_runtime_fd(runtime_root)
        parent_fd: int | None = None
        destination_fd: int | None = None
        source_fd: int | None = None
        name = f"snapshot-{uuid4().hex}"
        root = runtime_root / _SNAPSHOT_PARENT / name
        try:
            try:
                os.mkdir(_SNAPSHOT_PARENT, 0o700, dir_fd=runtime_fd)
            except FileExistsError:
                pass
            parent_fd = os.open(
                _SNAPSHOT_PARENT,
                os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
                dir_fd=runtime_fd,
            )
            os.fchmod(parent_fd, 0o700)
            os.mkdir(name, 0o700, dir_fd=parent_fd)
            destination_fd = os.open(
                name,
                os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
                dir_fd=parent_fd,
            )
            pinned_root_fd = filesystem.duplicate_root_fd()
            try:
                source_fd = os.open(
                    ".",
                    os.O_RDONLY
                    | _DIRECTORY
                    | _NOFOLLOW
                    | _NOATIME
                    | _CLOEXEC,
                    dir_fd=pinned_root_fd,
                )
            finally:
                os.close(pinned_root_fd)
            _copy_directory(
                source_fd,
                destination_fd,
                components=(),
                state=_SnapshotState(),
            )
            snapshot = cls(root=root, _root_fd=destination_fd)
            destination_fd = None
            return snapshot
        except RuntimeToolError:
            _remove_snapshot_tree(root)
            raise
        except (OSError, UnicodeError) as error:
            _remove_snapshot_tree(root)
            raise RuntimeToolError("workspace_snapshot_unavailable") from error
        finally:
            if source_fd is not None:
                os.close(source_fd)
            if destination_fd is not None:
                os.close(destination_fd)
            if parent_fd is not None:
                os.close(parent_fd)
            os.close(runtime_fd)

    def duplicate_root_fd(self) -> int:
        if self._closed:
            raise RuntimeToolError("workspace_snapshot_closed")
        return os.dup(self._root_fd)

    def discard(self) -> None:
        """Release the retained view and remove its Core-private staging tree."""
        if self._closed:
            return
        self._closed = True
        try:
            os.close(self._root_fd)
        finally:
            _remove_snapshot_tree(self.root)


def _copy_directory(
    source_fd: int,
    destination_fd: int,
    *,
    components: tuple[str, ...],
    state: _SnapshotState,
) -> None:
    before = capture_fd_metadata(
        source_fd,
        unavailable_reason="workspace_snapshot_changed",
    )
    try:
        with os.scandir(source_fd) as iterator:
            names = []
            for entry in iterator:
                state.entries += 1
                if state.entries > MAX_HOSTED_WORKSPACE_SNAPSHOT_ENTRIES:
                    raise RuntimeToolError("workspace_snapshot_too_large")
                entry.name.encode("utf-8", errors="strict")
                names.append(entry.name)
        names.sort()
    except RuntimeToolError:
        raise
    except (OSError, UnicodeError) as error:
        raise RuntimeToolError("workspace_snapshot_changed") from error

    for name in names:
        # Git metadata is outside the hosted workspace contract regardless of
        # whether it is a directory, worktree pointer, or symlink. The platform
        # runtime subtree is likewise replaced by a private sandbox runtime.
        if name == ".git":
            continue
        if not components and name == "runtime":
            # Keep only the mount point. Bubblewrap replaces it with a private
            # tmpfs before exec, while no live runtime child can enter the view.
            try:
                os.mkdir(name, 0o700, dir_fd=destination_fd)
            except OSError as error:
                raise RuntimeToolError("workspace_snapshot_changed") from error
            continue
        try:
            observed = os.stat(
                name,
                dir_fd=source_fd,
                follow_symlinks=False,
            )
        except OSError as error:
            raise RuntimeToolError("workspace_snapshot_changed") from error
        path_components = (*components, name)
        if stat.S_ISDIR(observed.st_mode):
            _copy_child_directory(
                source_fd,
                destination_fd,
                name=name,
                observed=observed,
                components=path_components,
                state=state,
            )
        elif stat.S_ISREG(observed.st_mode):
            _copy_regular_file(
                source_fd,
                destination_fd,
                name=name,
                observed=observed,
            )
        elif stat.S_ISLNK(observed.st_mode):
            _copy_symlink(
                source_fd,
                destination_fd,
                name=name,
                observed=observed,
            )
        else:
            raise RuntimeToolError("workspace_snapshot_entry_unsupported")

    after = capture_fd_metadata(
        source_fd,
        unavailable_reason="workspace_snapshot_changed",
    )
    if not _source_metadata_stable(before, after, ignore_atime=True):
        raise RuntimeToolError("workspace_snapshot_changed")
    apply_preserved_file_metadata(
        destination_fd,
        before,
        target_atime_ns=before.atime_ns,
        target_mtime_ns=before.mtime_ns,
    )


def _copy_child_directory(
    source_parent_fd: int,
    destination_parent_fd: int,
    *,
    name: str,
    observed: os.stat_result,
    components: tuple[str, ...],
    state: _SnapshotState,
) -> None:
    if len(components) >= MAX_CONFINED_PATH_COMPONENTS:
        raise RuntimeToolError("workspace_snapshot_too_large")
    state.directories += 1
    if state.directories > MAX_HOSTED_WORKSPACE_SNAPSHOT_DIRECTORIES:
        raise RuntimeToolError("workspace_snapshot_too_large")
    source_fd: int | None = None
    destination_fd: int | None = None
    try:
        source_fd = os.open(
            name,
            os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _NOATIME | _CLOEXEC,
            dir_fd=source_parent_fd,
        )
        if not _stat_identity_matches(observed, os.fstat(source_fd)):
            raise RuntimeToolError("workspace_snapshot_changed")
        os.mkdir(name, 0o700, dir_fd=destination_parent_fd)
        destination_fd = os.open(
            name,
            os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
            dir_fd=destination_parent_fd,
        )
        _copy_directory(
            source_fd,
            destination_fd,
            components=components,
            state=state,
        )
    except RuntimeToolError:
        raise
    except OSError as error:
        raise RuntimeToolError("workspace_snapshot_changed") from error
    finally:
        if destination_fd is not None:
            os.close(destination_fd)
        if source_fd is not None:
            os.close(source_fd)


def _copy_regular_file(
    source_parent_fd: int,
    destination_parent_fd: int,
    *,
    name: str,
    observed: os.stat_result,
) -> None:
    source_fd: int | None = None
    destination_fd: int | None = None
    try:
        source_fd = os.open(
            name,
            os.O_RDONLY | _NOFOLLOW | _NOATIME | _CLOEXEC,
            dir_fd=source_parent_fd,
        )
        if not _stat_identity_matches(observed, os.fstat(source_fd)):
            raise RuntimeToolError("workspace_snapshot_changed")
        before = capture_fd_metadata(
            source_fd,
            unavailable_reason="workspace_snapshot_changed",
        )
        if before.file_type != stat.S_IFREG:
            raise RuntimeToolError("workspace_snapshot_changed")
        destination_fd = os.open(
            name,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | _NOFOLLOW
            | _CLOEXEC,
            0o600,
            dir_fd=destination_parent_fd,
        )
        _copy_file_bytes(source_fd, destination_fd, expected_size=before.size_bytes)
        after = capture_fd_metadata(
            source_fd,
            unavailable_reason="workspace_snapshot_changed",
        )
        if not _source_metadata_stable(before, after, ignore_atime=True):
            raise RuntimeToolError("workspace_snapshot_changed")
        apply_preserved_file_metadata(
            destination_fd,
            before,
            target_atime_ns=before.atime_ns,
            target_mtime_ns=before.mtime_ns,
        )
    except RuntimeToolError:
        raise
    except OSError as error:
        raise RuntimeToolError("workspace_snapshot_changed") from error
    finally:
        if destination_fd is not None:
            os.close(destination_fd)
        if source_fd is not None:
            os.close(source_fd)


def _copy_file_bytes(source_fd: int, destination_fd: int, *, expected_size: int) -> None:
    try:
        fcntl.ioctl(destination_fd, _FICLONE, source_fd)
    except OSError as error:
        if error.errno not in {
            errno.EBADF,
            errno.EINVAL,
            errno.ENOTTY,
            errno.EOPNOTSUPP,
            errno.EXDEV,
            errno.EPERM,
        }:
            raise
        os.ftruncate(destination_fd, 0)
        os.lseek(source_fd, 0, os.SEEK_SET)
        os.lseek(destination_fd, 0, os.SEEK_SET)
        remaining = expected_size
        while remaining:
            chunk = os.read(source_fd, min(_COPY_CHUNK_BYTES, remaining))
            if not chunk:
                raise RuntimeToolError("workspace_snapshot_changed")
            view = memoryview(chunk)
            while view:
                written = os.write(destination_fd, view)
                if written <= 0:
                    raise RuntimeToolError("workspace_snapshot_unavailable")
                view = view[written:]
            remaining -= len(chunk)
        if os.read(source_fd, 1):
            raise RuntimeToolError("workspace_snapshot_changed")
    if os.fstat(destination_fd).st_size != expected_size:
        raise RuntimeToolError("workspace_snapshot_changed")


def _copy_symlink(
    source_parent_fd: int,
    destination_parent_fd: int,
    *,
    name: str,
    observed: os.stat_result,
) -> None:
    source_path = f"/proc/self/fd/{source_parent_fd}/{name}"
    destination_path = f"/proc/self/fd/{destination_parent_fd}/{name}"
    try:
        target = os.readlink(name, dir_fd=source_parent_fd)
        source_xattrs = _symlink_xattrs(source_path)
        after_read = os.stat(
            name,
            dir_fd=source_parent_fd,
            follow_symlinks=False,
        )
        if not _stat_version_matches(observed, after_read, ignore_atime=True):
            raise RuntimeToolError("workspace_snapshot_changed")
        os.symlink(target, name, dir_fd=destination_parent_fd)
        os.chown(
            name,
            observed.st_uid,
            observed.st_gid,
            dir_fd=destination_parent_fd,
            follow_symlinks=False,
        )
        for attribute, value in source_xattrs:
            os.setxattr(
                destination_path,
                attribute,
                value,
                follow_symlinks=False,
            )
        os.utime(
            name,
            ns=(observed.st_atime_ns, observed.st_mtime_ns),
            dir_fd=destination_parent_fd,
            follow_symlinks=False,
        )
        destination = os.stat(
            name,
            dir_fd=destination_parent_fd,
            follow_symlinks=False,
        )
        final_source = os.stat(
            name,
            dir_fd=source_parent_fd,
            follow_symlinks=False,
        )
        if (
            not _stat_version_matches(observed, final_source, ignore_atime=True)
            or not stat.S_ISLNK(destination.st_mode)
            or os.readlink(name, dir_fd=destination_parent_fd) != target
            or (destination.st_uid, destination.st_gid)
            != (observed.st_uid, observed.st_gid)
            or destination.st_atime_ns != observed.st_atime_ns
            or destination.st_mtime_ns != observed.st_mtime_ns
            or _symlink_xattrs(destination_path) != source_xattrs
        ):
            raise RuntimeToolError("workspace_snapshot_changed")
    except RuntimeToolError:
        raise
    except OSError as error:
        raise RuntimeToolError("workspace_snapshot_changed") from error


def _symlink_xattrs(path: str) -> tuple[tuple[str, bytes], ...]:
    try:
        names = tuple(sorted(os.listxattr(path, follow_symlinks=False)))
        return tuple(
            (name, bytes(os.getxattr(path, name, follow_symlinks=False)))
            for name in names
        )
    except OSError as error:
        # Linux commonly denies symlink xattr access even when no xattrs exist;
        # fail closed rather than silently dropping observable metadata.
        raise RuntimeToolError("workspace_snapshot_metadata_unavailable") from error


def _stat_identity_matches(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev,
        before.st_ino,
        stat.S_IFMT(before.st_mode),
    ) == (
        after.st_dev,
        after.st_ino,
        stat.S_IFMT(after.st_mode),
    )


def _stat_version_matches(
    before: os.stat_result,
    after: os.stat_result,
    *,
    ignore_atime: bool,
) -> bool:
    fields_before = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_uid,
        before.st_gid,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    fields_after = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_uid,
        after.st_gid,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    return fields_before == fields_after and (
        ignore_atime or before.st_atime_ns == after.st_atime_ns
    )


def _source_metadata_stable(
    before: ConfinedPathMetadata,
    after: ConfinedPathMetadata,
    *,
    ignore_atime: bool,
) -> bool:
    return (
        before.device == after.device
        and before.inode == after.inode
        and before.file_type == after.file_type
        and before.mode == after.mode
        and before.uid == after.uid
        and before.gid == after.gid
        and before.link_count == after.link_count
        and before.size_bytes == after.size_bytes
        and before.mtime_ns == after.mtime_ns
        and before.ctime_ns == after.ctime_ns
        and before.xattrs == after.xattrs
        and (ignore_atime or before.atime_ns == after.atime_ns)
    )


def _remove_snapshot_tree(root: Path) -> None:
    if not root.exists():
        return
    try:
        for directory, names, _files in os.walk(root, topdown=True):
            try:
                os.chmod(directory, 0o700, follow_symlinks=False)
            except OSError:
                pass
            # os.walk places symlinked directories in names. Never chmod their
            # targets while making copied directories removable.
            names[:] = [
                name
                for name in names
                if not Path(directory, name).is_symlink()
            ]
        shutil.rmtree(root, ignore_errors=True)
    except OSError:
        pass


__all__ = [
    "HostedWorkspaceSnapshot",
    "MAX_HOSTED_WORKSPACE_SNAPSHOT_DIRECTORIES",
    "MAX_HOSTED_WORKSPACE_SNAPSHOT_ENTRIES",
]
