"""Exclusive OS integration symlinks to installation-owned backing files."""

from pathlib import Path
import os


def registration_exists(path: Path, backing: Path) -> bool:
    """Accept only our exact symlink, including when its target is missing."""
    if path.is_symlink():
        if os.readlink(path) == str(backing):
            return True
        raise FileExistsError(f"Unrelated integration symlink: {path}")
    if path.exists():
        raise FileExistsError(f"Unrelated integration file: {path}")
    return False


def register_file(path: Path, backing: Path, *, run_command=None) -> None:
    if registration_exists(path, backing):
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(backing)
    except PermissionError:
        if run_command is None:
            raise
        run_command(["mkdir", "-p", str(path.parent)])
        # Never replace an entry that appeared after the ownership check.
        run_command(["ln", "-s", str(backing), str(path)])


def unregister_file(path: Path, backing: Path, *, run_command=None) -> None:
    if not registration_exists(path, backing):
        return
    try:
        path.unlink()
    except PermissionError:
        if run_command is None:
            raise
        run_command(["rm", "--", str(path)])


def installation_backing_path(root: Path, directory: str, name: str) -> Path:
    """Reject backing paths whose existing ancestors redirect outside the root."""
    path = root / "installation" / directory / name
    if not root.is_absolute() or Path(name).name != name or directory not in {"nginx", "systemd"}:
        raise ValueError("Invalid installation backing path")
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("Installation backing files require real ancestors")
    return path
