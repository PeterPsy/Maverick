"""Narrow trust declaration for the installation's isolated Node distribution."""

from pathlib import Path
from core.shared.protected_executable import is_protected_executable

from core.shared.repository import discover_repository_root


NODE_TOOLCHAIN_DIRECTORY = "node-v24.11.0-linux-x64"


def installation_node_toolchain_root() -> Path:
    return discover_repository_root() / ".toolchains" / NODE_TOOLCHAIN_DIRECTORY


def is_protected_installation_node(node_binary: Path) -> bool:
    """Accept only the declared binary with root-owned, non-writable ancestors."""
    root = installation_node_toolchain_root()
    if node_binary != root / "bin/node":
        return False
    return is_protected_executable(node_binary)
