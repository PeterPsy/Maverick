"""Workspace storage inventory helpers for the Gallery app."""

from __future__ import annotations

from pathlib import Path
import re



SCHEMA_VERSION = "1"
MAX_PREVIEW_BYTES = 8 * 1024 * 1024
MAX_READ_BYTES = 100 * 1024 * 1024
FILE_ROLES = {"uploaded", "generated"}
UPLOAD_BUCKET_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
VIEW_FILTER_ROLES = {"all", *FILE_ROLES}
VIEW_FILTER_KINDS = {"all", "image", "video", "audio", "markdown", "text", "pdf", "document", "presentation", "spreadsheet", "file"}
MAX_VIEW_QUERY_CHARS = 200
MAX_CUSTOM_VIEW_TITLE_CHARS = 140
MAX_CUSTOM_VIEW_FILES = 500
MAX_TEXT_PREVIEW_CACHE_ENTRIES = 200
MAX_MARKDOWN_EDIT_BYTES = 2 * 1024 * 1024
MAX_WRITE_BYTES = 25 * 1024 * 1024


def delete_file_payload(*, role: str, relative_path: str, uploaded_root: Path, generated_root: Path) -> dict:
    path = resolve_storage_file(
        role=role,
        relative_path=relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    record = file_record(role=role, root=root, path=path.resolve())
    path.unlink()
    return {"deleted": True, "file": record}
