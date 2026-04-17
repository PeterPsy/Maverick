"""Workspace-domain models for path contracts and export metadata."""

from __future__ import annotations

from dataclasses import dataclass

from pathlib import Path


@dataclass(frozen=True)
class WorkspacePaths:
    """Canonical filesystem roots for one workspace."""

    workspace_id: str
    root: Path
    apps: Path
    data: Path
    logs: Path
    runtime: Path
    storage: Path
    uploaded_storage: Path
    generated_storage: Path
    tests: Path
    tmp: Path


@dataclass(frozen=True)
class FileIdentity:
    """Stable metadata for one exported workspace file."""

    file_id: str
    relative_path: str
    content_hash: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ExportManifest:
    """Canonical export manifest envelope for one workspace snapshot."""

    manifest_version: str
    workspace_id: str
    exported_at: str
    files: list[FileIdentity]

