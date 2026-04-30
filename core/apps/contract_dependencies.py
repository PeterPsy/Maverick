"""Cross-app interface dependency contract parsing helpers."""

from __future__ import annotations

from core.apps.contract_validation import (
    _expect_bool,
    _expect_interface_id,
    _expect_interface_version,
    _expect_mapping,
    _expect_slug,
    _expect_string,
    _expect_string_list,
)
from core.apps.errors import AppContractValidationError
from core.apps.models import AppProvidedInterfaceDeclaration, AppRequiredInterfaceDeclaration


SURFACE_IDS = {"backend", "cli", "mcp", "reference", "view", "widget"}
CARDINALITIES = {"one", "many"}


def parse_provided_interfaces(root: dict) -> list[AppProvidedInterfaceDeclaration]:
    """Parse generic interfaces this app provides to other apps."""
    provides_payload = root.get("provides")
    if not isinstance(provides_payload, list):
        raise AppContractValidationError("`provides` must be a list.")
    provided: list[AppProvidedInterfaceDeclaration] = []
    seen_interfaces: set[tuple[str, str]] = set()
    for index, item in enumerate(provides_payload):
        payload = _expect_mapping(item, label=f"provides[{index}]")
        unexpected_keys = set(payload) - {"interface", "version", "description", "surfaces"}
        if unexpected_keys:
            unexpected = ", ".join(sorted(unexpected_keys))
            raise AppContractValidationError(f"Unsupported provides[{index}] field(s): {unexpected}.")
        interface = _expect_interface_id(payload, "interface")
        version = _expect_interface_version(payload, "version")
        identity = (interface, version)
        if identity in seen_interfaces:
            raise AppContractValidationError("`provides` entries must use unique interface/version pairs.")
        seen_interfaces.add(identity)
        surfaces = _expect_string_list(payload, "surfaces")
        unsupported_surfaces = set(surfaces) - SURFACE_IDS
        if unsupported_surfaces:
            unsupported = ", ".join(sorted(unsupported_surfaces))
            raise AppContractValidationError(f"Unsupported provides[{index}].surfaces value(s): {unsupported}.")
        provided.append(
            AppProvidedInterfaceDeclaration(
                interface=interface,
                version=version,
                description=_expect_string(payload, "description"),
                surfaces=surfaces,
            )
        )
    return provided


def parse_required_interfaces(root: dict) -> list[AppRequiredInterfaceDeclaration]:
    """Parse generic interfaces this app requires from provider apps."""
    requires_payload = root.get("requires")
    if not isinstance(requires_payload, list):
        raise AppContractValidationError("`requires` must be a list.")
    required: list[AppRequiredInterfaceDeclaration] = []
    seen_aliases: set[str] = set()
    for index, item in enumerate(requires_payload):
        payload = _expect_mapping(item, label=f"requires[{index}]")
        unexpected_keys = set(payload) - {"alias", "interface", "version", "required", "cardinality", "description"}
        if unexpected_keys:
            unexpected = ", ".join(sorted(unexpected_keys))
            raise AppContractValidationError(f"Unsupported requires[{index}] field(s): {unexpected}.")
        alias = _expect_slug(payload, "alias")
        if alias in seen_aliases:
            raise AppContractValidationError("`requires` entries must use unique alias values.")
        seen_aliases.add(alias)
        cardinality = _expect_string(payload, "cardinality")
        if cardinality not in CARDINALITIES:
            raise AppContractValidationError("`requires[].cardinality` must be `one` or `many`.")
        required.append(
            AppRequiredInterfaceDeclaration(
                alias=alias,
                interface=_expect_interface_id(payload, "interface"),
                version=_expect_interface_version(payload, "version"),
                required=_expect_bool(payload, "required"),
                cardinality=cardinality,
                description=_expect_string(payload, "description"),
            )
        )
    return required
