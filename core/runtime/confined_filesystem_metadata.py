"""Descriptor-backed metadata capture and exact file metadata cloning."""

from __future__ import annotations

from dataclasses import dataclass
import os
import stat

from core.runtime.tool_errors import RuntimeToolError


MAX_CONFINED_XATTRS = 128
MAX_CONFINED_XATTR_BYTES = 1_048_576


@dataclass(frozen=True)
class ConfinedPathMetadata:
    """Stable metadata observed from one already-open confined inode."""

    mode: int
    uid: int
    gid: int
    atime_ns: int
    mtime_ns: int
    ctime_ns: int
    xattrs: tuple[tuple[str, bytes], ...]


def capture_fd_metadata(
    fd: int,
    *,
    unavailable_reason: str = "filesystem_metadata_unavailable",
) -> ConfinedPathMetadata:
    """Read bounded metadata and reject a concurrent metadata/content race."""
    try:
        before = os.fstat(fd)
        names = tuple(sorted(os.listxattr(fd)))
        if len(names) > MAX_CONFINED_XATTRS:
            raise RuntimeToolError("filesystem_metadata_unsupported")
        values: list[tuple[str, bytes]] = []
        total_bytes = 0
        for raw_name in names:
            name = os.fsdecode(raw_name)
            value = bytes(os.getxattr(fd, raw_name))
            total_bytes += len(os.fsencode(name)) + len(value)
            if total_bytes > MAX_CONFINED_XATTR_BYTES:
                raise RuntimeToolError("filesystem_metadata_unsupported")
            values.append((name, value))
        after = os.fstat(fd)
    except RuntimeToolError:
        raise
    except OSError as error:
        raise RuntimeToolError(unavailable_reason) from error
    if _version_fields(before) != _version_fields(after):
        raise RuntimeToolError("filesystem_resource_changed")
    return ConfinedPathMetadata(
        mode=stat.S_IMODE(after.st_mode),
        uid=after.st_uid,
        gid=after.st_gid,
        atime_ns=after.st_atime_ns,
        mtime_ns=after.st_mtime_ns,
        ctime_ns=after.st_ctime_ns,
        xattrs=tuple(values),
    )


def apply_preserved_file_metadata(
    fd: int,
    metadata: ConfinedPathMetadata,
) -> ConfinedPathMetadata:
    """Clone ownership, permission bits, ACLs, and xattrs or fail closed."""
    try:
        current = os.fstat(fd)
        content_mtime_ns = current.st_mtime_ns
        if (current.st_uid, current.st_gid) != (metadata.uid, metadata.gid):
            os.fchown(fd, metadata.uid, metadata.gid)
        os.fchmod(fd, metadata.mode)
        expected = dict(metadata.xattrs)
        for raw_name in os.listxattr(fd):
            name = os.fsdecode(raw_name)
            if name not in expected:
                os.removexattr(fd, raw_name)
        for name, value in metadata.xattrs:
            os.setxattr(fd, name, value)
        os.utime(fd, ns=(metadata.atime_ns, content_mtime_ns))
        observed = capture_fd_metadata(fd)
    except RuntimeToolError as error:
        raise RuntimeToolError("filesystem_metadata_preservation_failed") from error
    except OSError as error:
        raise RuntimeToolError("filesystem_metadata_preservation_failed") from error
    if not preserved_metadata_matches(metadata, observed):
        raise RuntimeToolError("filesystem_metadata_preservation_failed")
    if observed.atime_ns != metadata.atime_ns:
        raise RuntimeToolError("filesystem_metadata_preservation_failed")
    return observed


def apply_new_file_metadata(
    fd: int,
    *,
    mode: int,
    uid: int,
    gid: int,
) -> ConfinedPathMetadata:
    """Apply the representable creation metadata captured from the overlay."""
    if (
        not isinstance(mode, int)
        or isinstance(mode, bool)
        or mode < 0
        or mode > 0o7777
        or not isinstance(uid, int)
        or isinstance(uid, bool)
        or uid < 0
        or not isinstance(gid, int)
        or isinstance(gid, bool)
        or gid < 0
    ):
        raise RuntimeToolError("filesystem_metadata_unsupported")
    try:
        current = os.fstat(fd)
        if (current.st_uid, current.st_gid) != (uid, gid):
            os.fchown(fd, uid, gid)
        os.fchmod(fd, mode)
        for raw_name in os.listxattr(fd):
            os.removexattr(fd, raw_name)
        observed = capture_fd_metadata(fd)
    except RuntimeToolError as error:
        raise RuntimeToolError("filesystem_metadata_preservation_failed") from error
    except OSError as error:
        raise RuntimeToolError("filesystem_metadata_preservation_failed") from error
    if observed.mode != mode or observed.uid != uid or observed.gid != gid or observed.xattrs:
        raise RuntimeToolError("filesystem_metadata_preservation_failed")
    return observed


def preserved_metadata_matches(
    expected: ConfinedPathMetadata,
    observed: ConfinedPathMetadata,
) -> bool:
    """Compare metadata that must survive a content-only replacement."""
    return (
        expected.mode == observed.mode
        and expected.uid == observed.uid
        and expected.gid == observed.gid
        and expected.xattrs == observed.xattrs
    )


def materialized_metadata_matches(
    expected: ConfinedPathMetadata,
    observed: ConfinedPathMetadata,
) -> bool:
    """Compare stable metadata plus user-observable access/modification times."""
    return (
        preserved_metadata_matches(expected, observed)
        and expected.atime_ns == observed.atime_ns
        and expected.mtime_ns == observed.mtime_ns
    )


def _version_fields(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


__all__ = [
    "ConfinedPathMetadata",
    "apply_new_file_metadata",
    "apply_preserved_file_metadata",
    "capture_fd_metadata",
    "materialized_metadata_matches",
    "preserved_metadata_matches",
]
