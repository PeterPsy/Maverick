"""Process-safe workspace lock for one complete official update transaction."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
import tempfile
from typing import Iterator

from core.shared.operating_group import permits_operating_group_handoff

from official_update_state import OfficialUpdateError


UPDATE_LOCK_FILE = ".official-update.lock"


@contextmanager
def official_update_lock(
    app_data_root: Path, *, blocking: bool = False
) -> Iterator[bool]:
    """Hold one safe per-workspace lock, optionally reporting a live owner."""
    root = Path(app_data_root)
    path = root / UPDATE_LOCK_FILE
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise OfficialUpdateError("official update lock is unavailable") from error
    acquired = False
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise OfficialUpdateError("official update lock is unsafe")
        trusted_group_handoff = False
        if metadata.st_uid != os.geteuid():
            try:
                root_metadata = root.lstat()
            except OSError as error:
                raise OfficialUpdateError("official update lock is unsafe") from error
            trusted_group_handoff = permits_operating_group_handoff(
                metadata,
                root_metadata,
            )
            if not trusted_group_handoff:
                raise OfficialUpdateError("official update lock is unsafe")
        operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(descriptor, operation)
            acquired = True
        except BlockingIOError:
            if blocking:
                raise
        if acquired and trusted_group_handoff:
            replacement = _replace_stale_lock(path, expected=metadata)
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            descriptor = replacement
        elif acquired and stat.S_IMODE(metadata.st_mode) != 0o600:
            try:
                os.fchmod(descriptor, 0o600)
            except OSError as error:
                raise OfficialUpdateError("official update lock is unsafe") from error
        yield acquired
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _replace_stale_lock(path: Path, *, expected: os.stat_result) -> int:
    """Replace one unlocked trusted-group inode with a private lock we own."""
    temporary_path: Path | None = None
    replacement = -1
    try:
        replacement, temporary = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".handoff",
        )
        temporary_path = Path(temporary)
        os.fchmod(replacement, 0o600)
        metadata = os.fstat(replacement)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise OfficialUpdateError("replacement official update lock is unsafe")
        fcntl.flock(replacement, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = path.lstat()
        if (
            (current.st_dev, current.st_ino) != (expected.st_dev, expected.st_ino)
            or current.st_ctime_ns != expected.st_ctime_ns
            or not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
        ):
            raise OfficialUpdateError("official update lock changed during handoff")
        os.replace(temporary_path, path)
        temporary_path = None
        installed = path.lstat()
        if (
            (installed.st_dev, installed.st_ino) != (metadata.st_dev, metadata.st_ino)
            or installed.st_uid != os.geteuid()
            or installed.st_nlink != 1
            or stat.S_IMODE(installed.st_mode) != 0o600
        ):
            raise OfficialUpdateError("replacement official update lock changed")
        _fsync_directory(path.parent)
        return replacement
    except (OSError, BlockingIOError) as error:
        if replacement >= 0:
            os.close(replacement)
        raise OfficialUpdateError("official update lock handoff failed") from error
    except Exception:
        if replacement >= 0:
            os.close(replacement)
        raise
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = ["official_update_lock"]
