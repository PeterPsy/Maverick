"""Gallery app service layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from errors import GalleryValidationError
from store import (
    MAX_PREVIEW_BYTES,
    file_info_payload,
    list_files,
    load_state,
    read_file_payload,
    reference_from_payload,
    rename_file_payload,
    seed_state,
)


def handle_action(data_root: Path, uploaded_root: Path, generated_root: Path, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    action = str(body.get("action") or "catalog")
    if action == "catalog":
        return 200, {
            "state": load_state(data_root),
            "files": list_files(uploaded_root=uploaded_root, generated_root=generated_root),
        }
    if action == "read_file":
        role, relative_path = reference_from_payload(
            role=str(body.get("role") or ""),
            relative_path=str(body.get("relative_path") or ""),
            workspace_relative_path=str(body.get("workspace_relative_path") or ""),
        )
        max_bytes = int(body.get("max_bytes") or MAX_PREVIEW_BYTES)
        return 200, read_file_payload(
            role=role,
            relative_path=relative_path,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
            max_bytes=max_bytes,
        )
    if action == "file_info":
        role, relative_path = reference_from_payload(
            role=str(body.get("role") or ""),
            relative_path=str(body.get("relative_path") or ""),
            workspace_relative_path=str(body.get("workspace_relative_path") or ""),
        )
        return 200, file_info_payload(
            role=role,
            relative_path=relative_path,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
    if action == "rename_file":
        role, relative_path = reference_from_payload(
            role=str(body.get("role") or ""),
            relative_path=str(body.get("relative_path") or ""),
            workspace_relative_path=str(body.get("workspace_relative_path") or ""),
        )
        return 200, rename_file_payload(
            role=role,
            relative_path=relative_path,
            new_name=str(body.get("new_name") or ""),
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
    if action == "health.check":
        seed_state(data_root)
        uploaded_root.mkdir(parents=True, exist_ok=True)
        generated_root.mkdir(parents=True, exist_ok=True)
        return 200, {"status": "ok", "file_count": len(list_files(uploaded_root=uploaded_root, generated_root=generated_root))}
    raise GalleryValidationError(f"Unknown action `{action}`.")
