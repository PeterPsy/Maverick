"""File identity and export manifest helpers for workspace exports."""

from __future__ import annotations

import json
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import uuid

from core.apps.models import WorkspaceAppBindingRecord
from core.workspaces.models import ExportManifest, ExportedAppReference, FileIdentity, FileRole


FILE_INVENTORY_SCHEMA_VERSION = "1"
WORKSPACE_EXPORT_SCHEMA_VERSION = "2"


def _inventory_root(workspace_root: Path) -> Path:
    return workspace_root / ".maverick"


def _inventory_path(workspace_root: Path) -> Path:
    return _inventory_root(workspace_root) / "file_inventory.json"


def _load_inventory(workspace_root: Path) -> dict:
    inventory_path = _inventory_path(workspace_root)
    if not inventory_path.exists():
        return {"schema_version": FILE_INVENTORY_SCHEMA_VERSION, "entries": []}
    return json.loads(inventory_path.read_text(encoding="utf-8"))


def _save_inventory(workspace_root: Path, inventory: dict) -> None:
    inventory_dir = _inventory_root(workspace_root)
    inventory_dir.mkdir(parents=True, exist_ok=True)
    _inventory_path(workspace_root).write_text(json.dumps(inventory, indent=2, sort_keys=True), encoding="utf-8")


def _file_role_for_path(relative_path: str) -> FileRole:
    if relative_path.startswith("storage/uploaded/"):
        return "uploaded"
    if relative_path.startswith("storage/generated/"):
        return "generated"
    if relative_path.startswith("data/"):
        return "app_data"
    return "other"


def _find_stable_file_id(inventory: dict, *, relative_path: str, content_hash: str, file_role: FileRole) -> tuple[str, str]:
    entries: list[dict] = inventory["entries"]
    for entry in entries:
        if entry["relative_path"] == relative_path:
            return entry["file_id"], entry["created_at"]

    candidates = [entry for entry in entries if entry["content_hash"] == content_hash and entry["file_role"] == file_role]
    if len(candidates) == 1:
        return candidates[0]["file_id"], candidates[0]["created_at"]

    return uuid.uuid4().hex, datetime.now(tz=UTC).isoformat()


def _upsert_inventory_entry(
    inventory: dict,
    *,
    file_id: str,
    relative_path: str,
    content_hash: str,
    file_role: FileRole,
    created_at: str,
    updated_at: str,
) -> None:
    entries: list[dict] = inventory["entries"]
    updated_entries = [entry for entry in entries if entry["file_id"] != file_id]
    updated_entries.append(
        {
            "file_id": file_id,
            "relative_path": relative_path,
            "content_hash": content_hash,
            "file_role": file_role,
            "created_at": created_at,
            "updated_at": updated_at,
        }
    )
    inventory["entries"] = sorted(updated_entries, key=lambda item: item["file_id"])


def build_file_identity(file_path: Path, workspace_root: Path) -> FileIdentity:
    """Build stable file identity metadata for one file inside a workspace root."""
    resolved_file_path = file_path.resolve()
    resolved_workspace_root = workspace_root.resolve()
    relative_path = resolved_file_path.relative_to(resolved_workspace_root).as_posix()
    stat_result = resolved_file_path.stat()
    content_hash = hashlib.sha256(resolved_file_path.read_bytes()).hexdigest()
    file_role = _file_role_for_path(relative_path)
    inventory = _load_inventory(resolved_workspace_root)
    updated_at = datetime.fromtimestamp(stat_result.st_mtime, tz=UTC).isoformat()
    file_id, created_at = _find_stable_file_id(
        inventory,
        relative_path=relative_path,
        content_hash=content_hash,
        file_role=file_role,
    )
    _upsert_inventory_entry(
        inventory,
        file_id=file_id,
        relative_path=relative_path,
        content_hash=content_hash,
        file_role=file_role,
        created_at=created_at,
        updated_at=updated_at,
    )
    _save_inventory(resolved_workspace_root, inventory)
    return FileIdentity(
        file_id=file_id,
        relative_path=relative_path,
        content_hash=content_hash,
        file_role=file_role,
        created_at=created_at,
        updated_at=updated_at,
    )


def build_export_manifest(
    workspace_id: str,
    workspace_root: Path,
    files: list[Path],
    *,
    app_bindings: list[WorkspaceAppBindingRecord] | None = None,
    schema_versions: dict[str, str] | None = None,
) -> ExportManifest:
    """Build a canonical workspace export manifest."""
    identities = [
        build_file_identity(file_path=file_path, workspace_root=workspace_root)
        for file_path in sorted(files)
        if _include_in_export(file_path=file_path, workspace_root=workspace_root)
    ]
    known_apps = [
        ExportedAppReference(
            app_id=binding.app_id,
            version=binding.active_version,
            status=binding.status,
            source_kind=binding.source_kind,
            source_record_id=binding.source_record_id,
        )
        for binding in sorted(app_bindings or [], key=lambda item: item.app_id)
    ]
    return ExportManifest(
        manifest_version=WORKSPACE_EXPORT_SCHEMA_VERSION,
        workspace_id=workspace_id,
        exported_at=datetime.now(tz=UTC).isoformat(),
        schema_versions=schema_versions
        or {
            "workspace_export": WORKSPACE_EXPORT_SCHEMA_VERSION,
            "file_inventory": FILE_INVENTORY_SCHEMA_VERSION,
        },
        known_apps=known_apps,
        files=identities,
    )


def _include_in_export(*, file_path: Path, workspace_root: Path) -> bool:
    relative_path = file_path.resolve().relative_to(workspace_root.resolve()).as_posix()
    return not (
        relative_path.startswith("logs/")
        or relative_path.startswith(".maverick/")
    )
