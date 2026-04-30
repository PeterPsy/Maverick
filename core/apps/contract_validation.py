"""Validation helpers for canonical app contract parsing."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from core.apps.contract_common import APP_ID_PATTERN
from core.apps.errors import AppContractValidationError


WIDGET_ID_PATTERN = APP_ID_PATTERN
CONTENT_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*)+$")
ENTITY_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
INTERFACE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$")
INTERFACE_VERSION_PATTERN = re.compile(r"^\^?[0-9]+(?:\.[0-9]+){0,2}$")
PERMISSION_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)*$")
NETWORK_TARGET_PATTERN = re.compile(r"^\*$|^[a-z0-9][a-z0-9.-]*(:[0-9]{1,5})?$")


def _reject_unexpected_fields(payload: dict[str, Any], allowed: set[str], *, label: str) -> None:
    unexpected_keys = set(payload) - allowed
    if unexpected_keys:
        unexpected = ", ".join(sorted(unexpected_keys))
        raise AppContractValidationError(f"Unsupported {label} field(s): {unexpected}.")

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

def _expect_permission_name_list(payload: dict[str, Any], key: str, *, label: str) -> list[str]:
    values = _expect_string_list(payload, key)
    for value in values:
        if not PERMISSION_NAME_PATTERN.fullmatch(value):
            raise AppContractValidationError(f"`{label}.{key}` entries must use lowercase permission names, got `{value}`.")
    return values

def _expect_network_target_list(payload: dict[str, Any], key: str, *, label: str) -> list[str]:
    values = _expect_string_list(payload, key)
    for value in values:
        if not NETWORK_TARGET_PATTERN.fullmatch(value):
            raise AppContractValidationError(f"`{label}.{key}` entries must use hostnames, host:port, or `*`, got `{value}`.")
    return values

def _expect_slug(payload: dict[str, Any], key: str) -> str:
    value = _expect_string(payload, key)
    if not WIDGET_ID_PATTERN.fullmatch(value):
        raise AppContractValidationError(f"`{key}` must use lowercase kebab-case, got `{value}`.")
    return value

def _expect_entity_type(payload: dict[str, Any], key: str) -> str:
    value = _expect_string(payload, key)
    if not ENTITY_TYPE_PATTERN.fullmatch(value):
        raise AppContractValidationError(f"`{key}` must use lowercase snake_case, got `{value}`.")
    return value

def _expect_content_kind_list(payload: dict[str, Any], key: str) -> list[str]:
    values = _expect_string_list(payload, key)
    for value in values:
        if not CONTENT_KIND_PATTERN.fullmatch(value):
            raise AppContractValidationError(f"`{key}` entries must use stable dotted kinds, got `{value}`.")
    return values

def _expect_interface_id(payload: dict[str, Any], key: str) -> str:
    value = _expect_string(payload, key)
    if not INTERFACE_ID_PATTERN.fullmatch(value):
        raise AppContractValidationError(f"`{key}` must use stable dotted interface ids, got `{value}`.")
    return value

def _expect_interface_version(payload: dict[str, Any], key: str) -> str:
    value = _expect_string(payload, key)
    if not INTERFACE_VERSION_PATTERN.fullmatch(value):
        raise AppContractValidationError(
            f"`{key}` must be a numeric interface version such as `1` or a major-compatible range such as `^1`, got `{value}`."
        )
    return value

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

def _expect_relative_mount_path(source_root: Path, relative_path: str, *, label: str) -> str:
    if Path(relative_path).is_absolute():
        raise AppContractValidationError(f"`{label}` must be a relative path.")
    resolved = (source_root / relative_path).resolve()
    root = source_root.resolve()
    if resolved != root and root not in resolved.parents:
        raise AppContractValidationError(f"`{label}` escapes app root `{source_root}`.")
    if not resolved.exists() or not resolved.is_dir():
        raise AppContractValidationError(f"`{label}` must resolve to an existing directory under app root `{source_root}`.")
    return relative_path

def _expect_timeout(payload: dict[str, Any], key: str, *, default: int) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int) or value <= 0:
        raise AppContractValidationError(f"`{key}` must be a positive integer timeout.")
    return value
