"""Local workspace Storage file helpers for Memory source ingestion."""

from __future__ import annotations

from base64 import b64decode
import binascii
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from app_surface_transport import json_response, run_json_subprocess, run_maverick_app_mcp
from content_store import canonical_body
from errors import MemoryValidationError


MAX_LOCAL_SOURCE_BYTES = 1024 * 1024
STORAGE_PREVIEW_MAX_CHARS = 12000
TEXT_STORAGE_EXTENSIONS = {
    ".csv",
    ".json",
    ".log",
    ".md",
    ".rst",
    ".text",
    ".txt",
    ".yaml",
    ".yml",
}


def fetch_local_storage_file_source(data_root: Path, workspace_relative_path: str = "", file_id: str = "") -> dict[str, Any]:
    """Fetch one local Storage file through Storage-owned read surfaces."""

    workspace_relative_path = str(workspace_relative_path or "").strip()
    file_id = str(file_id or "").strip()
    if not workspace_relative_path and file_id:
        workspace_relative_path = resolve_storage_file_path(data_root, file_id)
    if not workspace_relative_path:
        raise MemoryValidationError("storage_file ingest requires file_id or workspace_relative_path.")
    info = _storage_file_surface(
        data_root,
        "storage_file_info",
        {"workspace_relative_path": workspace_relative_path},
    )
    file_payload = _file_payload(info)
    validate_storage_file_identity(
        file_payload,
        requested_file_id=file_id,
        requested_workspace_relative_path=workspace_relative_path,
    )
    resolved_workspace_relative_path = str(file_payload.get("workspace_relative_path") or workspace_relative_path).strip()
    size_bytes = _positive_int(file_payload.get("size_bytes"))
    preview = _preview_storage_text(data_root, resolved_workspace_relative_path, file_id=file_id)
    preview_text = str(preview.get("preview_text") or "")
    preview_file = preview.get("file") if isinstance(preview.get("file"), dict) else {}
    if preview_file:
        validate_storage_file_identity(
            preview_file,
            requested_file_id=file_id,
            requested_workspace_relative_path=resolved_workspace_relative_path,
        )
    body_markdown = canonical_body(preview_text) if preview_text else ""
    extraction_status = "truncated" if bool(preview.get("truncated") or preview.get("preview_truncated")) else "available"
    extraction_error = str(preview.get("error") or "")
    if not body_markdown and Path(resolved_workspace_relative_path).suffix.lower() in TEXT_STORAGE_EXTENSIONS:
        if size_bytes > MAX_LOCAL_SOURCE_BYTES:
            extraction_status = "unavailable"
            extraction_error = f"local text file exceeds {MAX_LOCAL_SOURCE_BYTES} bytes."
        else:
            read = _read_storage_text(data_root, resolved_workspace_relative_path, file_id=file_id)
            if read.get("body"):
                body_markdown = canonical_body(str(read["body"]))
                extraction_status = "available"
            else:
                extraction_status = "unavailable"
                extraction_error = str(read.get("error") or extraction_error or "Storage text extraction was unavailable.")
    elif not body_markdown:
        extraction_status = "unavailable"
        extraction_error = extraction_error or "Storage preview text was unavailable."
    return {
        "body_markdown": body_markdown,
        "preview_text": preview_text,
        "preview_truncated": bool(preview.get("truncated") or preview.get("preview_truncated"))
        or (len(preview_text) >= STORAGE_PREVIEW_MAX_CHARS and preview_text != body_markdown),
        "extraction_status": extraction_status,
        "extraction_error": extraction_error,
        "file": file_payload,
    }


def default_storage_file_surface(data_root: Path, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    workspace_root = workspace_root_for_data_root(data_root)
    if workspace_root is None:
        raise MemoryValidationError("Memory data_root must live under a workspace data directory for Storage ingestion.")
    if shutil.which("maverick"):
        return platform_storage_file_surface(workspace_root, tool_name, arguments)
    if os.environ.get("MAVERICK_MEMORY_ALLOW_LOCAL_STORAGE_FALLBACK") != "1":
        raise MemoryValidationError("Storage MCP surface is unavailable; local Storage source fallback is disabled.")
    return local_storage_file_surface(workspace_root, tool_name, arguments)


def platform_storage_file_surface(workspace_root: Path, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    completed = run_maverick_app_mcp(workspace_root, app_id="storage", operation="call", tool_name=tool_name, arguments=arguments)
    return _checked_storage_response(completed)


def local_storage_file_surface(workspace_root: Path, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    storage_root = Path(__file__).resolve().parents[2] / "storage"
    payload = {
        "app_id": "storage",
        "workspace_id": workspace_root.name,
        "data_root": str(workspace_root / "data" / "storage"),
        "uploaded_storage_root": str(workspace_root / "storage" / "uploaded"),
        "generated_storage_root": str(workspace_root / "storage" / "generated"),
        "tool_name": tool_name,
        "arguments": arguments,
    }
    completed = run_json_subprocess(
        [sys.executable, str(storage_root / "mcp" / "server.py")],
        cwd=storage_root,
        input_text=json.dumps(payload),
        label="local Storage MCP fallback",
    )
    return _checked_storage_response(completed)


_storage_file_surface = default_storage_file_surface


def resolve_storage_file_path(data_root: Path, file_id: str) -> str:
    response = _storage_file_surface(
        data_root,
        "storage_reference_resolve",
        {"entity_type": "file", "entity_id": file_id},
    )
    file_payload = _file_payload(response)
    validate_storage_file_identity(file_payload, requested_file_id=file_id, requested_workspace_relative_path="")
    workspace_relative_path = str(file_payload.get("workspace_relative_path") or "").strip()
    if not workspace_relative_path.startswith(("storage/uploaded/", "storage/generated/")):
        raise MemoryValidationError("storage_file ingest requires a local workspace Storage file.")
    return workspace_relative_path


def workspace_root_for_data_root(data_root: Path) -> Path | None:
    if data_root.parent.name != "data":
        return None
    return data_root.parent.parent


def _preview_storage_text(data_root: Path, workspace_relative_path: str, *, file_id: str) -> dict[str, Any]:
    try:
        return _storage_file_surface(
            data_root,
            "storage_preview_text",
            {"workspace_relative_path": workspace_relative_path, "max_chars": STORAGE_PREVIEW_MAX_CHARS},
        )
    except MemoryValidationError as error:
        return {"preview_text": "", "error": str(error)}


def _read_storage_text(data_root: Path, workspace_relative_path: str, *, file_id: str) -> dict[str, Any]:
    try:
        read = _storage_file_surface(
            data_root,
            "storage_read_file",
            {"workspace_relative_path": workspace_relative_path, "max_bytes": MAX_LOCAL_SOURCE_BYTES},
        )
        read_file = read.get("file") if isinstance(read.get("file"), dict) else {}
        if read_file:
            validate_storage_file_identity(
                read_file,
                requested_file_id=file_id,
                requested_workspace_relative_path=workspace_relative_path,
            )
        return {"body": _decode_storage_content(read)}
    except MemoryValidationError as error:
        return {"body": "", "error": str(error)}


def _checked_storage_response(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    response = json_response(completed, invalid_json_message="Storage file surface returned invalid JSON.")
    if completed.returncode != 0:
        raise MemoryValidationError(str(response.get("detail") or response.get("error") or "Storage file surface failed."))
    status_code = int(response.get("status_code") or 200)
    if status_code >= 400:
        raise MemoryValidationError(str(response.get("detail") or response.get("error") or "Storage file operation failed."))
    return response


def _file_payload(response: dict[str, Any]) -> dict[str, Any]:
    file_payload = response.get("file")
    if not isinstance(file_payload, dict):
        raise MemoryValidationError("Storage file surface did not return file metadata.")
    return file_payload


def validate_storage_file_identity(
    file_payload: dict[str, Any],
    *,
    requested_file_id: str,
    requested_workspace_relative_path: str,
) -> None:
    requested_id = str(requested_file_id or "").strip()
    returned_ids = storage_file_identity_values(file_payload)
    if requested_id and returned_ids and requested_id not in returned_ids:
        raise MemoryValidationError("storage_file file_id does not match the file returned by Storage.")
    requested_path = str(requested_workspace_relative_path or "").strip()
    returned_path = str(file_payload.get("workspace_relative_path") or "").strip()
    if requested_path and returned_path and requested_path != returned_path:
        raise MemoryValidationError("storage_file workspace_relative_path does not match the file returned by Storage.")


def storage_file_identity_values(file_payload: dict[str, Any]) -> set[str]:
    primary_ids = {
        value
        for value in (
            str(file_payload.get("file_id") or "").strip(),
            str(file_payload.get("id") or "").strip(),
        )
        if value
    }
    if primary_ids:
        return primary_ids
    path_id = str(file_payload.get("path_id") or "").strip()
    return {path_id} if path_id else set()


def _decode_storage_content(response: dict[str, Any]) -> str:
    if "content_base64" not in response:
        raise MemoryValidationError("Storage read_file did not return file content.")
    content_base64 = str(response.get("content_base64") or "")
    try:
        content = b64decode(content_base64, validate=True)
    except (ValueError, binascii.Error) as error:
        raise MemoryValidationError("Storage read_file returned invalid base64 content.") from error
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MemoryValidationError("storage_file ingest requires UTF-8 text content.") from error


def _positive_int(value: object) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)
