"""File identity and export manifest helpers for workspace exports."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path

from core.workspaces.models import ExportManifest, FileIdentity


def build_file_identity(file_path: Path, workspace_root: Path) -> FileIdentity:
    """Build stable file identity metadata for one file inside a workspace root."""
    resolved_file_path = file_path.resolve()
    resolved_workspace_root = workspace_root.resolve()
    relative_path = resolved_file_path.relative_to(resolved_workspace_root).as_posix()
    stat_result = resolved_file_path.stat()
    content_hash = hashlib.sha256(resolved_file_path.read_bytes()).hexdigest()
    file_id = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()
    return FileIdentity(
        file_id=file_id,
        relative_path=relative_path,
        content_hash=content_hash,
        created_at=datetime.fromtimestamp(stat_result.st_ctime, tz=UTC).isoformat(),
        updated_at=datetime.fromtimestamp(stat_result.st_mtime, tz=UTC).isoformat(),
    )


def build_export_manifest(workspace_id: str, workspace_root: Path, files: list[Path]) -> ExportManifest:
    """Build a canonical workspace export manifest."""
    identities = [build_file_identity(file_path=file_path, workspace_root=workspace_root) for file_path in sorted(files)]
    return ExportManifest(
        manifest_version="1",
        workspace_id=workspace_id,
        exported_at=datetime.now(tz=UTC).isoformat(),
        files=identities,
    )

