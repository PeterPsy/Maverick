"""Canonical app contract builders, serializer, and parser/validator."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any

from core.apps.errors import AppContractValidationError
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
    AppSourceRecord,
    AppStorageDeclaration,
    AppStorageIndices,
    ParsedAppContract,
    WorkspaceLocalAppProjectRecord,
)
from core.execution_policy.models import ExecutionMode
from core.shared.version import current_core_version


CURRENT_APP_CONTRACT_VERSION = "1.0"
APP_CONTRACT_FILENAME = "app_contract.json"
APP_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def _timestamp(now: datetime | None = None) -> str:
    return (now or utcnow()).isoformat()


def _normalize_slug(value: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower()).strip("-")
    return normalized or fallback


def app_contract_path(source_root: Path) -> Path:
    """Return the canonical contract-file path for one app root."""
    return source_root / APP_CONTRACT_FILENAME


def _expect_mapping(payload: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AppContractValidationError(f"`{label}` must be an object.")
    return payload


def _expect_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AppContractValidationError(f"`{key}` must be a non-empty string.")
    return value.strip()


def _expect_app_id(payload: dict[str, Any], key: str = "app_id") -> str:
    value = _expect_string(payload, key)
    if not APP_ID_PATTERN.fullmatch(value):
        raise AppContractValidationError(
            f"`{key}` must use lowercase kebab-case such as `restaurant-manager`, got `{value}`."
        )
    return value


def _expect_bool(payload: dict[str, Any], key: str, *, default: bool | None = None) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise AppContractValidationError(f"`{key}` must be a boolean.")
    return value


def _expect_string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise AppContractValidationError(f"`{key}` must be a list of non-empty strings.")
    return [item.strip() for item in value]


def _expect_relative_contract_path(source_root: Path, relative_path: str, *, label: str, allow_directory: bool = False) -> str:
    if Path(relative_path).is_absolute():
        raise AppContractValidationError(f"`{label}` must be a relative path.")
    resolved = (source_root / relative_path).resolve()
    root = source_root.resolve()
    if resolved != root and root not in resolved.parents:
        raise AppContractValidationError(f"`{label}` escapes app root `{source_root}`.")
    if not resolved.exists():
        raise AppContractValidationError(f"`{label}` does not exist under app root `{source_root}`.")
    if not allow_directory and not resolved.is_file():
        raise AppContractValidationError(f"`{label}` must resolve to a file.")
    if allow_directory and not resolved.is_dir():
        raise AppContractValidationError(f"`{label}` must resolve to a directory.")
    return relative_path


def _expect_timeout(payload: dict[str, Any], key: str, *, default: int) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int) or value <= 0:
        raise AppContractValidationError(f"`{key}` must be a positive integer timeout.")
    return value


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
    modifiable_by_agents: bool = False,
) -> AppDistributionDeclaration:
    """Build one app distribution and mutability declaration."""
    return AppDistributionDeclaration(
        mode=mode,
        source_access=source_access,
        modifiable_by_agents=modifiable_by_agents,
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


def parsed_contract_to_app_source_record(
    *,
    parsed: ParsedAppContract,
    source_kind: str,
    source_path: str,
    source_id: str | None = None,
    now: datetime | None = None,
) -> AppSourceRecord:
    """Persist one parsed app contract as an installation-level app source record."""
    timestamp = _timestamp(now)
    return AppSourceRecord(
        source_id=source_id or f"{source_kind}:{parsed.app_id}:{parsed.version}",
        app_id=parsed.app_id,
        name=parsed.name,
        version=parsed.version,
        description=parsed.description,
        publisher=parsed.publisher,
        source_kind=source_kind,
        source_path=source_path,
        contract=parsed.contract,
        created_at=timestamp,
        updated_at=timestamp,
    )


def parsed_contract_to_workspace_local_project_record(
    *,
    parsed: ParsedAppContract,
    workspace_id: str,
    project_root: str,
    project_id: str | None = None,
    forked_from_source_id: str | None = None,
    forked_from_version: str | None = None,
    now: datetime | None = None,
) -> WorkspaceLocalAppProjectRecord:
    """Persist one parsed app contract as a workspace-local project record."""
    timestamp = _timestamp(now)
    return WorkspaceLocalAppProjectRecord(
        project_id=project_id or f"{workspace_id}:{parsed.app_id}",
        workspace_id=workspace_id,
        app_id=parsed.app_id,
        name=parsed.name,
        version=parsed.version,
        description=parsed.description,
        publisher=parsed.publisher,
        project_root=project_root,
        contract=parsed.contract,
        created_at=timestamp,
        updated_at=timestamp,
        forked_from_source_id=forked_from_source_id,
        forked_from_version=forked_from_version,
    )


def app_contract_payload(parsed: ParsedAppContract) -> dict[str, Any]:
    """Render one parsed contract into the canonical JSON payload shape."""
    lifecycle = parsed.contract.lifecycle
    return {
        "app_id": parsed.app_id,
        "contract_version": parsed.contract.compatibility.contract_version,
        "name": parsed.name,
        "version": parsed.version,
        "description": parsed.description,
        "publisher": parsed.publisher,
        "minimum_core_version": parsed.contract.compatibility.minimum_core_version,
        "distribution": {
            "mode": parsed.contract.distribution.mode,
            "source_access": parsed.contract.distribution.source_access,
            "modifiable_by_agents": parsed.contract.distribution.modifiable_by_agents,
        },
        "capabilities": {
            "mcp_tools": parsed.contract.capabilities.mcp_tools,
            "cli_commands": parsed.contract.capabilities.cli_commands,
            "skills": parsed.contract.capabilities.skills,
            "views": parsed.contract.capabilities.views,
        },
        "entrypoints": {
            "mcp": parsed.contract.entrypoints.mcp,
            "cli": parsed.contract.entrypoints.cli,
            "backend": parsed.contract.entrypoints.backend,
            "frontend": parsed.contract.entrypoints.frontend,
            "skills_root": parsed.contract.entrypoints.skills_root,
            "hooks": parsed.contract.entrypoints.hooks,
        },
        "storage": {
            "storage_kind": parsed.contract.storage.storage_kind,
            "data_schema_version": parsed.contract.storage.data_schema_version,
            "primary_paths": parsed.contract.storage.primary_paths,
            "indices": (
                {"kind": parsed.contract.storage.indices.kind}
                if parsed.contract.storage.indices is not None
                else None
            ),
            "supports_export": parsed.contract.storage.supports_export,
            "supports_import": parsed.contract.storage.supports_import,
            "supports_migrations": parsed.contract.storage.supports_migrations,
        },
        "compatibility": {
            "workspace_modes": parsed.contract.compatibility.supported_workspace_modes or [],
        },
        "hook_timeouts": {
            "install_seconds": parsed.contract.hook_timeouts.install_seconds,
            "upgrade_seconds": parsed.contract.hook_timeouts.upgrade_seconds,
            "migrate_seconds": parsed.contract.hook_timeouts.migrate_seconds,
            "export_seconds": parsed.contract.hook_timeouts.export_seconds,
            "import_seconds": parsed.contract.hook_timeouts.import_seconds,
            "validate_after_import_seconds": parsed.contract.hook_timeouts.validate_after_import_seconds,
            "repair_after_import_seconds": parsed.contract.hook_timeouts.repair_after_import_seconds,
            "health_check_seconds": parsed.contract.hook_timeouts.health_check_seconds,
        },
        "lifecycle": {
            "install": lifecycle.install,
            "upgrade": lifecycle.upgrade,
            "uninstall": lifecycle.uninstall,
            "migrate": lifecycle.migrate,
            "export": lifecycle.export,
            "import": lifecycle.import_data,
            "validate_after_import": lifecycle.validate_after_import,
            "repair_after_import": lifecycle.repair_after_import,
            "rebuild": lifecycle.rebuild,
            "health_check": lifecycle.health_check,
        },
        "health_contract": {
            "mode": parsed.contract.health_contract.mode,
            "degraded_on_failure": parsed.contract.health_contract.degraded_on_failure,
        },
        "failure_semantics": {
            "install_failure": parsed.contract.failure_semantics.install_failure,
            "migrate_failure": parsed.contract.failure_semantics.migrate_failure,
            "import_failure": parsed.contract.failure_semantics.import_failure,
        },
        "rollback_support": {
            "bundle": parsed.contract.rollback_support.bundle,
            "data": parsed.contract.rollback_support.data,
            "repair_only": parsed.contract.rollback_support.repair_only,
        },
    }


def write_app_contract_file(source_root: Path, parsed: ParsedAppContract) -> Path:
    """Write one canonical app contract file into the given app root."""
    source_root.mkdir(parents=True, exist_ok=True)
    contract_file = app_contract_path(source_root)
    contract_file.write_text(json.dumps(app_contract_payload(parsed), indent=2) + "\n", encoding="utf-8")
    return contract_file


def parse_app_contract_file(source_root: Path) -> ParsedAppContract:
    """Parse and validate the canonical app contract file in one app source root."""
    contract_file = app_contract_path(source_root)
    if not contract_file.is_file():
        raise AppContractValidationError(f"App contract file `{contract_file}` does not exist.")
    try:
        payload = json.loads(contract_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise AppContractValidationError(f"App contract file `{contract_file}` is not valid JSON.") from error
    root = _expect_mapping(payload, label="app_contract")
    app_id = _expect_app_id(root, "app_id")
    name = _expect_string(root, "name")
    version = _expect_string(root, "version")
    description = _expect_string(root, "description")
    publisher = _expect_string(root, "publisher")
    minimum_core_version = _expect_string(root, "minimum_core_version")

    capabilities_payload = _expect_mapping(root.get("capabilities", {}), label="capabilities")
    distribution_payload = _expect_mapping(root.get("distribution", {}), label="distribution")
    entrypoints_payload = _expect_mapping(root.get("entrypoints", {}), label="entrypoints")
    storage_payload = _expect_mapping(root.get("storage", {}), label="storage")
    compatibility_payload = _expect_mapping(root.get("compatibility", {}), label="compatibility")
    lifecycle_payload = _expect_mapping(root.get("lifecycle", {}), label="lifecycle")
    hook_timeouts_payload = _expect_mapping(root.get("hook_timeouts", {}), label="hook_timeouts")
    failure_semantics_payload = _expect_mapping(root.get("failure_semantics", {}), label="failure_semantics")
    health_contract_payload = _expect_mapping(root.get("health_contract", {}), label="health_contract")
    rollback_support_payload = _expect_mapping(root.get("rollback_support", {}), label="rollback_support")

    supported_workspace_modes = _expect_string_list(compatibility_payload, "workspace_modes") or None
    compatibility = build_app_compatibility(
        contract_version=_expect_string(root, "contract_version"),
        minimum_core_version=minimum_core_version,
        supported_workspace_modes=supported_workspace_modes,
    )

    primary_paths = _expect_string_list(storage_payload, "primary_paths")
    for index, primary_path in enumerate(primary_paths):
        if Path(primary_path).is_absolute():
            raise AppContractValidationError("`storage.primary_paths` entries must be relative.")
        expected_prefix = f"data/{app_id}/"
        if not primary_path.startswith(expected_prefix):
            raise AppContractValidationError(
                f"`storage.primary_paths[{index}]` must stay under `{expected_prefix}`."
            )
    indices_payload = storage_payload.get("indices")
    indices = None
    if indices_payload is not None:
        indices_mapping = _expect_mapping(indices_payload, label="storage.indices")
        indices = AppStorageIndices(kind=_expect_string(indices_mapping, "kind"))
    storage = AppStorageDeclaration(
        storage_kind=_expect_string(storage_payload, "storage_kind"),
        data_schema_version=_expect_string(storage_payload, "data_schema_version"),
        primary_paths=primary_paths,
        indices=indices,
        supports_export=_expect_bool(storage_payload, "supports_export", default=False),
        supports_import=_expect_bool(storage_payload, "supports_import", default=False),
        supports_migrations=_expect_bool(storage_payload, "supports_migrations", default=False),
    )

    capabilities = AppCapabilities(
        mcp_tools=_expect_string_list(capabilities_payload, "mcp_tools"),
        cli_commands=_expect_string_list(capabilities_payload, "cli_commands"),
        skills=_expect_string_list(capabilities_payload, "skills"),
        views=_expect_string_list(capabilities_payload, "views"),
    )

    distribution = AppDistributionDeclaration(
        mode=distribution_payload.get("mode", "sealed"),
        source_access=distribution_payload.get("source_access", "none"),
        modifiable_by_agents=_expect_bool(distribution_payload, "modifiable_by_agents", default=False),
    )
    if distribution.mode not in {"sealed", "source_available", "workspace_local"}:
        raise AppContractValidationError("`distribution.mode` must be sealed, source_available, or workspace_local.")
    if distribution.source_access not in {"none", "read_only", "forkable", "editable"}:
        raise AppContractValidationError(
            "`distribution.source_access` must be none, read_only, forkable, or editable."
        )
    if distribution.mode == "sealed" and (
        distribution.source_access != "none" or distribution.modifiable_by_agents
    ):
        raise AppContractValidationError("Sealed apps must use source_access none and cannot be modifiable by agents.")
    if distribution.mode == "source_available" and distribution.source_access not in {"read_only", "forkable"}:
        raise AppContractValidationError("Source-available apps must use source_access read_only or forkable.")
    if distribution.mode == "workspace_local" and distribution.source_access != "editable":
        raise AppContractValidationError("Workspace-local apps must use source_access editable.")

    lifecycle = AppLifecycleDeclaration(
        install=_expect_bool(lifecycle_payload, "install", default=False),
        upgrade=_expect_bool(lifecycle_payload, "upgrade", default=False),
        uninstall=_expect_bool(lifecycle_payload, "uninstall", default=False),
        migrate=_expect_bool(lifecycle_payload, "migrate", default=False),
        export=_expect_bool(lifecycle_payload, "export", default=False),
        import_data=_expect_bool(lifecycle_payload, "import", default=False),
        validate_after_import=_expect_bool(lifecycle_payload, "validate_after_import", default=False),
        repair_after_import=_expect_bool(lifecycle_payload, "repair_after_import", default=False),
        rebuild=_expect_bool(lifecycle_payload, "rebuild", default=False),
        health_check=_expect_bool(lifecycle_payload, "health_check", default=False),
    )

    mcp_entrypoint = entrypoints_payload.get("mcp")
    cli_entrypoint = entrypoints_payload.get("cli")
    backend_entrypoint = entrypoints_payload.get("backend")
    frontend_entrypoint = entrypoints_payload.get("frontend")
    skills_root = entrypoints_payload.get("skills_root")
    hooks_payload = _expect_mapping(entrypoints_payload.get("hooks", {}), label="entrypoints.hooks")
    hooks = {
        hook_name: _expect_relative_contract_path(source_root, hook_path, label=f"entrypoints.hooks.{hook_name}")
        for hook_name, hook_path in hooks_payload.items()
    }
    entrypoints = AppEntrypoints(
        mcp=(
            _expect_relative_contract_path(source_root, mcp_entrypoint, label="entrypoints.mcp")
            if mcp_entrypoint is not None
            else None
        ),
        cli=(
            _expect_relative_contract_path(source_root, cli_entrypoint, label="entrypoints.cli")
            if cli_entrypoint is not None
            else None
        ),
        backend=(
            _expect_relative_contract_path(source_root, backend_entrypoint, label="entrypoints.backend")
            if backend_entrypoint is not None
            else None
        ),
        frontend=(
            _expect_relative_contract_path(
                source_root,
                frontend_entrypoint,
                label="entrypoints.frontend",
                allow_directory=True,
            )
            if frontend_entrypoint is not None
            else None
        ),
        skills_root=(
            _expect_relative_contract_path(
                source_root,
                skills_root,
                label="entrypoints.skills_root",
                allow_directory=True,
            )
            if skills_root is not None
            else None
        ),
        hooks=hooks,
    )

    if lifecycle.health_check and "health_check" not in hooks and health_contract_payload.get("mode") == "hook":
        raise AppContractValidationError("Health-check lifecycle support requires a `health_check` hook.")

    hook_timeouts = AppHookTimeouts(
        install_seconds=_expect_timeout(hook_timeouts_payload, "install_seconds", default=60),
        upgrade_seconds=_expect_timeout(hook_timeouts_payload, "upgrade_seconds", default=120),
        migrate_seconds=_expect_timeout(hook_timeouts_payload, "migrate_seconds", default=300),
        export_seconds=_expect_timeout(hook_timeouts_payload, "export_seconds", default=120),
        import_seconds=_expect_timeout(hook_timeouts_payload, "import_seconds", default=120),
        validate_after_import_seconds=_expect_timeout(
            hook_timeouts_payload, "validate_after_import_seconds", default=60
        ),
        repair_after_import_seconds=_expect_timeout(
            hook_timeouts_payload, "repair_after_import_seconds", default=180
        ),
        health_check_seconds=_expect_timeout(hook_timeouts_payload, "health_check_seconds", default=30),
    )

    failure_semantics = AppFailureSemantics(
        install_failure=_expect_string(failure_semantics_payload, "install_failure"),
        migrate_failure=_expect_string(failure_semantics_payload, "migrate_failure"),
        import_failure=_expect_string(failure_semantics_payload, "import_failure"),
    )
    health_contract = AppHealthContract(
        mode=_expect_string(health_contract_payload, "mode"),
        degraded_on_failure=_expect_bool(health_contract_payload, "degraded_on_failure", default=True),
    )
    rollback_support = AppRollbackSupport(
        bundle=_expect_bool(rollback_support_payload, "bundle", default=False),
        data=_expect_bool(rollback_support_payload, "data", default=False),
        repair_only=_expect_bool(rollback_support_payload, "repair_only", default=False),
    )

    return ParsedAppContract(
        app_id=app_id,
        name=name,
        version=version,
        description=description,
        publisher=publisher,
        contract=AppContractDescriptor(
            distribution=distribution,
            compatibility=compatibility,
            storage=storage,
            capabilities=capabilities,
            lifecycle=lifecycle,
            entrypoints=entrypoints,
            hook_timeouts=hook_timeouts,
            failure_semantics=failure_semantics,
            health_contract=health_contract,
            rollback_support=rollback_support,
        ),
    )
