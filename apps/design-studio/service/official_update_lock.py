"""Process-safe workspace lock for one complete official update transaction."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
from typing import Iterator

from official_update_state import OfficialUpdateError


UPDATE_LOCK_FILE = ".official-update.lock"


@contextmanager
def official_update_lock(
    app_data_root: Path, *, blocking: bool = False
) -> Iterator[bool]:
    """Hold one safe per-workspace lock, optionally reporting a live owner."""
    path = Path(app_data_root) / UPDATE_LOCK_FILE
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise OfficialUpdateError("official update lock is unavailable") from error
    acquired = False
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            raise OfficialUpdateError("official update lock is unsafe")
        operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(descriptor, operation)
            acquired = True
        except BlockingIOError:
            if blocking:
                raise
        yield acquired
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


__all__ = ["official_update_lock"]
