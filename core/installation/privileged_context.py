"""Protected HOME/XDG context shared by privileged installation children."""

import os
from pathlib import Path

from core.installation.protected_material import protected_directory


def privileged_environment(root: Path) -> dict[str, str]:
    home = root / "installation/privileged-home"
    return {"HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_CACHE_HOME": str(home / "cache"), "XDG_DATA_HOME": str(home / "data"),
            "XDG_STATE_HOME": str(home / "state"), "TMPDIR": str(home / "tmp"),
            "PYTHONNOUSERSITE": "1"}


def prepare_privileged_context(root: Path) -> None:
    for value in dict.fromkeys(privileged_environment(root).values()):
        if value == "1":
            continue
        path = protected_directory(Path(value))
        path.chmod(0o700)


def enter_privileged_context(root: Path) -> None:
    prepare_privileged_context(root)
    os.environ.update(privileged_environment(root))
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE"):
        os.environ.pop(name, None)


def privileged_exec_environment(root: Path) -> str:
    """ExecStart assignments override EnvironmentFile before Python startup."""
    return "/usr/bin/env -- " + " ".join(f"{key}={value}" for key, value in privileged_environment(root).items())
