"""Real, root-owned backing paths for privileged installation writers."""

import os
from pathlib import Path
import stat


def require_protected_parents(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Privileged material requires an absolute real path")
    for parent in reversed(path.parents):
        metadata = parent.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise ValueError(f"Unprotected privileged parent: {parent}")
    if path.is_symlink():
        raise ValueError("Privileged material cannot be a symlink")


def protected_directory(path: Path) -> Path:
    """Create only missing directories; never repair a service-controlled parent."""
    if not path.exists():
        protected_directory(path.parent)
        path.mkdir(mode=0o755)
    require_protected_parents(path / ".parent-check")
    return path


def protect_service_environment(path: Path, group: str, runner) -> None:
    require_protected_parents(path)
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise ValueError("Service environment content must already be root-controlled")
    runner(["chown", f"root:{group}", str(path)])
    runner(["chmod", "0640", str(path)])


def require_service_environment(path: Path) -> None:
    require_protected_parents(path)
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o640:
        raise ValueError("The service environment must be root-owned at 0640")


def require_root_environment_update(path: Path) -> None:
    if os.geteuid() != 0:
        raise PermissionError("Only root can update installation service configuration")
    require_service_environment(path)


def prepare_host_logs(root: Path) -> None:
    for name in ("systemd", "nginx"):
        protected_directory(root / "installation/logs" / name)


def create_recovery_backup(root: Path, kind: str, name: str) -> Path:
    if kind not in {"wildcard", "azure"} or Path(name).name != name or name in {"", ".", ".."}:
        raise ValueError("Invalid recovery backup namespace")
    parent = protected_directory(root / "installation/backups" / kind)
    backup = parent / name
    backup.mkdir(mode=0o700)
    return backup
