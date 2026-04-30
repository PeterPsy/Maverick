"""Metadata and lifecycle section parsing for app contracts."""

from __future__ import annotations

from core.apps.contract_validation import _expect_bool, _expect_string, _expect_string_list, _expect_timeout, _reject_unexpected_fields
from core.apps.errors import AppContractValidationError
from core.apps.models import (
    AppDistributionDeclaration,
    AppFailureSemantics,
    AppHealthContract,
    AppHookTimeouts,
    AppLifecycleDeclaration,
    AppRollbackSupport,
    AppVisibilityDeclaration,
)


def parse_distribution_section(payload: dict[str, object]) -> AppDistributionDeclaration:
    distribution = AppDistributionDeclaration(
        mode=payload.get("mode", "sealed"),
        source_access=payload.get("source_access", "none"),
    )
    unexpected_keys = set(payload) - {"mode", "source_access"}
    if unexpected_keys:
        unexpected = ", ".join(sorted(unexpected_keys))
        raise AppContractValidationError(f"Unsupported distribution field(s): {unexpected}.")
    if distribution.mode not in {"sealed", "source_available", "workspace_local"}:
        raise AppContractValidationError("`distribution.mode` must be sealed, source_available, or workspace_local.")
    if distribution.source_access not in {"none", "read_only", "forkable", "editable"}:
        raise AppContractValidationError("`distribution.source_access` must be none, read_only, forkable, or editable.")
    if distribution.mode == "sealed" and distribution.source_access != "none":
        raise AppContractValidationError("Sealed apps must use source_access none.")
    if distribution.mode == "source_available" and distribution.source_access not in {"read_only", "forkable"}:
        raise AppContractValidationError("Source-available apps must use source_access read_only or forkable.")
    if distribution.mode == "workspace_local" and distribution.source_access != "editable":
        raise AppContractValidationError("Workspace-local apps must use source_access editable.")
    return distribution


def parse_visibility_section(payload: dict[str, object]) -> AppVisibilityDeclaration:
    visibility_roles = None
    if payload.get("platform_roles") is not None:
        visibility_roles = _expect_string_list(payload, "platform_roles") or None
    if visibility_roles is not None:
        unsupported_roles = set(visibility_roles) - {"admin", "member"}
        if unsupported_roles:
            unsupported = ", ".join(sorted(unsupported_roles))
            raise AppContractValidationError(f"Unsupported visibility platform role(s): {unsupported}.")
    workspace_roles = None
    if payload.get("workspace_roles") is not None:
        workspace_roles = _expect_string_list(payload, "workspace_roles") or None
    if workspace_roles is not None:
        unsupported_workspace_roles = set(workspace_roles) - {"admin", "member"}
        if unsupported_workspace_roles:
            unsupported = ", ".join(sorted(unsupported_workspace_roles))
            raise AppContractValidationError(f"Unsupported visibility workspace role(s): {unsupported}.")
    capabilities = None
    if payload.get("capabilities") is not None:
        capabilities = _expect_string_list(payload, "capabilities") or None
    unexpected_keys = set(payload) - {"platform_roles", "workspace_roles", "capabilities"}
    if unexpected_keys:
        unexpected = ", ".join(sorted(unexpected_keys))
        raise AppContractValidationError(f"Unsupported visibility field(s): {unexpected}.")
    return AppVisibilityDeclaration(
        platform_roles=visibility_roles,
        workspace_roles=workspace_roles,
        capabilities=capabilities,
    )


def parse_lifecycle_section(payload: dict[str, object]) -> AppLifecycleDeclaration:
    _reject_unexpected_fields(
        payload,
        {
            "install",
            "upgrade",
            "uninstall",
            "migrate",
            "export",
            "import",
            "validate_after_import",
            "repair_after_import",
            "health_check",
        },
        label="lifecycle",
    )
    return AppLifecycleDeclaration(
        install=_expect_bool(payload, "install", default=False),
        upgrade=_expect_bool(payload, "upgrade", default=False),
        uninstall=_expect_bool(payload, "uninstall", default=False),
        migrate=_expect_bool(payload, "migrate", default=False),
        export=_expect_bool(payload, "export", default=False),
        import_data=_expect_bool(payload, "import", default=False),
        validate_after_import=_expect_bool(payload, "validate_after_import", default=False),
        repair_after_import=_expect_bool(payload, "repair_after_import", default=False),
        health_check=_expect_bool(payload, "health_check", default=False),
    )


def parse_hook_timeouts_section(payload: dict[str, object]) -> AppHookTimeouts:
    _reject_unexpected_fields(
        payload,
        {
            "install_seconds",
            "upgrade_seconds",
            "migrate_seconds",
            "export_seconds",
            "import_seconds",
            "validate_after_import_seconds",
            "repair_after_import_seconds",
            "health_check_seconds",
        },
        label="hook_timeouts",
    )
    return AppHookTimeouts(
        install_seconds=_expect_timeout(payload, "install_seconds", default=60),
        upgrade_seconds=_expect_timeout(payload, "upgrade_seconds", default=120),
        migrate_seconds=_expect_timeout(payload, "migrate_seconds", default=300),
        export_seconds=_expect_timeout(payload, "export_seconds", default=120),
        import_seconds=_expect_timeout(payload, "import_seconds", default=120),
        validate_after_import_seconds=_expect_timeout(payload, "validate_after_import_seconds", default=60),
        repair_after_import_seconds=_expect_timeout(payload, "repair_after_import_seconds", default=180),
        health_check_seconds=_expect_timeout(payload, "health_check_seconds", default=30),
    )


def parse_failure_semantics_section(payload: dict[str, object]) -> AppFailureSemantics:
    _reject_unexpected_fields(payload, {"install_failure", "migrate_failure", "import_failure"}, label="failure_semantics")
    return AppFailureSemantics(
        install_failure=_expect_string(payload, "install_failure"),
        migrate_failure=_expect_string(payload, "migrate_failure"),
        import_failure=_expect_string(payload, "import_failure"),
    )


def parse_health_contract_section(payload: dict[str, object]) -> AppHealthContract:
    _reject_unexpected_fields(payload, {"mode", "degraded_on_failure"}, label="health_contract")
    return AppHealthContract(
        mode=_expect_string(payload, "mode"),
        degraded_on_failure=_expect_bool(payload, "degraded_on_failure", default=True),
    )


def parse_rollback_support_section(payload: dict[str, object]) -> AppRollbackSupport:
    _reject_unexpected_fields(payload, {"bundle", "data", "repair_only"}, label="rollback_support")
    return AppRollbackSupport(
        bundle=_expect_bool(payload, "bundle", default=False),
        data=_expect_bool(payload, "data", default=False),
        repair_only=_expect_bool(payload, "repair_only", default=False),
    )
