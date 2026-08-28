"""Factory helpers for canonical app contract dataclasses."""

from __future__ import annotations

from pathlib import Path

from core.apps.contract_common import CURRENT_APP_CONTRACT_VERSION, _normalize_slug
from core.apps.models import (
    AppCapabilities,
    AppCompatibilityDescriptor,
    AppDataEventDeclaration,
    AppContractDescriptor,
    AppDistributionDeclaration,
    AppEntrypoints,
    AppFailureSemantics,
    AppHealthContract,
    AppHostPermissionDeclaration,
    AppHookTimeouts,
    AppLifecycleDeclaration,
    AppNetworkPermissionDeclaration,
    AppPermissionsDeclaration,
    AppPresentationDeclaration,
    AppProviderCredentialSource,
    AppProviderPermissionDeclaration,
    AppProvidedInterfaceDeclaration,
    AppReferenceCacheScope,
    AppReferenceEntityDeclaration,
    AppRequiredInterfaceDeclaration,
    AppRollbackSupport,
    AppRuntimePermissionDeclaration,
    AppSecretPermissionDeclaration,
    AppServicesDeclaration,
    AppStorageDeclaration,
    AppStorageIndices,
    AppViewStateActionDeclaration,
    AppViewSurfaceDeclaration,
    AppVisibilityDeclaration,
    HttpSidecarBindSpec,
    HttpSidecarDiagnosticsSpec,
    HttpSidecarArtifactMountSpec,
    HttpSidecarBrowserOriginSpec,
    HttpSidecarEntrypointAccessSpec,
    HttpSidecarEntrypointSurfaceSpec,
    HttpSidecarHealthSpec,
    HttpSidecarLogSpec,
    HttpSidecarModelAccessSpec,
    HttpSidecarProcessPolicy,
    HttpSidecarPrewarmSpec,
    HttpSidecarProxySpec,
    HttpSidecarResourceLimits,
    HttpSidecarRootFilesystemSpec,
    HttpSidecarRoutePolicy,
    HttpSidecarRouteRule,
    HttpSidecarSpec,
    ParsedAppContract,
    WidgetActionDeclaration,
    WidgetDeclaration,
    WidgetFrontendDeclaration,
)
from core.execution_policy.models import ExecutionMode
from core.shared.version import current_core_version


def build_app_compatibility(
    *,
    contract_version: str = CURRENT_APP_CONTRACT_VERSION,
    minimum_core_version: str | None = None,
    supported_workspace_modes: list[ExecutionMode] | None = None,
) -> AppCompatibilityDescriptor:
    """Build one app compatibility descriptor."""
    return AppCompatibilityDescriptor(
        contract_version=contract_version,
        minimum_core_version=minimum_core_version or current_core_version(start_path=Path(__file__)),
        supported_workspace_modes=supported_workspace_modes,
    )

def build_app_storage(
    *,
    storage_kind: str = "json",
    data_schema_version: str = "1",
    primary_paths: list[str] | None = None,
    indices_kind: str | None = None,
    supports_export: bool = True,
    supports_import: bool = True,
    supports_migrations: bool = False,
) -> AppStorageDeclaration:
    """Build one storage declaration."""
    indices = AppStorageIndices(kind=indices_kind) if indices_kind else None
    return AppStorageDeclaration(
        storage_kind=storage_kind,
        data_schema_version=data_schema_version,
        primary_paths=primary_paths or [],
        indices=indices,
        supports_export=supports_export,
        supports_import=supports_import,
        supports_migrations=supports_migrations,
    )

def build_app_capabilities(
    *,
    mcp_tools: list[str] | None = None,
    cli_commands: list[str] | None = None,
    skills: list[str] | None = None,
    views: list[str] | None = None,
    data_events: list[AppDataEventDeclaration] | None = None,
    view_surfaces: list[AppViewSurfaceDeclaration] | None = None,
    reference_entities: list[AppReferenceEntityDeclaration] | None = None,
) -> AppCapabilities:
    """Build one capability declaration."""
    return AppCapabilities(
        mcp_tools=mcp_tools or [],
        cli_commands=cli_commands or [],
        skills=skills or [],
        views=views or [],
        data_events=data_events or [],
        view_surfaces=view_surfaces or [],
        reference_entities=reference_entities or [],
    )

def build_view_surface_declaration(
    *,
    view_id: str,
    display_name: str,
    entity_types: list[str] | None = None,
    state_actions: list[AppViewStateActionDeclaration] | None = None,
    supports_custom_view: bool = False,
    supports_filter_refinement: bool = False,
) -> AppViewSurfaceDeclaration:
    """Build one view-composition capability declaration."""
    return AppViewSurfaceDeclaration(
        view_id=view_id,
        display_name=display_name,
        entity_types=entity_types or [],
        state_actions=state_actions or [],
        supports_custom_view=supports_custom_view,
        supports_filter_refinement=supports_filter_refinement,
    )

def build_view_state_action_declaration(
    *,
    action: str,
    standard: bool,
    description: str,
) -> AppViewStateActionDeclaration:
    """Build one view-state action declaration."""
    return AppViewStateActionDeclaration(
        action=action,
        standard=standard,
        description=description,
    )

def build_reference_entity_declaration(
    *,
    entity_type: str,
    display_name: str,
    searchable: bool = True,
    resolvable: bool = True,
    summarizable: bool = True,
    deep_link_supported: bool = True,
    cache_scope: AppReferenceCacheScope = "session",
) -> AppReferenceEntityDeclaration:
    """Build one referenceable entity capability declaration."""
    return AppReferenceEntityDeclaration(
        entity_type=entity_type,
        display_name=display_name,
        searchable=searchable,
        resolvable=resolvable,
        summarizable=summarizable,
        deep_link_supported=deep_link_supported,
        cache_scope=cache_scope,
    )

def build_app_distribution(
    *,
    mode: str = "sealed",
    source_access: str = "none",
) -> AppDistributionDeclaration:
    """Build one app distribution and mutability declaration."""
    return AppDistributionDeclaration(
        mode=mode,
        source_access=source_access,
    )

def build_app_presentation(
    *,
    frontend_role: str = "none",
) -> AppPresentationDeclaration:
    """Build one app presentation declaration for shell-facing UI semantics."""
    return AppPresentationDeclaration(frontend_role=frontend_role)

def build_app_permissions(
    *,
    secret_read: list[str] | None = None,
    secret_write: list[str] | None = None,
    network_outbound: list[str] | None = None,
    runtime_create_sessions: bool = False,
    runtime_cleanup_sessions: bool = False,
    runtime_receive_cleanup_callbacks: bool = False,
    host_telemetry: bool = False,
    provider_model_proxy: bool = False,
    provider_credential_source: AppProviderCredentialSource = "none",
    provider_deliver_secrets_to_app: bool = False,
) -> AppPermissionsDeclaration:
    """Build one operational permissions declaration."""
    return AppPermissionsDeclaration(
        secrets=AppSecretPermissionDeclaration(read=secret_read or [], write=secret_write or []),
        network=AppNetworkPermissionDeclaration(outbound=network_outbound or []),
        runtime=AppRuntimePermissionDeclaration(
            create_sessions=runtime_create_sessions,
            cleanup_sessions=runtime_cleanup_sessions,
            receive_cleanup_callbacks=runtime_receive_cleanup_callbacks,
        ),
        host=AppHostPermissionDeclaration(telemetry=host_telemetry),
        providers=AppProviderPermissionDeclaration(
            model_proxy=provider_model_proxy,
            credential_source=provider_credential_source,
            deliver_secrets_to_app=provider_deliver_secrets_to_app,
        ),
    )

def build_app_lifecycle(
    *,
    install: bool = True,
    upgrade: bool = True,
    uninstall: bool = True,
    migrate: bool = False,
    export: bool = False,
    import_data: bool = False,
    validate_after_import: bool = False,
    repair_after_import: bool = False,
    health_check: bool = False,
) -> AppLifecycleDeclaration:
    """Build one lifecycle declaration."""
    return AppLifecycleDeclaration(
        install=install,
        upgrade=upgrade,
        uninstall=uninstall,
        migrate=migrate,
        export=export,
        import_data=import_data,
        validate_after_import=validate_after_import,
        repair_after_import=repair_after_import,
        health_check=health_check,
    )

def build_app_entrypoints(
    *,
    mcp: str | None = None,
    cli: str | None = None,
    backend: str | None = None,
    frontend: str | None = None,
    skills_root: str | None = None,
    hooks: dict[str, str] | None = None,
) -> AppEntrypoints:
    """Build app executable entrypoints."""
    return AppEntrypoints(
        mcp=mcp,
        cli=cli,
        backend=backend,
        frontend=frontend,
        skills_root=skills_root,
        hooks=hooks or {},
    )

def build_app_hook_timeouts(
    *,
    backend_seconds: int = 30,
    install_seconds: int = 60,
    upgrade_seconds: int = 120,
    migrate_seconds: int = 300,
    export_seconds: int = 120,
    import_seconds: int = 120,
    validate_after_import_seconds: int = 60,
    repair_after_import_seconds: int = 180,
    health_check_seconds: int = 30,
) -> AppHookTimeouts:
    """Build lifecycle and health timeout metadata."""
    return AppHookTimeouts(
        backend_seconds=backend_seconds,
        install_seconds=install_seconds,
        upgrade_seconds=upgrade_seconds,
        migrate_seconds=migrate_seconds,
        export_seconds=export_seconds,
        import_seconds=import_seconds,
        validate_after_import_seconds=validate_after_import_seconds,
        repair_after_import_seconds=repair_after_import_seconds,
        health_check_seconds=health_check_seconds,
    )

def build_app_failure_semantics(
    *,
    install_failure: str = "block_activation",
    migrate_failure: str = "preserve_data_mark_unhealthy",
    import_failure: str = "preserve_payload_mark_failed",
) -> AppFailureSemantics:
    """Build failure-semantics metadata."""
    return AppFailureSemantics(
        install_failure=install_failure,
        migrate_failure=migrate_failure,
        import_failure=import_failure,
    )

def build_app_health_contract(*, mode: str = "none", degraded_on_failure: bool = True) -> AppHealthContract:
    """Build health-check contract metadata."""
    return AppHealthContract(mode=mode, degraded_on_failure=degraded_on_failure)

def build_app_rollback_support(*, bundle: bool = False, data: bool = False, repair_only: bool = False) -> AppRollbackSupport:
    """Build rollback support metadata."""
    return AppRollbackSupport(bundle=bundle, data=data, repair_only=repair_only)

def build_widget_frontend(*, kind: str = "iframe", mount: str, spa_fallback: bool = True) -> WidgetFrontendDeclaration:
    """Build one widget frontend declaration."""
    return WidgetFrontendDeclaration(kind=kind, mount=mount, spa_fallback=spa_fallback)

def build_widget_actions(*, backend: bool = False, mcp: bool = False, cli: bool = False) -> WidgetActionDeclaration:
    """Build one widget action declaration."""
    return WidgetActionDeclaration(backend=backend, mcp=mcp, cli=cli)

def build_widget_declaration(
    *,
    widget_id: str,
    host: str,
    content_kinds: list[str],
    frontend: WidgetFrontendDeclaration,
    actions: WidgetActionDeclaration | None = None,
) -> WidgetDeclaration:
    """Build one app-owned widget declaration."""
    return WidgetDeclaration(
        widget_id=widget_id,
        host=host,
        content_kinds=content_kinds,
        frontend=frontend,
        actions=actions or build_widget_actions(),
    )


def build_http_sidecar_route_rule(
    *,
    path_template: str,
    method: str | None = None,
    static_tree: bool = False,
) -> HttpSidecarRouteRule:
    """Build one HTTP sidecar route-policy rule."""
    return HttpSidecarRouteRule(method=method, path_template=path_template, static_tree=static_tree)


def build_http_sidecar_route_policy(
    *,
    pass_through: list[HttpSidecarRouteRule] | None = None,
    handled_by_core: list[HttpSidecarRouteRule] | None = None,
    blocked: list[HttpSidecarRouteRule] | None = None,
) -> HttpSidecarRoutePolicy:
    """Build one HTTP sidecar route policy."""
    return HttpSidecarRoutePolicy(
        pass_through=pass_through or [],
        handled_by_core=handled_by_core or [],
        blocked=blocked or [],
    )


def build_http_sidecar_spec(
    *,
    service_id: str,
    runtime: str = "generic",
    command: list[str],
    working_directory: str = ".",
    package_manager: str | None = None,
    env: dict[str, str] | None = None,
    process_policy: HttpSidecarProcessPolicy | None = None,
    artifact_mounts: list[HttpSidecarArtifactMountSpec] | None = None,
    root_filesystem: HttpSidecarRootFilesystemSpec | None = None,
    model_access: HttpSidecarModelAccessSpec | None = None,
    prewarm: HttpSidecarPrewarmSpec | None = None,
    diagnostics: HttpSidecarDiagnosticsSpec | None = None,
    browser_origin: HttpSidecarBrowserOriginSpec | None = None,
    entrypoint_access: HttpSidecarEntrypointAccessSpec | None = None,
    bind: HttpSidecarBindSpec | None = None,
    health: HttpSidecarHealthSpec | None = None,
    proxy: HttpSidecarProxySpec | None = None,
    logs: HttpSidecarLogSpec | None = None,
) -> HttpSidecarSpec:
    """Build one app-owned HTTP sidecar declaration."""
    return HttpSidecarSpec(
        service_id=service_id,
        runtime=runtime,
        package_manager=package_manager,
        working_directory=working_directory,
        command=command,
        env=env or {},
        process_policy=process_policy or build_http_sidecar_process_policy(),
        artifact_mounts=artifact_mounts or [],
        root_filesystem=root_filesystem,
        model_access=model_access,
        prewarm=prewarm,
        diagnostics=diagnostics,
        browser_origin=browser_origin,
        entrypoint_access=entrypoint_access,
        bind=bind or HttpSidecarBindSpec(host="127.0.0.1", port="auto"),
        health=health or HttpSidecarHealthSpec(path="/health", timeout_ms=30000),
        proxy=proxy,
        logs=logs,
    )


def build_http_sidecar_artifact_mount(*, artifact_id: str) -> HttpSidecarArtifactMountSpec:
    """Build one fixed platform-owned sidecar artifact mount."""
    return HttpSidecarArtifactMountSpec(
        artifact_id=artifact_id,
        mount_path=f"/artifacts/{artifact_id}",
    )


def build_http_sidecar_root_filesystem(
    *, artifact_id: str, subpath: str
) -> HttpSidecarRootFilesystemSpec:
    """Build one artifact-backed, read-only sidecar execution root."""
    return HttpSidecarRootFilesystemSpec(artifact_id=artifact_id, subpath=subpath)


def build_http_sidecar_model_access(
    *, api: bool = True, cli: list[str] | None = None, required: bool = False
) -> HttpSidecarModelAccessSpec:
    """Build one optional, scoped naked-model sidecar capability request."""
    return HttpSidecarModelAccessSpec(api=api, cli=cli or [], required=required)


def build_http_sidecar_prewarm(
    *,
    on_core_start: bool = True,
    on_install: bool = True,
    on_activation: bool = True,
    keep_alive: bool = True,
) -> HttpSidecarPrewarmSpec:
    """Build one declarative keep-alive prewarm policy."""
    return HttpSidecarPrewarmSpec(
        on_core_start=on_core_start,
        on_install=on_install,
        on_activation=on_activation,
        keep_alive=keep_alive,
    )


def build_http_sidecar_diagnostics(*, status_file: str) -> HttpSidecarDiagnosticsSpec:
    """Build one generic data-relative sidecar startup diagnostic declaration."""
    return HttpSidecarDiagnosticsSpec(status_file=status_file)


def build_http_sidecar_process_policy(
    *,
    memory_bytes: int = 4 * 1024 * 1024 * 1024,
    open_files: int = 1024,
    request_concurrency: int = 32,
) -> HttpSidecarProcessPolicy:
    """Build the only supported fail-closed sidecar process policy."""
    return HttpSidecarProcessPolicy(
        inherit_host_env=False,
        sandbox="required",
        bundle_read_only=True,
        workspace_data_write=True,
        network="isolated",
        transport="unix_relay",
        outbound=[],
        limits=HttpSidecarResourceLimits(
            memory_bytes=memory_bytes,
            open_files=open_files,
            request_concurrency=request_concurrency,
        ),
    )


def build_http_sidecar_browser_origin(
    *,
    immutable_asset_prefixes: list[str] | None = None,
) -> HttpSidecarBrowserOriginSpec:
    """Build the strict isolated-origin policy supported by core."""
    return HttpSidecarBrowserOriginSpec(
        mode="isolated",
        csp_profile="self_hosted_web_app",
        frame_ancestors=["platform"],
        connect_src=["self"],
        immutable_asset_prefixes=list(immutable_asset_prefixes or []),
    )


def build_http_sidecar_entrypoint_surface(
    *,
    surface: str,
    routes: list[HttpSidecarRouteRule],
) -> HttpSidecarEntrypointSurfaceSpec:
    """Build one entrypoint-specific exact route allowlist."""
    return HttpSidecarEntrypointSurfaceSpec(surface=surface, routes=routes)  # type: ignore[arg-type]


def build_http_sidecar_entrypoint_access(
    *,
    surfaces: list[HttpSidecarEntrypointSurfaceSpec],
    ttl_seconds: int = 30,
    request_budget: int = 16,
    max_request_body_bytes: int = 1024 * 1024,
    max_response_body_bytes: int = 8 * 1024 * 1024,
    streaming: bool = False,
) -> HttpSidecarEntrypointAccessSpec:
    """Build one synchronous invocation-scoped sidecar access profile."""
    return HttpSidecarEntrypointAccessSpec(
        ttl_seconds=ttl_seconds,
        request_budget=request_budget,
        max_request_body_bytes=max_request_body_bytes,
        max_response_body_bytes=max_response_body_bytes,
        streaming=streaming,
        surfaces=surfaces,
    )


def build_http_sidecar_proxy(
    *,
    mount: str,
    route_policy: HttpSidecarRoutePolicy,
    streaming: bool = False,
    sse: bool = False,
    websocket: bool = False,
) -> HttpSidecarProxySpec:
    """Build one governed HTTP sidecar proxy declaration."""
    return HttpSidecarProxySpec(
        mount=mount,
        streaming=streaming,
        sse=sse,
        websocket=websocket,
        route_policy=route_policy,
    )


def build_http_sidecar_logs(*, stdout: str, stderr: str) -> HttpSidecarLogSpec:
    """Build one workspace log declaration for sidecar output."""
    return HttpSidecarLogSpec(stdout=stdout, stderr=stderr)


def build_app_services(*, http_sidecars: list[HttpSidecarSpec] | None = None) -> AppServicesDeclaration:
    """Build app-owned long-running service declarations."""
    return AppServicesDeclaration(http_sidecars=http_sidecars or [])

def build_provided_interface_declaration(
    *,
    interface: str,
    version: str = "1",
    description: str,
    surfaces: list[str] | None = None,
) -> AppProvidedInterfaceDeclaration:
    """Build one generic provided-interface declaration."""
    return AppProvidedInterfaceDeclaration(
        interface=interface,
        version=version,
        description=description,
        surfaces=surfaces or [],
    )

def build_required_interface_declaration(
    *,
    alias: str,
    interface: str,
    version: str = "^1",
    required: bool = True,
    cardinality: str = "one",
    description: str,
) -> AppRequiredInterfaceDeclaration:
    """Build one generic required-interface declaration."""
    return AppRequiredInterfaceDeclaration(
        alias=alias,
        interface=interface,
        version=version,
        required=required,
        cardinality=cardinality,
        description=description,
    )

def build_app_contract(
    *,
    provides: list[AppProvidedInterfaceDeclaration] | None = None,
    requires: list[AppRequiredInterfaceDeclaration] | None = None,
    distribution: AppDistributionDeclaration | None = None,
    visibility: AppVisibilityDeclaration | None = None,
    presentation: AppPresentationDeclaration | None = None,
    permissions: AppPermissionsDeclaration | None = None,
    compatibility: AppCompatibilityDescriptor | None = None,
    storage: AppStorageDeclaration | None = None,
    capabilities: AppCapabilities | None = None,
    lifecycle: AppLifecycleDeclaration | None = None,
    entrypoints: AppEntrypoints | None = None,
    hook_timeouts: AppHookTimeouts | None = None,
    failure_semantics: AppFailureSemantics | None = None,
    health_contract: AppHealthContract | None = None,
    rollback_support: AppRollbackSupport | None = None,
    widgets: list[WidgetDeclaration] | None = None,
    services: AppServicesDeclaration | None = None,
) -> AppContractDescriptor:
    """Build an executable app contract descriptor."""
    resolved_entrypoints = entrypoints or build_app_entrypoints()
    resolved_presentation = presentation or build_app_presentation(
        frontend_role="workspace" if resolved_entrypoints.frontend else "none"
    )
    return AppContractDescriptor(
        provides=provides or [],
        requires=requires or [],
        distribution=distribution or build_app_distribution(),
        visibility=visibility or AppVisibilityDeclaration(platform_roles=None, workspace_roles=None, capabilities=None),
        presentation=resolved_presentation,
        permissions=permissions or build_app_permissions(),
        compatibility=compatibility or build_app_compatibility(),
        storage=storage or build_app_storage(),
        capabilities=capabilities or build_app_capabilities(),
        lifecycle=lifecycle or build_app_lifecycle(),
        entrypoints=resolved_entrypoints,
        hook_timeouts=hook_timeouts or build_app_hook_timeouts(),
        failure_semantics=failure_semantics or build_app_failure_semantics(),
        health_contract=health_contract or build_app_health_contract(),
        rollback_support=rollback_support or build_app_rollback_support(),
        widgets=widgets or [],
        services=services or build_app_services(),
    )

def build_parsed_app_contract(
    *,
    app_id: str,
    name: str,
    version: str,
    description: str,
    publisher: str,
    contract: AppContractDescriptor | None = None,
) -> ParsedAppContract:
    """Build a normalized parsed contract object."""
    normalized_app_id = _normalize_slug(app_id, fallback="app")
    return ParsedAppContract(
        app_id=normalized_app_id,
        name=name,
        version=version,
        description=description,
        publisher=publisher,
        contract=contract or build_app_contract(),
    )
