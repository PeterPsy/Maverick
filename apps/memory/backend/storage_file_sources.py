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
    suffix = Path(workspace_relative_path).suffix.lower()
    if suffix not in TEXT_STORAGE_EXTENSIONS:
        raise MemoryValidationError("storage_file ingest currently supports text and Markdown-like files.")
    info = _storage_file_surface(
        data_root,
        "storage_file_info",
        {"workspace_relative_path": workspace_relative_path},
    )
    file_payload = _file_payload(info)
    size_bytes = _positive_int(file_payload.get("size_bytes"))
    if size_bytes > MAX_LOCAL_SOURCE_BYTES:
        raise MemoryValidationError(f"storage_file ingest supports local text files up to {MAX_LOCAL_SOURCE_BYTES} bytes.")
    preview = _storage_file_surface(
        data_root,
        "storage_preview_text",
        {"workspace_relative_path": workspace_relative_path, "max_chars": STORAGE_PREVIEW_MAX_CHARS},
    )
    read = _storage_file_surface(
        data_root,
        "storage_read_file",
        {"workspace_relative_path": workspace_relative_path, "max_bytes": MAX_LOCAL_SOURCE_BYTES},
    )
    body_markdown = canonical_body(_decode_storage_content(read))
    preview_text = str(preview.get("preview_text") or "")
    return {
        "body_markdown": body_markdown,
        "preview_text": preview_text,
        "preview_truncated": len(preview_text) >= STORAGE_PREVIEW_MAX_CHARS and preview_text != body_markdown,
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
    completed = subprocess.run(
        [
            "maverick",
            "app",
            "storage",
            "mcp",
            "call",
            tool_name,
            "--json",
            *_mcp_cli_argument_flags(arguments),
        ],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
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
    completed = subprocess.run(
        [sys.executable, str(storage_root / "mcp" / "server.py")],
        cwd=storage_root,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
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
    workspace_relative_path = str(file_payload.get("workspace_relative_path") or "").strip()
    if not workspace_relative_path.startswith(("storage/uploaded/", "storage/generated/")):
        raise MemoryValidationError("storage_file ingest requires a local workspace Storage file.")
    return workspace_relative_path


def workspace_root_for_data_root(data_root: Path) -> Path | None:
    if data_root.parent.name != "data":
        return None
    return data_root.parent.parent


def _mcp_cli_argument_flags(arguments: dict[str, Any]) -> list[str]:
    cli_args: list[str] = []
    for key, value in arguments.items():
        if value is None or value == "":
            continue
        cli_args.extend([f"--{key.replace('_', '-')}", str(value)])
    return cli_args


def _checked_storage_response(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    try:
        response = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as error:
        raise MemoryValidationError("Storage file surface returned invalid JSON.") from error
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
