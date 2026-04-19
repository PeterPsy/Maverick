"""Factory helpers for canonical app contract dataclasses."""

from __future__ import annotations

from pathlib import Path
import re

from core.apps.contract_common import _normalize_slug
from core.apps.models import (
    AppCapabilities,
    AppCompatibilityDescriptor,
    AppContractDescriptor,
    AppDistributionDeclaration,
    AppEntrypoints,
    AppFailureSemantics,
    AppHealthContract,
    AppHookTimeouts,
    AppLifecycleDeclaration,
    AppRollbackSupport,
    AppStorageDeclaration,
    AppStorageIndices,
    ParsedAppContract,
    WidgetActionDeclaration,
    WidgetDeclaration,
    WidgetFrontendDeclaration,
)
from core.execution_policy.models import ExecutionMode
from core.shared.version import current_core_version


CURRENT_APP_CONTRACT_VERSION = "1.0"
APP_CONTRACT_FILENAME = "app_contract.json"
APP_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

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
) -> AppCapabilities:
    """Build one capability declaration."""
    return AppCapabilities(
        mcp_tools=mcp_tools or [],
        cli_commands=cli_commands or [],
        skills=skills or [],
        views=views or [],
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
    rebuild: bool = False,
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
        rebuild=rebuild,
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

def build_app_contract(
    *,
    distribution: AppDistributionDeclaration | None = None,
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
) -> AppContractDescriptor:
    """Build an executable app contract descriptor."""
    return AppContractDescriptor(
        distribution=distribution or build_app_distribution(),
        compatibility=compatibility or build_app_compatibility(),
        storage=storage or build_app_storage(),
        capabilities=capabilities or build_app_capabilities(),
        lifecycle=lifecycle or build_app_lifecycle(),
        entrypoints=entrypoints or build_app_entrypoints(),
        hook_timeouts=hook_timeouts or build_app_hook_timeouts(),
        failure_semantics=failure_semantics or build_app_failure_semantics(),
        health_contract=health_contract or build_app_health_contract(),
        rollback_support=rollback_support or build_app_rollback_support(),
        widgets=widgets or [],
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
