"""App-hosting and app-contract models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.execution_policy.models import ExecutionMode
from core.identity.models import PlatformRole


AppSourceKind = Literal["platform", "external_bundle", "workspace_local_project"]
WorkspaceAppStatus = Literal["installed", "enabled", "disabled", "failed", "updating", "rolled_back"]
AppDistributionMode = Literal["sealed", "source_available", "workspace_local"]
AppSourceAccess = Literal["none", "read_only", "forkable", "editable"]
HealthMode = Literal["none", "hook"]
InstallFailureMode = Literal["block_activation", "mark_failed"]
MigrateFailureMode = Literal["preserve_data_mark_unhealthy", "block_activation"]
ImportFailureMode = Literal["preserve_payload_mark_failed", "block_activation"]
StorageKind = Literal["sqlite", "sqlite+files", "duckdb", "json", "jsonl", "mixed"]
StorageIndexKind = Literal["embedded", "file_based"]
WidgetFrontendKind = Literal["iframe"]
AppRequiredInterfaceCardinality = Literal["one", "many"]


@dataclass(frozen=True)
class AppCompatibilityDescriptor:
    """Minimal compatibility metadata used by the app-hosting control plane."""

    contract_version: str
    minimum_core_version: str
    supported_workspace_modes: list[ExecutionMode] | None


@dataclass(frozen=True)
class AppStorageIndices:
    """Describe how one app stores secondary indices when it uses them."""

    kind: StorageIndexKind


@dataclass(frozen=True)
class AppStorageDeclaration:
    """Describe the app-owned storage model declared by the contract."""

    storage_kind: StorageKind
    data_schema_version: str
    primary_paths: list[str]
    indices: AppStorageIndices | None
    supports_export: bool
    supports_import: bool
    supports_migrations: bool


@dataclass(frozen=True)
class AppCapabilities:
    """Describe the official capability surfaces exposed by one app."""

    mcp_tools: list[str]
    cli_commands: list[str]
    skills: list[str]
    views: list[str]
    data_events: list["AppDataEventDeclaration"]
    view_surfaces: list["AppViewSurfaceDeclaration"]
    reference_entities: list["AppReferenceEntityDeclaration"]


@dataclass(frozen=True)
class AppDataEventDeclaration:
    """Describe one app-owned mutable data resource that emits live-change events."""

    resource: str
    description: str


@dataclass(frozen=True)
class AppViewStateActionDeclaration:
    """Describe one app-owned view-state action and whether it follows a shared contract."""

    action: str
    standard: bool
    description: str


@dataclass(frozen=True)
class AppViewSurfaceDeclaration:
    """Describe an app-owned UI surface that can render curated entity sets."""

    view_id: str
    display_name: str
    entity_types: list[str]
    state_actions: list[AppViewStateActionDeclaration]
    supports_custom_view: bool
    supports_filter_refinement: bool


@dataclass(frozen=True)
class AppReferenceEntityDeclaration:
    """Describe one app-owned entity type that other apps may reference."""

    entity_type: str
    display_name: str
    searchable: bool
    resolvable: bool
    summarizable: bool
    deep_link_supported: bool


@dataclass(frozen=True)
class AppDistributionDeclaration:
    """Describe whether app source is sealed, source-available, or workspace-local."""

    mode: AppDistributionMode
    source_access: AppSourceAccess


@dataclass(frozen=True)
class AppVisibilityDeclaration:
    """Describe which platform users may see and mount one app."""

    platform_roles: list[PlatformRole] | None
    workspace_roles: list[Literal["admin", "member"]] | None = None
    capabilities: list[str] | None = None


@dataclass(frozen=True)
class AppSecretPermissionDeclaration:
    """Describe app-scoped secret bindings one app may request or receive."""

    read: list[str]
    write: list[str]


@dataclass(frozen=True)
class AppNetworkPermissionDeclaration:
    """Describe outbound network targets an app may request."""

    outbound: list[str]


@dataclass(frozen=True)
class AppRuntimePermissionDeclaration:
    """Describe runtime control-plane operations an app may request."""

    create_sessions: bool
    cleanup_sessions: bool


@dataclass(frozen=True)
class AppHostPermissionDeclaration:
    """Describe host-level operational visibility an app may request."""

    telemetry: bool


@dataclass(frozen=True)
class AppPermissionsDeclaration:
    """Describe platform-governed operational permissions requested by one app."""

    secrets: AppSecretPermissionDeclaration
    network: AppNetworkPermissionDeclaration
    runtime: AppRuntimePermissionDeclaration
    host: AppHostPermissionDeclaration


@dataclass(frozen=True)
class AppLifecycleDeclaration:
    """Describe which lifecycle operations the app claims to support."""

    install: bool
    upgrade: bool
    uninstall: bool
    migrate: bool
    export: bool
    import_data: bool
    validate_after_import: bool
    repair_after_import: bool
    health_check: bool


@dataclass(frozen=True)
class AppEntrypoints:
    """Executable entrypoints exposed by the app contract."""

    mcp: str | None
    cli: str | None
    backend: str | None
    frontend: str | None
    skills_root: str | None
    hooks: dict[str, str]


@dataclass(frozen=True)
class AppHookTimeouts:
    """Timeout values for lifecycle and health operations."""

    install_seconds: int
    upgrade_seconds: int
    migrate_seconds: int
    export_seconds: int
    import_seconds: int
    validate_after_import_seconds: int
    repair_after_import_seconds: int
    health_check_seconds: int


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
class WidgetFrontendDeclaration:
    """Describe how the core mounts one app-owned embeddable widget frontend."""

    kind: WidgetFrontendKind
    mount: str
    spa_fallback: bool


@dataclass(frozen=True)
class WidgetActionDeclaration:
    """Describe which official owner-app surfaces a widget may use."""

    backend: bool
    mcp: bool
    cli: bool


@dataclass(frozen=True)
class WidgetDeclaration:
    """Describe one app-owned embeddable widget surface."""

    widget_id: str
    host: str
    content_kinds: list[str]
    frontend: WidgetFrontendDeclaration
    actions: WidgetActionDeclaration


@dataclass(frozen=True)
class AppProvidedInterfaceDeclaration:
    """Describe one generic app interface provided by this app."""

    interface: str
    version: str
    description: str
    surfaces: list[str]


@dataclass(frozen=True)
class AppRequiredInterfaceDeclaration:
    """Describe one generic app interface required by this app."""

    alias: str
    interface: str
    version: str
    required: bool
    cardinality: AppRequiredInterfaceCardinality
    description: str


@dataclass(frozen=True)
class AppContractDescriptor:
    """Executable app contract metadata used by the core."""

    provides: list[AppProvidedInterfaceDeclaration]
    requires: list[AppRequiredInterfaceDeclaration]
    distribution: AppDistributionDeclaration
    visibility: AppVisibilityDeclaration
    permissions: AppPermissionsDeclaration
    compatibility: AppCompatibilityDescriptor
    storage: AppStorageDeclaration
    capabilities: AppCapabilities
    lifecycle: AppLifecycleDeclaration
    entrypoints: AppEntrypoints
    hook_timeouts: AppHookTimeouts
    failure_semantics: AppFailureSemantics
    health_contract: AppHealthContract
    rollback_support: AppRollbackSupport
    widgets: list[WidgetDeclaration]


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
    owner_user_id: str | None = None
    owner_username: str | None = None
    promoted_from_workspace_id: str | None = None
    promoted_from_project_id: str | None = None
    public_app_id: str | None = None


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
    owner_user_id: str | None = None
    owner_username: str | None = None
    forked_from_source_id: str | None = None
    forked_from_version: str | None = None
    public_app_id: str | None = None
    local_app_id: str | None = None


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
    public_app_id: str | None = None
    local_app_id: str | None = None
    mount_app_id: str | None = None


@dataclass(frozen=True)
class WorkspaceAppDependencySelectionRecord:
    """Workspace-scoped provider selection for one consumer app requirement alias."""

    selection_id: str
    workspace_id: str
    consumer_app_id: str
    alias: str
    provider_app_ids: list[str]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AppDataStateRecord:
    """Persisted app-owned metadata about the current data plane in one workspace."""

    app_id: str
    app_version: str
    data_schema_version: str
    updated_at: str


@dataclass(frozen=True)
class WorkspaceAppReinstallResult:
    """Describe one reinstall outcome and any recovery actions requested."""

    binding: WorkspaceAppBindingRecord
    reused_existing_data_root: bool
    validation_requested: bool
    repair_requested: bool
    migration_requested: bool


@dataclass(frozen=True)
class WorkspaceAppUpgradeResult:
    """Describe one app upgrade attempt and whether rollback was required."""

    binding: WorkspaceAppBindingRecord
    previous_version: str
    target_version: str
    migration_ran: bool
    rolled_back: bool


@dataclass(frozen=True)
class AppHookContext:
    """Structured context passed to app lifecycle and health hooks."""

    workspace_id: str
    workspace_root: str
    export_root: str
    app_id: str
    data_root: str
    uploaded_storage_root: str
    generated_storage_root: str
    source_kind: AppSourceKind
    source_record_id: str
    hook_name: str


@dataclass(frozen=True)
class ParsedAppContract:
    """Normalized app contract parsed from one app source root."""

    app_id: str
    name: str
    version: str
    description: str
    publisher: str
    contract: AppContractDescriptor
