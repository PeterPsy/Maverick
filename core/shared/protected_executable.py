"""Filesystem protection facts shared by declared installation toolchains."""

from pathlib import Path
import stat


def is_protected_executable(binary: Path) -> bool:
    try:
        for path in (binary, *binary.parents):
            metadata = path.lstat()
            kind = stat.S_ISREG if path == binary else stat.S_ISDIR
            if not kind(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
                return False
        return bool(binary.stat().st_mode & stat.S_IXUSR)
    except OSError:
        return False
