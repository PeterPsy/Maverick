"""Compatibility facade for runtime-local Maverick CLI wrappers."""

from __future__ import annotations

from pathlib import Path

from core.runtime.runtime_cli_wrapper import (
    refresh_runtime_maverick_wrappers,
    runtime_maverick_wrapper_source,
    write_runtime_maverick_wrapper,
)


def refresh_workspace_maverick_wrappers(repository_root: Path) -> list[Path]:
    return refresh_runtime_maverick_wrappers(repository_root)


def _write_workspace_maverick_wrapper(path: Path) -> None:
    write_runtime_maverick_wrapper(path)


def _workspace_maverick_wrapper_source() -> str:
    return runtime_maverick_wrapper_source()
