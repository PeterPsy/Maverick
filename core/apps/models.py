"""App-hosting models for Phase 4."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.execution_policy.models import ExecutionMode


AppSourceKind = Literal["platform", "external_bundle", "workspace_local_project"]
WorkspaceAppStatus = Literal["installed", "enabled", "disabled", "failed", "updating", "rolled_back"]


@dataclass(frozen=True)
class AppCompatibilityDescriptor:
    """Minimal compatibility metadata used by the app-hosting control plane."""

    contract_version: str
    minimum_core_version: str
    supported_workspace_modes: list[ExecutionMode] | None


@dataclass(frozen=True)
class AppSourceRecord:
    """Installation-level app source metadata for platform or external app artifacts."""

    source_id: str
    app_id: str
    name: str
    version: str
    description: str
    publisher: str
    source_kind: Literal["platform", "external_bundle"]
    source_path: str
    compatibility: AppCompatibilityDescriptor
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class WorkspaceLocalAppProjectRecord:
    """Workspace-owned local app project metadata."""

    project_id: str
    workspace_id: str
    app_id: str
    name: str
    version: str
    description: str
    publisher: str
    project_root: str
    compatibility: AppCompatibilityDescriptor
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class WorkspaceAppBindingRecord:
    """Workspace-scoped installation and enablement record for one app."""

    binding_id: str
    workspace_id: str
    app_id: str
    source_record_id: str
    source_kind: AppSourceKind
    status: WorkspaceAppStatus
    active_version: str
    data_root: str
    installed_at: str
    updated_at: str


@dataclass(frozen=True)
class WorkspaceAppReinstallResult:
    """Describe one reinstall outcome and any recovery actions requested."""

    binding: WorkspaceAppBindingRecord
    reused_existing_data_root: bool
    validation_requested: bool
    repair_requested: bool
    migration_requested: bool
