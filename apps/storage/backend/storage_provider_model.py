"""Provider-aware file record helpers for Storage."""

from __future__ import annotations

from typing import Any

from errors import StorageValidationError


LOCAL_PROVIDER = "local"
GOOGLE_DRIVE_PROVIDER = "google_drive"
REMOTE_PROVIDERS = {GOOGLE_DRIVE_PROVIDER}
FILE_ROLES = {"uploaded", "generated"}

LOCAL_FILE_CAPABILITIES = {
    "can_read": True,
    "can_write": True,
    "can_move": True,
    "can_rename": True,
    "can_delete": True,
    "can_preview": True,
    "can_index": True,
}

REMOTE_FILE_CAPABILITIES = {
    "can_read": False,
    "can_write": False,
    "can_move": False,
    "can_rename": False,
    "can_delete": False,
    "can_preview": False,
    "can_index": False,
}


def normalize_provider(value: object, *, role: str = "") -> str:
    provider = str(value or "").strip()
    if provider:
        return provider
    return LOCAL_PROVIDER if role in FILE_ROLES else ""


def provider_is_local(provider: object) -> bool:
    return str(provider or LOCAL_PROVIDER).strip() == LOCAL_PROVIDER


def reject_remote_workspace_relative_path(
    *,
    provider: object,
    workspace_relative_path: object = None,
    workspace_relative_paths: object = None,
) -> None:
    normalized_provider = normalize_provider(provider)
    has_workspace_path = bool(str(workspace_relative_path or "").strip())
    if isinstance(workspace_relative_paths, list):
        has_workspace_path = has_workspace_path or any(str(item or "").strip() for item in workspace_relative_paths)
    elif workspace_relative_paths is not None:
        has_workspace_path = has_workspace_path or bool(str(workspace_relative_paths or "").strip())
    if normalized_provider in REMOTE_PROVIDERS and has_workspace_path:
        raise StorageValidationError("workspace_relative_path is only valid for local Storage providers.")


def normalize_capabilities(raw_value: object, *, provider: str) -> dict[str, bool]:
    defaults = LOCAL_FILE_CAPABILITIES if provider == LOCAL_PROVIDER else REMOTE_FILE_CAPABILITIES
    if not isinstance(raw_value, dict):
        return dict(defaults)
    capabilities = dict(defaults)
    for key in defaults:
        if key in raw_value:
            capabilities[key] = bool(raw_value[key])
    return capabilities


def normalize_remote_locator(raw_value: object, *, provider: str, drive_file_id: str = "") -> dict[str, Any]:
    locator = dict(raw_value) if isinstance(raw_value, dict) else {}
    if provider == GOOGLE_DRIVE_PROVIDER and drive_file_id:
        locator["drive_file_id"] = drive_file_id
    return locator
