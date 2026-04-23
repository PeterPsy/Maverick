"""Workspace attachment validation for Gmail send operations."""

from __future__ import annotations

from mimetypes import guess_type
from pathlib import Path
from typing import Any

from errors import GmailAppValidationError

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
ALLOWED_STORAGE_PREFIXES = ("storage/generated/", "storage/uploaded/")


def normalize_attachments(data_root: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return validated workspace attachments from a send payload."""

    workspace_root = workspace_root_from_data_root(data_root)
    attachments = raw_attachment_items(payload)
    normalized: list[dict[str, Any]] = []
    for item in attachments:
        attachment = normalize_attachment_item(workspace_root, item)
        if attachment["size_bytes"] > MAX_ATTACHMENT_BYTES:
            raise GmailAppValidationError(f"Attachment `{attachment['workspace_relative_path']}` exceeds the 20 MB Gmail App limit.")
        normalized.append(attachment)
    return normalized


def workspace_root_from_data_root(data_root: Path) -> Path:
    resolved = data_root.resolve()
    if resolved.name != "gmail-app" or resolved.parent.name != "data":
        raise GmailAppValidationError("Gmail App data root must end with data/gmail-app.")
    return resolved.parent.parent


def raw_attachment_items(payload: dict[str, Any]) -> list[Any]:
    values: list[Any] = []
    for key in ("attachments", "workspace_attachments", "workspace-attachments", "attachment_paths"):
        value = payload.get(key)
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            values.extend(value)
        else:
            values.append(value)
    return values


def normalize_attachment_item(workspace_root: Path, item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        candidate = {"workspace_relative_path": item}
    elif isinstance(item, dict):
        candidate = dict(item)
    else:
        raise GmailAppValidationError("Attachments must be workspace-relative paths or objects.")

    workspace_relative_path = str(
        candidate.get("workspace_relative_path")
        or candidate.get("path")
        or candidate.get("relative_path")
        or ""
    ).strip()
    if not workspace_relative_path:
        raise GmailAppValidationError("Attachment requires workspace_relative_path.")
    workspace_relative_path = workspace_relative_path.replace("\\", "/").lstrip("/")
    if not workspace_relative_path.startswith(ALLOWED_STORAGE_PREFIXES):
        raise GmailAppValidationError("Gmail attachments must come from storage/generated or storage/uploaded.")
    if ".." in Path(workspace_relative_path).parts:
        raise GmailAppValidationError("Attachment path may not contain parent traversal.")

    absolute_path = (workspace_root / workspace_relative_path).resolve()
    try:
        absolute_path.relative_to(workspace_root)
    except ValueError as error:
        raise GmailAppValidationError("Attachment must stay inside the workspace root.") from error
    if not absolute_path.is_file():
        raise GmailAppValidationError(f"Attachment `{workspace_relative_path}` was not found.")

    filename = str(candidate.get("filename") or absolute_path.name).strip() or absolute_path.name
    content_type = str(candidate.get("content_type") or guess_type(filename)[0] or "application/octet-stream")
    return {
        "workspace_relative_path": workspace_relative_path,
        "filename": filename,
        "content_type": content_type,
        "size_bytes": absolute_path.stat().st_size,
    }


def read_attachment_bytes(data_root: Path, attachment: dict[str, Any]) -> bytes:
    workspace_root = workspace_root_from_data_root(data_root)
    workspace_relative_path = str(attachment.get("workspace_relative_path") or "").replace("\\", "/").lstrip("/")
    absolute_path = (workspace_root / workspace_relative_path).resolve()
    try:
        absolute_path.relative_to(workspace_root)
    except ValueError as error:
        raise GmailAppValidationError("Attachment must stay inside the workspace root.") from error
    if not absolute_path.is_file():
        raise GmailAppValidationError(f"Attachment `{workspace_relative_path}` was not found.")
    return absolute_path.read_bytes()
