"""Deterministic provider schema mapping and original-schema validation."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from core.runtime.tool_errors import RuntimeToolSchemaError


MAX_TOOL_SCHEMA_BYTES = 32_768
MAX_TOOL_SCHEMA_DEPTH = 8
MAX_TOOL_ARGUMENT_DEPTH = 16
_SCHEMA_KEYS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "const",
        "description",
        "title",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "minItems",
        "maxItems",
    }
)


def provider_tool_name(handle: str) -> str:
    """Map an internal handle to one stable provider-safe identifier."""
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", handle).strip("_").lower() or "tool"
    digest = hashlib.sha256(handle.encode("utf-8")).hexdigest()[:12]
    return f"mav_{slug[:42]}_{digest}"


def provider_safe_tool_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded, recursively sorted subset accepted across providers."""
    normalized = _normalize_schema(schema, depth=0)
    encoded = json.dumps(normalized, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(encoded) > MAX_TOOL_SCHEMA_BYTES:
        raise RuntimeToolSchemaError("tool_schema_too_large")
    return normalized


def validate_tool_arguments(schema: dict[str, Any], arguments: dict[str, object]) -> None:
    """Validate provider arguments against the authoritative original schema."""
    _normalize_schema(schema, depth=0)
    _validate_value(schema, arguments, path="$", depth=0)


def _normalize_schema(schema: object, *, depth: int) -> dict[str, Any]:
    if depth > MAX_TOOL_SCHEMA_DEPTH or not isinstance(schema, dict):
        raise RuntimeToolSchemaError("tool_schema_invalid")
    unsupported = set(schema) - _SCHEMA_KEYS
    if unsupported:
        raise RuntimeToolSchemaError("tool_schema_unsupported", ",".join(sorted(unsupported)))
    schema_type = schema.get("type", "object" if "properties" in schema else None)
    if schema_type not in {"object", "array", "string", "integer", "number", "boolean", "null"}:
        raise RuntimeToolSchemaError("tool_schema_invalid")
    normalized: dict[str, Any] = {"type": schema_type}
    for key in ("title", "description"):
        if key in schema:
            value = schema[key]
            if not isinstance(value, str):
                raise RuntimeToolSchemaError("tool_schema_invalid")
            normalized[key] = value[:1024]
    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list) or not enum or len(enum) > 128:
            raise RuntimeToolSchemaError("tool_schema_invalid")
        normalized["enum"] = _json_clone(enum)
    if "const" in schema:
        normalized["const"] = _json_clone(schema["const"])
    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        if key in schema:
            value = schema[key]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise RuntimeToolSchemaError("tool_schema_invalid")
            normalized[key] = value
    for key in ("minimum", "maximum"):
        if key in schema:
            value = schema[key]
            if not _is_number(value) or not math.isfinite(float(value)):
                raise RuntimeToolSchemaError("tool_schema_invalid")
            normalized[key] = value
    if schema_type == "object":
        properties = schema.get("properties", {})
        if not isinstance(properties, dict) or len(properties) > 128:
            raise RuntimeToolSchemaError("tool_schema_invalid")
        normalized["properties"] = {
            key: _normalize_schema(value, depth=depth + 1)
            for key, value in sorted(properties.items())
            if isinstance(key, str) and key
        }
        if len(normalized["properties"]) != len(properties):
            raise RuntimeToolSchemaError("tool_schema_invalid")
        required = schema.get("required", [])
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            raise RuntimeToolSchemaError("tool_schema_invalid")
        if not set(required).issubset(properties):
            raise RuntimeToolSchemaError("tool_schema_invalid")
        normalized["required"] = sorted(set(required))
        additional = schema.get("additionalProperties", True)
        if not isinstance(additional, bool):
            raise RuntimeToolSchemaError("tool_schema_unsupported")
        normalized["additionalProperties"] = additional
    if schema_type == "array":
        if "items" not in schema:
            raise RuntimeToolSchemaError("tool_schema_invalid")
        normalized["items"] = _normalize_schema(schema["items"], depth=depth + 1)
    return {key: normalized[key] for key in sorted(normalized)}


def _validate_value(schema: dict[str, Any], value: object, *, path: str, depth: int) -> None:
    if depth > MAX_TOOL_ARGUMENT_DEPTH:
        raise RuntimeToolSchemaError("tool_arguments_invalid", f"{path}: nesting")
    expected = schema.get("type", "object" if "properties" in schema else None)
    if not _matches_type(expected, value):
        raise RuntimeToolSchemaError("tool_arguments_invalid", f"{path}: expected {expected}")
    if "enum" in schema and value not in schema["enum"]:
        raise RuntimeToolSchemaError("tool_arguments_invalid", f"{path}: enum")
    if "const" in schema and value != schema["const"]:
        raise RuntimeToolSchemaError("tool_arguments_invalid", f"{path}: const")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - set(value)
        unknown = set(value) - set(properties)
        if missing or (unknown and schema.get("additionalProperties", True) is not True):
            raise RuntimeToolSchemaError("tool_arguments_invalid", f"{path}: fields")
        for key, item in value.items():
            if key in properties:
                _validate_value(properties[key], item, path=f"{path}.{key}", depth=depth + 1)
    elif isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)) or len(value) > int(schema.get("maxItems", len(value))):
            raise RuntimeToolSchemaError("tool_arguments_invalid", f"{path}: length")
        for index, item in enumerate(value):
            _validate_value(schema["items"], item, path=f"{path}[{index}]", depth=depth + 1)
    elif isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)) or len(value) > int(schema.get("maxLength", len(value))):
            raise RuntimeToolSchemaError("tool_arguments_invalid", f"{path}: length")
    elif _is_number(value):
        if "minimum" in schema and value < schema["minimum"]:
            raise RuntimeToolSchemaError("tool_arguments_invalid", f"{path}: minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise RuntimeToolSchemaError("tool_arguments_invalid", f"{path}: maximum")


def _matches_type(expected: object, value: object) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": _is_number(value),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, False)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _json_clone(value: object) -> object:
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise RuntimeToolSchemaError("tool_schema_invalid") from error
