"""Parser for canonical app contract files."""

from __future__ import annotations

import json
from pathlib import Path

from core.apps.contract_builders import build_app_compatibility
from core.apps.contract_common import app_contract_path
from core.apps.contract_dependencies import parse_provided_interfaces, parse_required_interfaces
from core.apps.contract_parser_capabilities import parse_capabilities_section
from core.apps.contract_parser_entrypoints import parse_entrypoints_section
from core.apps.contract_parser_metadata import (
    parse_distribution_section,
    parse_failure_semantics_section,
    parse_health_contract_section,
    parse_hook_timeouts_section,
    parse_lifecycle_section,
    parse_presentation_section,
    parse_rollback_support_section,
    parse_visibility_section,
)
from core.apps.contract_parser_permissions import parse_permissions_section
from core.apps.contract_parser_services import parse_services_section
from core.apps.contract_parser_storage import parse_storage_section
from core.apps.contract_validation import (
    _expect_app_id,
    _expect_mapping,
    _expect_string,
    _expect_string_list,
    _reject_unexpected_fields,
)
from core.apps.contract_widgets import parse_widget_declarations
from core.apps.errors import AppContractValidationError
from core.apps.models import AppContractDescriptor, ParsedAppContract

ROOT_FIELDS = {
    "app_id",
    "public_app_id",
    "contract_version",
    "name",
    "version",
    "description",
    "publisher",
    "minimum_core_version",
    "provides",
    "requires",
    "distribution",
    "visibility",
    "presentation",
    "permissions",
    "capabilities",
    "entrypoints",
    "storage",
    "compatibility",
    "hook_timeouts",
    "lifecycle",
    "health_contract",
    "failure_semantics",
    "rollback_support",
    "widgets",
    "services",
}


def parse_app_contract_file(source_root: Path) -> ParsedAppContract:
    """Parse and validate the canonical app contract file in one app source root."""
    root = _read_contract_payload(source_root)
    _reject_unexpected_fields(root, ROOT_FIELDS, label="app_contract")
    app_id = _expect_app_id(root, "app_id")
    public_app_id = root.get("public_app_id")
    if public_app_id is not None and _expect_app_id(root, "public_app_id") != app_id:
        raise AppContractValidationError("`public_app_id` must match `app_id` in the public app contract.")

    minimum_core_version = _expect_string(root, "minimum_core_version")
    compatibility_payload = _expect_mapping(root.get("compatibility", {}), label="compatibility")
    _reject_unexpected_fields(compatibility_payload, {"workspace_modes"}, label="compatibility")
    supported_workspace_modes = _expect_string_list(compatibility_payload, "workspace_modes") or None
    compatibility = build_app_compatibility(
        contract_version=_expect_string(root, "contract_version"),
        minimum_core_version=minimum_core_version,
        supported_workspace_modes=supported_workspace_modes,
    )

    lifecycle_payload = _expect_mapping(root.get("lifecycle", {}), label="lifecycle")
    entrypoints_payload = _expect_mapping(root.get("entrypoints", {}), label="entrypoints")
    health_contract_payload = _expect_mapping(root.get("health_contract", {}), label="health_contract")
    lifecycle = parse_lifecycle_section(lifecycle_payload)
    entrypoints = parse_entrypoints_section(source_root, entrypoints_payload)
    widgets = parse_widget_declarations(source_root, root, entrypoints)
    if lifecycle.health_check and "health_check" not in entrypoints.hooks and health_contract_payload.get("mode") == "hook":
        raise AppContractValidationError("Health-check lifecycle support requires a `health_check` hook.")

    permissions = parse_permissions_section(_expect_mapping(root.get("permissions", {}), label="permissions"))
    return ParsedAppContract(
        app_id=app_id,
        name=_expect_string(root, "name"),
        version=_expect_string(root, "version"),
        description=_expect_string(root, "description"),
        publisher=_expect_string(root, "publisher"),
        contract=AppContractDescriptor(
            provides=parse_provided_interfaces(root),
            requires=parse_required_interfaces(root),
            distribution=parse_distribution_section(_expect_mapping(root.get("distribution", {}), label="distribution")),
            visibility=parse_visibility_section(_expect_mapping(root.get("visibility", {}), label="visibility")),
            presentation=parse_presentation_section(
                _expect_mapping(root.get("presentation", {}), label="presentation"),
                has_frontend_entrypoint=entrypoints.frontend is not None,
            ),
            permissions=permissions,
            compatibility=compatibility,
            storage=parse_storage_section(_expect_mapping(root.get("storage", {}), label="storage"), app_id=app_id),
            capabilities=parse_capabilities_section(_expect_mapping(root.get("capabilities", {}), label="capabilities")),
            lifecycle=lifecycle,
            entrypoints=entrypoints,
            hook_timeouts=parse_hook_timeouts_section(_expect_mapping(root.get("hook_timeouts", {}), label="hook_timeouts")),
            failure_semantics=parse_failure_semantics_section(
                _expect_mapping(root.get("failure_semantics", {}), label="failure_semantics")
            ),
            health_contract=parse_health_contract_section(health_contract_payload),
            rollback_support=parse_rollback_support_section(
                _expect_mapping(root.get("rollback_support", {}), label="rollback_support")
            ),
            widgets=widgets,
            services=parse_services_section(
                source_root,
                _expect_mapping(root.get("services", {}), label="services"),
                app_id=app_id,
                supported_workspace_modes=supported_workspace_modes,
                provider_model_proxy=permissions.providers.model_proxy,
            ),
        ),
    )


def _read_contract_payload(source_root: Path) -> dict[str, object]:
    contract_file = app_contract_path(source_root)
    if not contract_file.is_file():
        raise AppContractValidationError(f"App contract file `{contract_file}` does not exist.")
    try:
        payload = json.loads(contract_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise AppContractValidationError(f"App contract file `{contract_file}` is not valid JSON.") from error
    return _expect_mapping(payload, label="app_contract")
