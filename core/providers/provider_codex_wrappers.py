"""Compatibility facade for runtime-local Loopino CLI wrappers."""

from __future__ import annotations

from pathlib import Path

from core.runtime.runtime_cli_wrapper import (
    refresh_runtime_loopino_wrappers,
    runtime_loopino_wrapper_source,
    write_runtime_loopino_wrapper,
)


def refresh_workspace_loopino_wrappers(repository_root: Path) -> list[Path]:
    return refresh_runtime_loopino_wrappers(repository_root)


def _write_workspace_loopino_wrapper(path: Path) -> None:
    write_runtime_loopino_wrapper(path)


def _workspace_loopino_wrapper_source() -> str:
    return runtime_loopino_wrapper_source()
