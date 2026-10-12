"""Atomic root-owned worker journals, inaccessible to the API process."""

import json
import os
from pathlib import Path
import tempfile

from core.installation.errors import InstallationError


def write_private(path: Path, value: dict) -> None:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise InstallationError("unsafe_installation_state")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".journal-")
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
