"""App-owned CLI and MCP discovery descriptor loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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
            allowed_fields={"description", "argument_schema"},
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
            allowed_fields={"description", "input_schema", "output_schema"},
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
