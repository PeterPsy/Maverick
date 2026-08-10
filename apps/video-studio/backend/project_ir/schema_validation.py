"""Small fail-closed evaluator for the committed Project IR JSON Schema profile."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

from .errors import ValidationIssue, issue


_ANNOTATIONS = {"$id", "$schema", "description", "title"}
_SUPPORTED = {
    "$defs",
    "$ref",
    "additionalProperties",
    "const",
    "enum",
    "items",
    "maxItems",
    "maxLength",
    "maxProperties",
    "maximum",
    "minItems",
    "minLength",
    "minProperties",
    "minimum",
    "pattern",
    "properties",
    "required",
    "type",
}


def schema_issues(document: object) -> list[ValidationIssue]:
    """Validate the structural JSON contract without an optional third-party runtime."""

    try:
        schema = _schema()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [issue("schema_contract_unavailable", "", "Project IR schema is unavailable.", reason=str(error))]
    problems: list[ValidationIssue] = []
    _validate(document, schema, schema, "", problems)
    return problems


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "schemas" / "project-ir.v1.schema.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Project IR schema root must be an object.")
    _assert_supported(value, value)
    return value


def _assert_supported(node: object, root: dict[str, Any]) -> None:
    if not isinstance(node, dict):
        return
    unknown = set(node) - _SUPPORTED - _ANNOTATIONS
    if unknown:
        raise ValueError("Unsupported Project IR schema keyword: " + ", ".join(sorted(unknown)))
    for key, value in node.items():
        if key in {"properties", "$defs"} and isinstance(value, dict):
            for child in value.values():
                _assert_supported(child, root)
        elif key in {"items", "additionalProperties"} and isinstance(value, dict):
            _assert_supported(value, root)
    reference = node.get("$ref")
    if reference is not None:
        _resolve_reference(root, reference)


def _validate(
    value: object,
    node: dict[str, Any],
    root: dict[str, Any],
    path: str,
    problems: list[ValidationIssue],
) -> None:
    if "$ref" in node:
        _validate(value, _resolve_reference(root, node["$ref"]), root, path, problems)
        return
    expected = node.get("type")
    if expected is not None and not _matches_type(value, expected):
        problems.append(issue("schema_type", path, "Value does not match the Project IR schema type."))
        return
    if "const" in node and value != node["const"]:
        problems.append(issue("schema_const", path, "Value does not match the Project IR schema constant."))
    if "enum" in node and value not in node["enum"]:
        problems.append(issue("schema_enum", path, "Value is outside the Project IR schema allowlist."))
    if isinstance(value, str):
        if len(value) < int(node.get("minLength", 0)):
            problems.append(issue("schema_string_length", path, "String is shorter than the Project IR minimum."))
        maximum = node.get("maxLength")
        if maximum is not None and len(value) > int(maximum):
            problems.append(issue("schema_string_length", path, "String exceeds the Project IR maximum."))
        pattern = node.get("pattern")
        if pattern is not None and re.search(str(pattern), value) is None:
            problems.append(issue("schema_string_pattern", path, "String does not match the Project IR schema pattern."))
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in node and value < int(node["minimum"]):
            problems.append(issue("schema_integer_range", path, "Integer is below the Project IR minimum."))
        if "maximum" in node and value > int(node["maximum"]):
            problems.append(issue("schema_integer_range", path, "Integer exceeds the Project IR maximum."))
    if isinstance(value, list):
        if len(value) < int(node.get("minItems", 0)):
            problems.append(issue("schema_array_length", path, "Array is shorter than the Project IR minimum."))
        maximum = node.get("maxItems")
        if maximum is not None and len(value) > int(maximum):
            problems.append(issue("schema_array_length", path, "Array exceeds the Project IR maximum."))
        item_schema = node.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate(item, item_schema, root, f"{path}/{index}", problems)
    if isinstance(value, dict):
        if len(value) < int(node.get("minProperties", 0)):
            problems.append(issue("schema_object_size", path, "Object has too few Project IR properties."))
        maximum = node.get("maxProperties")
        if maximum is not None and len(value) > int(maximum):
            problems.append(issue("schema_object_size", path, "Object has too many Project IR properties."))
        required = node.get("required", [])
        for name in sorted(set(required) - set(value)):
            problems.append(issue("schema_required", f"{path}/{_escape(name)}", "Required Project IR field is missing."))
        properties = node.get("properties", {})
        additional = node.get("additionalProperties", True)
        for name, item in value.items():
            child_path = f"{path}/{_escape(name)}"
            child_schema = properties.get(name) if isinstance(properties, dict) else None
            if isinstance(child_schema, dict):
                _validate(item, child_schema, root, child_path, problems)
            elif additional is False:
                problems.append(issue("schema_unknown_field", child_path, "Field is not declared by Project IR v1."))
            elif isinstance(additional, dict):
                _validate(item, additional, root, child_path, problems)


def _matches_type(value: object, expected: object) -> bool:
    choices = expected if isinstance(expected, list) else [expected]
    return any(
        (choice == "null" and value is None)
        or (choice == "boolean" and isinstance(value, bool))
        or (choice == "integer" and isinstance(value, int) and not isinstance(value, bool))
        or (choice == "string" and isinstance(value, str))
        or (choice == "array" and isinstance(value, list))
        or (choice == "object" and isinstance(value, dict))
        for choice in choices
    )


def _resolve_reference(root: dict[str, Any], reference: object) -> dict[str, Any]:
    if not isinstance(reference, str) or not reference.startswith("#/"):
        raise ValueError("Project IR schema contains an unsupported reference.")
    current: object = root
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise ValueError("Project IR schema contains an unresolved reference.")
        current = current[part]
    if not isinstance(current, dict):
        raise ValueError("Project IR schema reference must resolve to an object.")
    return current


def _escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")
