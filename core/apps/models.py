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
AppFrontendRole = Literal["workspace", "supporting", "none"]
HealthMode = Literal["none", "hook"]
InstallFailureMode = Literal["block_activation", "mark_failed"]
MigrateFailureMode = Literal["preserve_data_mark_unhealthy", "block_activation"]
ImportFailureMode = Literal["preserve_payload_mark_failed", "block_activation"]
StorageKind = Literal["sqlite", "sqlite+files", "duckdb", "json", "jsonl", "mixed"]
StorageIndexKind = Literal["embedded", "file_based"]
WidgetFrontendKind = Literal["iframe"]
AppRequiredInterfaceCardinality = Literal["one", "many"]
HttpSidecarRuntime = Literal["python", "node", "generic"]
HttpSidecarPort = int | Literal["auto"]
HttpSidecarSandboxMode = Literal["required"]
HttpSidecarNetworkMode = Literal["isolated"]
HttpSidecarTransport = Literal["unix_relay"]
HttpSidecarBrowserOriginMode = Literal["isolated"]
HttpSidecarBrowserCspProfile = Literal["self_hosted_web_app"]
HttpSidecarEntrypointSurface = Literal["backend", "cli", "mcp", "reference"]
AppProviderCredentialSource = Literal["none", "core-vault"]
AppReferenceCacheScope = Literal["session", "workspace_user"]


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
    cache_scope: AppReferenceCacheScope = "session"


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
class AppPresentationDeclaration:
    """Describe app presentation semantics for user-facing shell surfaces."""

    frontend_role: AppFrontendRole


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
    receive_cleanup_callbacks: bool = False


@dataclass(frozen=True)
class AppHostPermissionDeclaration:
    """Describe host-level operational visibility an app may request."""

    telemetry: bool


@dataclass(frozen=True)
class AppProviderPermissionDeclaration:
    """Describe core-governed provider access one app may request."""

    model_proxy: bool
    credential_source: AppProviderCredentialSource
    deliver_secrets_to_app: bool


@dataclass(frozen=True)
class AppPermissionsDeclaration:
    """Describe platform-governed operational permissions requested by one app."""

    secrets: AppSecretPermissionDeclaration
    network: AppNetworkPermissionDeclaration
    runtime: AppRuntimePermissionDeclaration
    host: AppHostPermissionDeclaration
    providers: AppProviderPermissionDeclaration


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
    """Timeout values for app-owned subprocess entrypoints."""

    backend_seconds: int
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
class HttpSidecarRouteRule:
    """Describe one method/path route rule for an app-owned HTTP sidecar."""

    method: str | None
    path_template: str
    static_tree: bool


@dataclass(frozen=True)
class HttpSidecarRoutePolicy:
    """Describe which sidecar routes are proxied, intercepted, or blocked."""

    pass_through: list[HttpSidecarRouteRule]
    handled_by_core: list[HttpSidecarRouteRule]
    blocked: list[HttpSidecarRouteRule]


@dataclass(frozen=True)
class HttpSidecarBindSpec:
    """Describe the loopback bind target for one app-owned HTTP sidecar."""

    host: str
    port: HttpSidecarPort


@dataclass(frozen=True)
class HttpSidecarHealthSpec:
    """Describe how the core checks sidecar readiness."""

    path: str
    timeout_ms: int


@dataclass(frozen=True)
class HttpSidecarProxySpec:
    """Describe the governed frontend proxy for one app-owned HTTP sidecar."""

    mount: str
    streaming: bool
    sse: bool
    websocket: bool
    route_policy: HttpSidecarRoutePolicy


@dataclass(frozen=True)
class HttpSidecarLogSpec:
    """Describe workspace-log paths for sidecar process output."""

    stdout: str
    stderr: str


@dataclass(frozen=True)
class HttpSidecarResourceLimits:
    """Bound resources enforced for one confined sidecar process group."""

    memory_bytes: int
    open_files: int
    request_concurrency: int


@dataclass(frozen=True)
class HttpSidecarProcessPolicy:
    """Describe the generic fail-closed process boundary for one sidecar."""

    inherit_host_env: bool
    sandbox: HttpSidecarSandboxMode
    bundle_read_only: bool
    workspace_data_write: bool
    network: HttpSidecarNetworkMode
    transport: HttpSidecarTransport
    outbound: list[str]
    limits: HttpSidecarResourceLimits


@dataclass(frozen=True)
class HttpSidecarBrowserOriginSpec:
    """Declare a core-routed isolated browser origin for one sidecar."""

    mode: HttpSidecarBrowserOriginMode
    csp_profile: HttpSidecarBrowserCspProfile
    frame_ancestors: list[str]
    connect_src: list[str]
    immutable_asset_prefixes: list[str]
    sandboxed_frame_resource_prefixes: list[str]


@dataclass(frozen=True)
class HttpSidecarEntrypointSurfaceSpec:
    """Declare exact sidecar routes available to one app entrypoint surface."""

    surface: HttpSidecarEntrypointSurface
    routes: list[HttpSidecarRouteRule]


@dataclass(frozen=True)
class HttpSidecarEntrypointAccessSpec:
    """Declare one bounded, invocation-scoped sidecar capability profile."""

    ttl_seconds: int
    request_budget: int
    max_request_body_bytes: int
    max_response_body_bytes: int
    streaming: bool
    surfaces: list[HttpSidecarEntrypointSurfaceSpec]


@dataclass(frozen=True)
class HttpSidecarArtifactMountSpec:
    """Declare one platform-owned artifact namespace mounted read-only."""

    artifact_id: str
    mount_path: str


@dataclass(frozen=True)
class HttpSidecarRootFilesystemSpec:
    """Select a verified artifact subtree as the sidecar's read-only root."""

    artifact_id: str
    subpath: str


@dataclass(frozen=True)
class HttpSidecarDataMountSpec:
    """Select the only app-data subtree writable inside one sidecar."""

    subpath: str


@dataclass(frozen=True)
class HttpSidecarHostPrepareSpec:
    """Declare a bounded host hook run immediately before a fresh launch."""

    entrypoint: str
    timeout_seconds: int
    environment_keys: list[str]


@dataclass(frozen=True)
class HttpSidecarModelAccessSpec:
    """Request an optional Core-owned naked-model transport for one sidecar."""

    api: bool
    cli: list[str]
    required: bool


@dataclass(frozen=True)
class HttpSidecarPrewarmSpec:
    """Declare when Core should start and retain one sidecar."""

    on_core_start: bool
    on_install: bool
    on_activation: bool
    keep_alive: bool


@dataclass(frozen=True)
class HttpSidecarDiagnosticsSpec:
    """Declare a bounded startup-status file inside app data."""

    status_file: str


@dataclass(frozen=True)
class HttpSidecarSpec:
    """Describe one app-owned local HTTP sidecar process."""

    service_id: str
    runtime: HttpSidecarRuntime
    command: list[str]
    working_directory: str
    package_manager: str | None
    env: dict[str, str]
    process_policy: HttpSidecarProcessPolicy
    artifact_mounts: list[HttpSidecarArtifactMountSpec]
    root_filesystem: HttpSidecarRootFilesystemSpec | None
    model_access: HttpSidecarModelAccessSpec | None
    prewarm: HttpSidecarPrewarmSpec | None
    diagnostics: HttpSidecarDiagnosticsSpec | None
    browser_origin: HttpSidecarBrowserOriginSpec | None
    entrypoint_access: HttpSidecarEntrypointAccessSpec | None
    bind: HttpSidecarBindSpec
    health: HttpSidecarHealthSpec
    proxy: HttpSidecarProxySpec | None
    logs: HttpSidecarLogSpec | None
    data_mount: HttpSidecarDataMountSpec | None = None
    host_prepare: HttpSidecarHostPrepareSpec | None = None


@dataclass(frozen=True)
class AppServicesDeclaration:
    """Describe app-owned long-running services managed by the core."""

    http_sidecars: list[HttpSidecarSpec]


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
    presentation: AppPresentationDeclaration
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
    services: AppServicesDeclaration


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
class WorkspaceAppSidecarQuarantineRecord:
    """Core-owned durable execution fence for one workspace app's sidecars."""

    quarantine_id: str
    workspace_id: str
    app_id: str
    reason: str
    active: bool
    created_at: str
    updated_at: str


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
