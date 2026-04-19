"""Workspace-domain records and filesystem contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from core.apps.models import AppSourceKind


WorkspaceStatus = Literal["active", "archived"]
MembershipRole = Literal["admin", "member"]
MembershipStatus = Literal["active", "inactive"]
FileRole = Literal["uploaded", "generated", "app_data", "other"]
WorkspaceExportParticipationStrategy = Literal["filesystem_snapshot", "export_hook"]


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
class WorkspaceRecord:
    """Canonical workspace registry record."""

    workspace_id: str
    slug: str
    name: str
    description: str | None
    status: WorkspaceStatus
    created_by_user_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class WorkspaceMembershipRecord:
    """Explicit user membership in one workspace."""

    membership_id: str
    workspace_id: str
    user_id: str
    role: MembershipRole
    status: MembershipStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class WorkspaceGovernanceRecord:
    """Workspace-scoped governance switches."""

    workspace_id: str
    allow_app_installation: bool
    allow_agent_creation: bool
    allow_agent_management: bool
    allow_custom_apps: bool
    allow_full_access_runtime: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class WorkspaceQuotaRecord:
    """Workspace-scoped operational limits."""

    workspace_id: str
    max_agent_instances: int | None
    max_installed_apps: int | None
    max_storage_bytes: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ActiveWorkspaceSelection:
    """The active workspace selected for one user."""

    user_id: str
    workspace_id: str
    updated_at: datetime


@dataclass(frozen=True)
class FileIdentity:
    """Stable metadata for one exported workspace file."""

    file_id: str
    relative_path: str
    content_hash: str
    file_role: FileRole
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ExportedAppReference:
    """Minimal app reference metadata required for deterministic restore."""

    app_id: str
    version: str
    data_schema_version: str
    status: str
    source_kind: AppSourceKind
    source_record_id: str
    forked_from_source_id: str | None = None
    forked_from_version: str | None = None


@dataclass(frozen=True)
class WorkspaceExportParticipant:
    """Describe how one installed workspace app participates in export."""

    app_id: str
    status: str
    version: str
    data_schema_version: str
    strategy: WorkspaceExportParticipationStrategy
    source_kind: AppSourceKind
    source_record_id: str
    export_hook_path: str | None
    forked_from_source_id: str | None = None
    forked_from_version: str | None = None


@dataclass(frozen=True)
class ExportManifest:
    """Canonical export manifest envelope for one workspace snapshot."""

    manifest_version: str
    workspace_id: str
    exported_at: str
    schema_versions: dict[str, str]
    known_apps: list[ExportedAppReference]
    files: list[FileIdentity]


@dataclass(frozen=True)
class WorkspaceExportBundle:
    """Carry the export manifest together with participation metadata."""

    manifest: ExportManifest
    participants: list[WorkspaceExportParticipant]
