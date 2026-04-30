"""Capabilities section parsing for app contracts."""

from __future__ import annotations

from core.apps.contract_common import APP_ID_PATTERN
from core.apps.contract_validation import (
    _expect_bool,
    _expect_entity_type,
    _expect_mapping,
    _expect_string,
    _expect_string_list,
    _reject_unexpected_fields,
)
from core.apps.errors import AppContractValidationError
from core.apps.models import (
    AppCapabilities,
    AppDataEventDeclaration,
    AppReferenceEntityDeclaration,
    AppViewStateActionDeclaration,
    AppViewSurfaceDeclaration,
)


def parse_capabilities_section(payload: dict[str, object]) -> AppCapabilities:
    reference_entities = _parse_reference_entities(payload)
    data_events = _parse_data_events(payload)
    view_surfaces = _parse_view_surfaces(
        payload,
        declared_reference_entity_types={item.entity_type for item in reference_entities},
    )
    cli_commands = _expect_string_list(payload, "cli_commands")
    return AppCapabilities(
        mcp_tools=_expect_string_list(payload, "mcp_tools"),
        cli_commands=cli_commands,
        skills=_expect_string_list(payload, "skills"),
        views=_expect_string_list(payload, "views"),
        data_events=data_events,
        view_surfaces=view_surfaces,
        reference_entities=reference_entities,
    )


def _parse_reference_entities(payload: dict[str, object]) -> list[AppReferenceEntityDeclaration]:
    raw_items = payload.get("reference_entities", [])
    _reject_unexpected_fields(
        payload,
        {
            "mcp_tools",
            "cli_commands",
            "skills",
            "views",
            "data_events",
            "view_surfaces",
            "reference_entities",
        },
        label="capabilities",
    )
    if not isinstance(raw_items, list):
        raise AppContractValidationError("`capabilities.reference_entities` must be a list.")
    reference_entities: list[AppReferenceEntityDeclaration] = []
    seen_entity_types: set[str] = set()
    for index, item in enumerate(raw_items):
        item_payload = _expect_mapping(item, label=f"capabilities.reference_entities[{index}]")
        entity_type = _expect_entity_type(item_payload, "entity_type")
        if entity_type in seen_entity_types:
            raise AppContractValidationError("`capabilities.reference_entities` entries must use unique entity_type values.")
        seen_entity_types.add(entity_type)
        unexpected_keys = set(item_payload) - {
            "entity_type",
            "display_name",
            "searchable",
            "resolvable",
            "summarizable",
            "deep_link_supported",
        }
        if unexpected_keys:
            unexpected = ", ".join(sorted(unexpected_keys))
            raise AppContractValidationError(
                f"Unsupported capabilities.reference_entities[{index}] field(s): {unexpected}."
            )
        reference_entities.append(
            AppReferenceEntityDeclaration(
                entity_type=entity_type,
                display_name=_expect_string(item_payload, "display_name"),
                searchable=_expect_bool(item_payload, "searchable", default=False),
                resolvable=_expect_bool(item_payload, "resolvable", default=False),
                summarizable=_expect_bool(item_payload, "summarizable", default=False),
                deep_link_supported=_expect_bool(item_payload, "deep_link_supported", default=False),
            )
        )
    return reference_entities


def _parse_data_events(payload: dict[str, object]) -> list[AppDataEventDeclaration]:
    raw_items = payload.get("data_events", [])
    if not isinstance(raw_items, list):
        raise AppContractValidationError("`capabilities.data_events` must be a list.")
    data_events: list[AppDataEventDeclaration] = []
    seen_resources: set[str] = set()
    for index, item in enumerate(raw_items):
        item_payload = _expect_mapping(item, label=f"capabilities.data_events[{index}]")
        unexpected_keys = set(item_payload) - {"resource", "description"}
        if unexpected_keys:
            unexpected = ", ".join(sorted(unexpected_keys))
            raise AppContractValidationError(
                f"Unsupported capabilities.data_events[{index}] field(s): {unexpected}."
            )
        resource = _expect_string(item_payload, "resource")
        if not APP_ID_PATTERN.fullmatch(resource):
            raise AppContractValidationError(
                f"`capabilities.data_events[{index}].resource` must be a lowercase slug."
            )
        if resource in seen_resources:
            raise AppContractValidationError("`capabilities.data_events` entries must use unique resource values.")
        seen_resources.add(resource)
        data_events.append(
            AppDataEventDeclaration(resource=resource, description=_expect_string(item_payload, "description"))
        )
    return data_events


def _parse_view_surfaces(
    payload: dict[str, object],
    *,
    declared_reference_entity_types: set[str],
) -> list[AppViewSurfaceDeclaration]:
    raw_items = payload.get("view_surfaces", [])
    if not isinstance(raw_items, list):
        raise AppContractValidationError("`capabilities.view_surfaces` must be a list.")
    view_surfaces: list[AppViewSurfaceDeclaration] = []
    seen_view_ids: set[str] = set()
    declared_views = _expect_string_list(payload, "views")
    for index, item in enumerate(raw_items):
        view_surfaces.append(
            _parse_view_surface(
                item,
                index=index,
                declared_views=declared_views,
                declared_reference_entity_types=declared_reference_entity_types,
                seen_view_ids=seen_view_ids,
            )
        )
    return view_surfaces


def _parse_view_surface(
    item: object,
    *,
    index: int,
    declared_views: list[str],
    declared_reference_entity_types: set[str],
    seen_view_ids: set[str],
) -> AppViewSurfaceDeclaration:
    item_payload = _expect_mapping(item, label=f"capabilities.view_surfaces[{index}]")
    view_id = _expect_string(item_payload, "view_id")
    if view_id not in declared_views:
        raise AppContractValidationError(
            f"`capabilities.view_surfaces[{index}].view_id` must reference a declared view."
        )
    if view_id in seen_view_ids:
        raise AppContractValidationError("`capabilities.view_surfaces` entries must use unique view_id values.")
    seen_view_ids.add(view_id)
    unexpected_keys = set(item_payload) - {
        "view_id",
        "display_name",
        "entity_types",
        "state_actions",
        "supports_custom_view",
        "supports_filter_refinement",
    }
    if unexpected_keys:
        unexpected = ", ".join(sorted(unexpected_keys))
        raise AppContractValidationError(
            f"Unsupported capabilities.view_surfaces[{index}] field(s): {unexpected}."
        )
    entity_types = _expect_string_list(item_payload, "entity_types")
    for entity_index, entity_type in enumerate(entity_types):
        _expect_entity_type({"entity_type": entity_type}, "entity_type")
        if entity_type not in declared_reference_entity_types:
            raise AppContractValidationError(
                f"`capabilities.view_surfaces[{index}].entity_types[{entity_index}]` must reference a declared reference entity type."
            )
    return AppViewSurfaceDeclaration(
        view_id=view_id,
        display_name=_expect_string(item_payload, "display_name"),
        entity_types=entity_types,
        state_actions=_parse_state_actions(item_payload, index=index),
        supports_custom_view=_expect_bool(item_payload, "supports_custom_view", default=False),
        supports_filter_refinement=_expect_bool(item_payload, "supports_filter_refinement", default=False),
    )


def _parse_state_actions(item_payload: dict[str, object], *, index: int) -> list[AppViewStateActionDeclaration]:
    raw_actions = item_payload.get("state_actions", [])
    if not isinstance(raw_actions, list):
        raise AppContractValidationError(f"`capabilities.view_surfaces[{index}].state_actions` must be a list.")
    state_actions: list[AppViewStateActionDeclaration] = []
    seen_actions: set[str] = set()
    for action_index, action_item in enumerate(raw_actions):
        action_payload = _expect_mapping(
            action_item,
            label=f"capabilities.view_surfaces[{index}].state_actions[{action_index}]",
        )
        unexpected_keys = set(action_payload) - {"action", "standard", "description"}
        if unexpected_keys:
            unexpected = ", ".join(sorted(unexpected_keys))
            raise AppContractValidationError(
                f"Unsupported capabilities.view_surfaces[{index}].state_actions[{action_index}] field(s): {unexpected}."
            )
        action = _expect_string(action_payload, "action")
        if action in seen_actions:
            raise AppContractValidationError(
                f"`capabilities.view_surfaces[{index}].state_actions` entries must use unique action values."
            )
        seen_actions.add(action)
        state_actions.append(
            AppViewStateActionDeclaration(
                action=action,
                standard=_expect_bool(action_payload, "standard"),
                description=_expect_string(action_payload, "description"),
            )
        )
    return state_actions
