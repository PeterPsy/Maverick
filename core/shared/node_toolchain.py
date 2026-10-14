"""Narrow trust declaration for the installation's isolated Node distribution."""

from pathlib import Path
import stat

from core.shared.repository import discover_repository_root


NODE_TOOLCHAIN_DIRECTORY = "node-v24.11.0-linux-x64"


def installation_node_toolchain_root() -> Path:
    return discover_repository_root() / ".toolchains" / NODE_TOOLCHAIN_DIRECTORY


def is_protected_installation_node(node_binary: Path) -> bool:
    """Accept only the declared binary with root-owned, non-writable ancestors."""
    root = installation_node_toolchain_root()
    if node_binary != root / "bin/node":
        return False
    try:
        for path in (node_binary, *node_binary.parents):
            metadata = path.lstat()
            expected_kind = stat.S_ISREG if path == node_binary else stat.S_ISDIR
            if (
                not expected_kind(metadata.st_mode)
                or metadata.st_uid != 0
                or metadata.st_mode & 0o022
            ):
                return False
        return bool(node_binary.stat().st_mode & stat.S_IXUSR)
    except OSError:
        return False
