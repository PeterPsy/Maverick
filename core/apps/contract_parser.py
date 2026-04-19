"""Parser for canonical app contract files."""

from __future__ import annotations

import json
from pathlib import Path
import re

from core.apps.errors import AppContractValidationError
from core.apps.models import (
    AppCapabilities,
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
    AppVisibilityDeclaration,
    ParsedAppContract,
)


CURRENT_APP_CONTRACT_VERSION = "1.0"
APP_CONTRACT_FILENAME = "app_contract.json"
APP_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

from core.apps.contract_builders import build_app_compatibility
from core.apps.contract_common import app_contract_path
from core.apps.contract_validation import (
    _expect_app_id,
    _expect_bool,
    _expect_mapping,
    _expect_relative_contract_path,
    _expect_string,
    _expect_string_list,
    _expect_timeout,
)
from core.apps.contract_widgets import parse_widget_declarations

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
    visibility_payload = _expect_mapping(root.get("visibility", {}), label="visibility")
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
    )
    unexpected_distribution_keys = set(distribution_payload) - {"mode", "source_access"}
    if unexpected_distribution_keys:
        unexpected = ", ".join(sorted(unexpected_distribution_keys))
        raise AppContractValidationError(f"Unsupported distribution field(s): {unexpected}.")
    if distribution.mode not in {"sealed", "source_available", "workspace_local"}:
        raise AppContractValidationError("`distribution.mode` must be sealed, source_available, or workspace_local.")
    if distribution.source_access not in {"none", "read_only", "forkable", "editable"}:
        raise AppContractValidationError(
            "`distribution.source_access` must be none, read_only, forkable, or editable."
        )
    if distribution.mode == "sealed" and distribution.source_access != "none":
        raise AppContractValidationError("Sealed apps must use source_access none.")
    if distribution.mode == "source_available" and distribution.source_access not in {"read_only", "forkable"}:
        raise AppContractValidationError("Source-available apps must use source_access read_only or forkable.")
    if distribution.mode == "workspace_local" and distribution.source_access != "editable":
        raise AppContractValidationError("Workspace-local apps must use source_access editable.")

    visibility_roles = None
    if visibility_payload.get("platform_roles") is not None:
        visibility_roles = _expect_string_list(visibility_payload, "platform_roles") or None
    if visibility_roles is not None:
        unsupported_roles = set(visibility_roles) - {"admin", "member"}
        if unsupported_roles:
            unsupported = ", ".join(sorted(unsupported_roles))
            raise AppContractValidationError(f"Unsupported visibility platform role(s): {unsupported}.")
    unexpected_visibility_keys = set(visibility_payload) - {"platform_roles"}
    if unexpected_visibility_keys:
        unexpected = ", ".join(sorted(unexpected_visibility_keys))
        raise AppContractValidationError(f"Unsupported visibility field(s): {unexpected}.")
    visibility = AppVisibilityDeclaration(platform_roles=visibility_roles)

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
    widgets = parse_widget_declarations(source_root, root, entrypoints)

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
            visibility=visibility,
            compatibility=compatibility,
            storage=storage,
            capabilities=capabilities,
            lifecycle=lifecycle,
            entrypoints=entrypoints,
            hook_timeouts=hook_timeouts,
            failure_semantics=failure_semantics,
            health_contract=health_contract,
            rollback_support=rollback_support,
            widgets=widgets,
        ),
    )
