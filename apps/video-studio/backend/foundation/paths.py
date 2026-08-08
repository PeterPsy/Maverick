"""Fail-closed path handling for the app-owned workspace data root."""

from __future__ import annotations

from pathlib import Path


class DataRootError(ValueError):
    """Raised when an app-owned data path is absent or escapes its root."""


def resolve_data_root(data_root: str | Path, *, create: bool = False) -> Path:
    """Resolve one absolute data root supplied by Maverick's app binding."""
    raw = str(data_root).strip()
    if not raw:
        raise DataRootError("Video Studio requires a non-empty app data root.")
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise DataRootError("Video Studio app data root must be absolute.")
    if ".." in candidate.parts:
        raise DataRootError("Video Studio app data root must not contain traversal segments.")
    if candidate.is_symlink():
        raise DataRootError("Video Studio app data root must not be a symbolic link.")
    if create:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise DataRootError("Video Studio app data root could not be created.") from error
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise DataRootError("Video Studio app data root does not exist.") from error
    if not resolved.is_dir():
        raise DataRootError("Video Studio app data root must be a directory.")
    return resolved


def safe_data_path(
    data_root: str | Path,
    relative_path: str | Path,
    *,
    create_root: bool = False,
) -> Path:
    """Resolve a relative path and prove that it remains below data_root."""
    root = resolve_data_root(data_root, create=create_root)
    raw_relative = str(relative_path).strip()
    if not raw_relative:
        raise DataRootError("Video Studio data path must not be empty.")
    relative = Path(raw_relative)
    if relative.is_absolute():
        raise DataRootError("Video Studio data paths must be relative.")
    if ".." in relative.parts:
        raise DataRootError("Video Studio data paths must not contain traversal segments.")
    lexical = root / relative
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise DataRootError("Video Studio data paths must not traverse symbolic links.")
    try:
        resolved = lexical.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as error:
        raise DataRootError("Video Studio data path could not be resolved.") from error
    if resolved != root and root not in resolved.parents:
        raise DataRootError("Video Studio data path escapes the app data root.")
    return resolved
