"""No-follow private operator files; never resolve these under tenant mounts."""

import os
from pathlib import Path
import stat

from core.certification_lab.errors import LabAuthorizationError


def require_private_path(path: Path, *, must_exist: bool = True) -> None:
    try:
        if not path.is_absolute() or path.resolve() != path:
            raise ValueError
        parent = path.parent.stat()
        if parent.st_uid != os.geteuid() or parent.st_mode & 0o077:
            raise ValueError
        if must_exist:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid != os.geteuid() or info.st_mode & 0o077):
                raise ValueError
    except (OSError, ValueError) as error:
        raise LabAuthorizationError("lab_private_store_unavailable") from error


def read_private_file(path: Path, *, max_bytes: int = 65_536) -> bytes:
    require_private_path(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid != os.geteuid() or info.st_mode & 0o077):
                raise ValueError
            content = source.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise ValueError
        return content
    except (OSError, ValueError) as error:
        raise LabAuthorizationError("lab_private_store_unavailable") from error
