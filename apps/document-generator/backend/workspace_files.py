"""Workspace storage path resolution for Document Generator."""

from __future__ import annotations

from pathlib import Path

from errors import DocumentValidationError


def resolve_workspace_file(uploaded_root: Path | None, generated_root: Path, workspace_relative_path: str) -> Path:
    """Resolve a workspace-relative storage file without allowing path escape."""
    if "\x00" in workspace_relative_path:
        raise DocumentValidationError("workspace_relative_path contains an invalid character.")
    if workspace_relative_path.startswith("storage/generated/"):
        return _resolve_under_root(generated_root, workspace_relative_path.removeprefix("storage/generated/"))
    if workspace_relative_path.startswith("storage/uploaded/"):
        if uploaded_root is None:
            raise DocumentValidationError("uploaded storage is unavailable for this surface.")
        return _resolve_under_root(uploaded_root, workspace_relative_path.removeprefix("storage/uploaded/"))
    raise DocumentValidationError("workspace_relative_path must be under storage/generated or storage/uploaded.")


def workspace_relative_generated_path(path: Path, generated_root: Path) -> str:
    """Return a storage/generated-relative path for a file below generated storage."""
    root = generated_root.resolve()
    target = path.resolve()
    if root != target and root not in target.parents:
        raise DocumentValidationError("generated output path escapes generated storage.")
    return f"storage/generated/{target.relative_to(root).as_posix()}"


def _resolve_under_root(root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise DocumentValidationError("workspace_relative_path escapes workspace storage.")
    root_path = root.resolve()
    target = (root_path / relative).resolve()
    if root_path != target and root_path not in target.parents:
        raise DocumentValidationError("workspace_relative_path escapes workspace storage.")
    if not target.is_file():
        raise DocumentValidationError("workspace file does not exist.")
    return target
