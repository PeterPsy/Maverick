"""Gallery app service layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from errors import GalleryValidationError
from store import (
    MAX_PREVIEW_BYTES,
    delete_file_payload,
    file_info_payload,
    list_files,
    load_state,
    preview_text_payload,
    read_file_payload,
    reference_from_payload,
    rename_file_payload,
    seed_state,
    clear_custom_view_payload,
    set_custom_view_payload,
    set_view_filter_payload,
)

REFERENCE_MANIFEST = {
    "app_id": "gallery",
    "schema_version": "1",
    "entity_types": [
        {"entity_type": "file", "display_name": "Workspace File", "id_stability": "stable", "searchable": True, "resolvable": True, "summarizable": True, "deep_link_supported": True}
    ],
}


def _file_reference(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "app_id": "gallery",
        "entity_type": "file",
        "entity_id": record["id"],
        "title": record["name"],
        "subtitle": record["workspace_relative_path"],
        "summary": f"{record['preview_kind']} file, {record['size_bytes']} bytes",
        "confidence": 1.0,
        "deep_link": f"/apps/gallery?path={record['workspace_relative_path']}",
        "workspace_relative_path": record["workspace_relative_path"],
    }


def handle_action(data_root: Path, uploaded_root: Path, generated_root: Path, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    action = str(body.get("action") or "catalog")
    if action == "catalog":
        return 200, {
            "state": load_state(data_root),
            "files": list_files(uploaded_root=uploaded_root, generated_root=generated_root),
        }
    if action == "view_filter":
        return 200, {"state": load_state(data_root)}
    if action == "set_view_filter":
        return 200, set_view_filter_payload(
            data_root=data_root,
            query=body.get("query") if "query" in body else None,
            role=body.get("role") if "role" in body else None,
            kind=body.get("kind") if "kind" in body else None,
            preserve_custom=bool(body.get("preserve_custom")),
        )
    if action == "set_custom_view":
        return 200, set_custom_view_payload(
            data_root=data_root,
            title=body.get("title"),
            file_ids=body.get("file_ids"),
            workspace_relative_paths=body.get("workspace_relative_paths"),
            files=body.get("files"),
            query=body.get("query") if "query" in body else None,
            role=body.get("role") if "role" in body else None,
            kind=body.get("kind") if "kind" in body else None,
        )
    if action == "clear_custom_view":
        return 200, clear_custom_view_payload(data_root=data_root)
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
    if action == "preview_text":
        role, relative_path = reference_from_payload(
            role=str(body.get("role") or ""),
            relative_path=str(body.get("relative_path") or ""),
            workspace_relative_path=str(body.get("workspace_relative_path") or ""),
        )
        max_chars = int(body.get("max_chars") or 4000)
        return 200, preview_text_payload(
            role=role,
            relative_path=relative_path,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
            data_root=data_root,
            max_chars=max_chars,
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
    if action == "delete_file":
        role, relative_path = reference_from_payload(
            role=str(body.get("role") or ""),
            relative_path=str(body.get("relative_path") or ""),
            workspace_relative_path=str(body.get("workspace_relative_path") or ""),
        )
        return 200, delete_file_payload(
            role=role,
            relative_path=relative_path,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
    if action == "health.check":
        seed_state(data_root)
        uploaded_root.mkdir(parents=True, exist_ok=True)
        generated_root.mkdir(parents=True, exist_ok=True)
        return 200, {"status": "ok", "file_count": len(list_files(uploaded_root=uploaded_root, generated_root=generated_root))}
    if action == "references.manifest":
        return 200, REFERENCE_MANIFEST
    if action == "references.search":
        query = str(body.get("query") or "").casefold()
        limit = max(1, min(int(body.get("limit") or 10), 50))
        files = [_file_reference(item) for item in list_files(uploaded_root=uploaded_root, generated_root=generated_root)]
        if query:
            files = [
                item for item in files
                if query in item["title"].casefold() or query in item["subtitle"].casefold()
            ]
        return 200, {"results": files[:limit]}
    if action == "references.resolve":
        entity_id = str(body.get("entity_id") or "").strip()
        item = next(
            (_file_reference(record) for record in list_files(uploaded_root=uploaded_root, generated_root=generated_root) if record["id"] == entity_id or record["workspace_relative_path"] == entity_id),
            None,
        )
        return 200, {"exists": False, "app_id": "gallery", "entity_type": "file", "entity_id": entity_id} if item is None else {"exists": True, **item}
    if action == "references.summarize":
        resolved_status, resolved = handle_action(
            data_root,
            uploaded_root,
            generated_root,
            {"action": "references.resolve", "entity_id": str(body.get("entity_id") or "")},
        )
        if resolved_status != 200 or not resolved.get("exists"):
            return 200, {"summary": "", "safe_fields": {}, "source_updated_at": ""}
        return 200, {
            "summary": resolved.get("summary") or resolved.get("title") or "",
            "safe_fields": {"title": resolved.get("title"), "path": resolved.get("workspace_relative_path")},
            "source_updated_at": "",
        }
    raise GalleryValidationError(f"Unknown action `{action}`.")
