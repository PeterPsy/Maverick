"""Trust decisions for files handed between local service operators."""

from __future__ import annotations

import os
import stat


def permits_operating_group_handoff(
    file_metadata: os.stat_result,
    directory_metadata: os.stat_result,
    *,
    effective_gid: int | None = None,
    supplementary_gids: tuple[int, ...] | None = None,
) -> bool:
    """Return whether a stale regular file belongs to the shared operating group.

    The setgid directory is the explicit trust marker.  Merely finding a
    writable file or a matching world-writable directory is not sufficient.
    Callers must still replace the old inode without following it and validate
    the new private inode after the handoff.
    """
    directory_mode = directory_metadata.st_mode
    groups = set(os.getgroups() if supplementary_gids is None else supplementary_gids)
    groups.add(os.getegid() if effective_gid is None else effective_gid)
    return bool(
        stat.S_ISREG(file_metadata.st_mode)
        and file_metadata.st_nlink == 1
        and stat.S_ISDIR(directory_mode)
        and directory_mode & stat.S_ISGID
        and directory_mode & stat.S_IWGRP
        and directory_mode & stat.S_IXGRP
        and file_metadata.st_gid == directory_metadata.st_gid
        and directory_metadata.st_gid in groups
    )


__all__ = ["permits_operating_group_handoff"]
