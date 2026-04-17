"""App-hosting models for Phase 4."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.execution_policy.models import ExecutionMode


AppSourceKind = Literal["platform", "external_bundle", "workspace_local_project"]
WorkspaceAppStatus = Literal["installed", "enabled", "disabled", "failed", "updating", "rolled_back"]
HealthMode = Literal["none", "hook"]
InstallFailureMode = Literal["block_activation", "mark_failed"]
MigrateFailureMode = Literal["preserve_data_mark_unhealthy", "block_activation"]
ImportFailureMode = Literal["preserve_payload_mark_failed", "block_activation"]


@dataclass(frozen=True)
class AppCompatibilityDescriptor:
    """Minimal compatibility metadata used by the app-hosting control plane."""

    contract_version: str
    minimum_core_version: str
    supported_workspace_modes: list[ExecutionMode] | None


@dataclass(frozen=True)
class AppEntrypoints:
    """Executable entrypoints exposed by the app contract."""

    mcp: str | None
    cli: str | None
    skills_root: str | None
    hooks: dict[str, str]


@dataclass(frozen=True)
class AppHookTimeouts:
    """Timeout values for lifecycle and health operations."""

    install_seconds: int
    migrate_seconds: int
    health_check_seconds: int
    export_seconds: int
    import_seconds: int


@dataclass(frozen=True)
class AppFailureSemantics:
    """Failure semantics declared by the app contract."""

    install_failure: InstallFailureMode
    migrate_failure: MigrateFailureMode
    import_failure: ImportFailureMode


@dataclass(frozen=True)
class AppHealthContract:
    """Health-check behavior declared by the app contract."""

    mode: HealthMode
    degraded_on_failure: bool


@dataclass(frozen=True)
class AppRollbackSupport:
    """Rollback or recovery guarantees declared by the app contract."""

    bundle: bool
    data: bool
    repair_only: bool


@dataclass(frozen=True)
class AppContractDescriptor:
    """Executable app contract metadata used by the core."""

    compatibility: AppCompatibilityDescriptor
    entrypoints: AppEntrypoints
    hook_timeouts: AppHookTimeouts
    failure_semantics: AppFailureSemantics
    health_contract: AppHealthContract
    rollback_support: AppRollbackSupport


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
    contract: AppContractDescriptor
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
    contract: AppContractDescriptor
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
