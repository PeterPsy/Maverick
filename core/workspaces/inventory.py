"""Workspace file inventory and filesystem discovery helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import uuid

from core.workspaces.models import FileIdentity, FileRole


FILE_INVENTORY_SCHEMA_VERSION = "1"


def inventory_root(workspace_root: Path) -> Path:
    """Return the internal inventory metadata root for one workspace."""
    return workspace_root / ".maverick"


def inventory_path(workspace_root: Path) -> Path:
    """Return the inventory file path for one workspace."""
    return inventory_root(workspace_root) / "file_inventory.json"


def load_file_inventory(workspace_root: Path) -> dict:
    """Load the persisted file inventory for one workspace."""
    file_path = inventory_path(workspace_root)
    if not file_path.exists():
        return {"schema_version": FILE_INVENTORY_SCHEMA_VERSION, "entries": []}
    return json.loads(file_path.read_text(encoding="utf-8"))


def save_file_inventory(workspace_root: Path, inventory: dict) -> None:
    """Persist the file inventory for one workspace."""
    root = inventory_root(workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    inventory_path(workspace_root).write_text(json.dumps(inventory, indent=2, sort_keys=True), encoding="utf-8")


def file_role_for_relative_path(relative_path: str) -> FileRole:
    """Classify one workspace-relative path into its canonical file role."""
    if relative_path.startswith("storage/uploaded/"):
        return "uploaded"
    if relative_path.startswith("storage/generated/"):
        return "generated"
    if relative_path.startswith("data/"):
        return "app_data"
    return "other"


def discover_workspace_storage_files(workspace_root: Path) -> list[Path]:
    """Return uploaded/generated files discovered directly from the workspace filesystem."""
    roots = (
        workspace_root / "storage" / "uploaded",
        workspace_root / "storage" / "generated",
    )
    discovered: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        discovered.extend(path for path in root.rglob("*") if path.is_file())
    return sorted(path.resolve() for path in discovered)


def _find_stable_file_id(
    inventory: dict,
    *,
    workspace_root: Path,
    relative_path: str,
    content_hash: str,
    file_role: FileRole,
) -> tuple[str, str]:
    entries: list[dict] = inventory["entries"]
    for entry in entries:
        if entry["relative_path"] == relative_path:
            return entry["file_id"], entry["created_at"]

    candidates = [
        entry
        for entry in entries
        if entry["content_hash"] == content_hash
        and entry["file_role"] == file_role
        and not (workspace_root / entry["relative_path"]).exists()
    ]
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
    file_role = file_role_for_relative_path(relative_path)
    inventory = load_file_inventory(resolved_workspace_root)
    updated_at = datetime.fromtimestamp(stat_result.st_mtime, tz=UTC).isoformat()
    file_id, created_at = _find_stable_file_id(
        inventory,
        workspace_root=resolved_workspace_root,
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
    save_file_inventory(resolved_workspace_root, inventory)
    return FileIdentity(
        file_id=file_id,
        relative_path=relative_path,
        content_hash=content_hash,
        file_role=file_role,
        created_at=created_at,
        updated_at=updated_at,
    )
