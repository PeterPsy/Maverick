"""App-owned CLI and MCP discovery descriptor loading."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from core.secrets.app_delivery import AppSecretRequest


@dataclass(frozen=True)
class AppSurfaceSecretSelector:
    """Descriptor-owned rule for deriving app secret requests from invocation arguments."""

    logical_names: list[str]
    resource_type: str | None = None
    resource_id_argument: str | None = None
    resource_lookup: dict[str, Any] | None = None
    when: dict[str, Any] | None = None


def app_cli_command_metadata(
    source_root: Path,
    command_name: str,
    *,
    default_description: str,
) -> tuple[str, dict[str, Any]]:
    """Return app-owned CLI description and schema metadata when declared."""
    try:
        item = _descriptor_item(
            source_root / "cli" / "command_schemas.json",
            root_field="commands",
            item_name=command_name,
            allowed_fields={"description", "argument_schema", "required_secrets", "secret_selectors"},
        )
        if item is None:
            return default_description, _object_schema()
        return (
            _optional_string(item, "description", default=default_description),
            _optional_schema(item, "argument_schema"),
        )
    except ValueError:
        return default_description, _object_schema()


def app_mcp_tool_metadata(
    source_root: Path,
    tool_name: str,
    *,
    default_description: str,
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    """Return app-owned MCP description and schema metadata when declared."""
    try:
        item = _descriptor_item(
            source_root / "mcp" / "tool_schemas.json",
            root_field="tools",
            item_name=tool_name,
            allowed_fields={"description", "input_schema", "output_schema", "required_secrets", "secret_selectors"},
        )
        if item is None:
            return default_description, _object_schema(), _object_schema()
        return (
            _optional_string(item, "description", default=default_description),
            _optional_schema(item, "input_schema"),
            _optional_nullable_schema(item, "output_schema"),
        )
    except ValueError:
        return default_description, _object_schema(), _object_schema()


def app_cli_command_required_secrets(
    source_root: Path,
    command_name: str,
    *,
    declared_secret_names: list[str],
) -> list[str]:
    """Return descriptor-declared secret logical names required by one CLI command."""
    return _app_surface_required_secrets(
        source_root / "cli" / "command_schemas.json",
        root_field="commands",
        item_name=command_name,
        allowed_fields={"description", "argument_schema", "required_secrets", "secret_selectors"},
        declared_secret_names=declared_secret_names,
    )


def app_mcp_tool_required_secrets(
    source_root: Path,
    tool_name: str,
    *,
    declared_secret_names: list[str],
) -> list[str]:
    """Return descriptor-declared secret logical names required by one MCP tool."""
    return _app_surface_required_secrets(
        source_root / "mcp" / "tool_schemas.json",
        root_field="tools",
        item_name=tool_name,
        allowed_fields={"description", "input_schema", "output_schema", "required_secrets", "secret_selectors"},
        declared_secret_names=declared_secret_names,
    )


def app_cli_command_secret_selectors(
    source_root: Path,
    command_name: str,
    *,
    declared_secret_names: list[str],
) -> list[AppSurfaceSecretSelector]:
    """Return CLI descriptor secret selectors filtered to declared logical names."""
    return _app_surface_secret_selectors(
        source_root / "cli" / "command_schemas.json",
        root_field="commands",
        item_name=command_name,
        allowed_fields={"description", "argument_schema", "required_secrets", "secret_selectors"},
        declared_secret_names=declared_secret_names,
    )


def app_mcp_tool_secret_selectors(
    source_root: Path,
    tool_name: str,
    *,
    declared_secret_names: list[str],
) -> list[AppSurfaceSecretSelector]:
    """Return MCP descriptor secret selectors filtered to declared logical names."""
    return _app_surface_secret_selectors(
        source_root / "mcp" / "tool_schemas.json",
        root_field="tools",
        item_name=tool_name,
        allowed_fields={"description", "input_schema", "output_schema", "required_secrets", "secret_selectors"},
        declared_secret_names=declared_secret_names,
    )


def app_secret_requests_for_arguments(
    selectors: list[AppSurfaceSecretSelector],
    arguments: dict[str, Any],
    *,
    resource_lookup: Callable[[AppSurfaceSecretSelector], dict[str, Any] | None] | None = None,
) -> list[AppSecretRequest]:
    """Resolve descriptor selectors into concrete app-secret delivery requests."""
    requests: list[AppSecretRequest] = []
    for selector in selectors:
        if not _selector_when_matches(selector.when, arguments):
            continue
        lookup_result = resource_lookup(selector) if selector.resource_lookup and resource_lookup is not None else None
        if selector.resource_lookup and not _lookup_requires_secrets(lookup_result):
            continue
        resource_type = selector.resource_type
        resource_id = _argument_value(arguments, selector.resource_id_argument)
        if resource_type and selector.resource_lookup and lookup_result is not None:
            resource_id = str(lookup_result.get("resource_id") or resource_id or "").strip()
        if resource_type and resource_id:
            requests.append(
                AppSecretRequest(
                    logical_names=selector.logical_names,
                    resource_type=resource_type,
                    resource_id=resource_id,
                )
            )
            continue
        if not resource_type:
            requests.append(AppSecretRequest(logical_names=selector.logical_names))
    return _dedupe_secret_requests(requests)


def _app_surface_required_secrets(
    path: Path,
    *,
    root_field: str,
    item_name: str,
    allowed_fields: set[str],
    declared_secret_names: list[str],
) -> list[str]:
    try:
        item = _descriptor_item(path, root_field=root_field, item_name=item_name, allowed_fields=allowed_fields)
        if item is None:
            return []
        names = _required_secret_names(item, declared_secret_names=declared_secret_names)
        raw_selectors = item.get("secret_selectors", [])
        if not isinstance(raw_selectors, list):
            raw_selectors = []
        for selector in raw_selectors:
            if isinstance(selector, dict):
                for logical_name in _required_secret_names(selector, declared_secret_names=declared_secret_names):
                    if logical_name not in names:
                        names.append(logical_name)
        return names
    except ValueError:
        return []


def _app_surface_secret_selectors(
    path: Path,
    *,
    root_field: str,
    item_name: str,
    allowed_fields: set[str],
    declared_secret_names: list[str],
) -> list[AppSurfaceSecretSelector]:
    selectors: list[AppSurfaceSecretSelector] = []
    try:
        item = _descriptor_item(path, root_field=root_field, item_name=item_name, allowed_fields=allowed_fields)
        if item is None:
            return selectors
        legacy = _required_secret_names(item, declared_secret_names=declared_secret_names)
        if legacy:
            selectors.append(AppSurfaceSecretSelector(logical_names=legacy))
        raw_selectors = item.get("secret_selectors", [])
        if not isinstance(raw_selectors, list):
            raise ValueError("App surface descriptor field `secret_selectors` must be a list.")
        for raw_selector in raw_selectors:
            if not isinstance(raw_selector, dict):
                raise ValueError("App surface descriptor field `secret_selectors` must contain objects.")
            selectors.extend(_secret_selector_from_descriptor(raw_selector, declared_secret_names=declared_secret_names))
        return selectors
    except ValueError:
        return selectors


def _descriptor_item(
    path: Path,
    *,
    root_field: str,
    item_name: str,
    allowed_fields: set[str],
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = _load_json_object(path)
    unexpected = set(payload) - {root_field}
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise ValueError(f"App surface descriptor `{path}` has unsupported field(s): {names}.")
    items = payload.get(root_field, {})
    if not isinstance(items, dict):
        raise ValueError(f"App surface descriptor `{path}` field `{root_field}` must be an object.")
    item = items.get(item_name)
    if item is None:
        return None
    if not isinstance(item, dict):
        raise ValueError(f"App surface descriptor `{path}` item `{item_name}` must be an object.")
    unexpected_item_fields = set(item) - allowed_fields
    if unexpected_item_fields:
        names = ", ".join(sorted(unexpected_item_fields))
        raise ValueError(
            f"App surface descriptor `{path}` item `{item_name}` has unsupported field(s): {names}."
        )
    return item


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"App surface descriptor `{path}` is not valid JSON.") from error
    if not isinstance(payload, dict):
        raise ValueError(f"App surface descriptor `{path}` must be a JSON object.")
    return payload


def _optional_string(payload: dict[str, Any], key: str, *, default: str) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"App surface descriptor field `{key}` must be a string.")
    return value


def _optional_schema(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key, _object_schema())
    if not isinstance(value, dict):
        raise ValueError(f"App surface descriptor field `{key}` must be an object.")
    return value


def _optional_nullable_schema(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = payload.get(key, _object_schema())
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"App surface descriptor field `{key}` must be an object or null.")
    return value


def _object_schema() -> dict[str, Any]:
    return {"type": "object"}


def _required_secret_names(payload: dict[str, Any], *, declared_secret_names: list[str]) -> list[str]:
    values = payload.get("required_secrets", [])
    if not isinstance(values, list):
        raise ValueError("App surface descriptor field `required_secrets` must be a list.")
    declared = {str(value).strip().lower() for value in declared_secret_names}
    required: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("App surface descriptor field `required_secrets` must contain strings.")
        logical_name = value.strip().lower()
        if logical_name and logical_name in declared and logical_name not in required:
            required.append(logical_name)
    return required


def _secret_selector_from_descriptor(
    payload: dict[str, Any],
    *,
    declared_secret_names: list[str],
) -> list[AppSurfaceSecretSelector]:
    unexpected = set(payload) - {"required_secrets", "resource_type", "resource_id_argument", "resource_lookup", "when"}
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise ValueError(f"App surface secret selector has unsupported field(s): {names}.")
    logical_names = _required_secret_names(payload, declared_secret_names=declared_secret_names)
    if not logical_names:
        return []
    resource_type = _optional_selector_string(payload, "resource_type")
    resource_id_argument = _optional_selector_string(payload, "resource_id_argument")
    resource_lookup = payload.get("resource_lookup")
    if resource_lookup is not None and not isinstance(resource_lookup, dict):
        raise ValueError("App surface secret selector field `resource_lookup` must be an object.")
    when = payload.get("when")
    if when is not None and not isinstance(when, dict):
        raise ValueError("App surface secret selector field `when` must be an object.")
    return [
        AppSurfaceSecretSelector(
            logical_names=logical_names,
            resource_type=resource_type,
            resource_id_argument=resource_id_argument,
            resource_lookup=resource_lookup,
            when=when,
        )
    ]


def _optional_selector_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"App surface secret selector field `{key}` must be a string.")
    return value.strip() or None


def _selector_when_matches(when: dict[str, Any] | None, arguments: dict[str, Any]) -> bool:
    if not when:
        return True
    for key, expected in when.items():
        actual = arguments.get(str(key))
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def _argument_value(arguments: dict[str, Any], argument_name: str | None) -> str:
    if not argument_name:
        return ""
    value = arguments.get(argument_name)
    return str(value or "").strip()


def _lookup_requires_secrets(lookup_result: dict[str, Any] | None) -> bool:
    if not isinstance(lookup_result, dict):
        return False
    return bool(lookup_result.get("requires_secrets"))


def _dedupe_secret_requests(requests: list[AppSecretRequest]) -> list[AppSecretRequest]:
    deduped: list[AppSecretRequest] = []
    seen: set[tuple[tuple[str, ...], str | None, str | None]] = set()
    for request in requests:
        key = (tuple(request.logical_names), request.resource_type, request.resource_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(request)
    return deduped
