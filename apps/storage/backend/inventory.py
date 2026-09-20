"""Storage inventory API, selected only by an explicit migration marker.

The JSON adapter supports pre-cutover workspaces and verified reverse exports.
Migrated workspaces never read or rewrite files.json during ordinary operations.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from inventory_records import content_hash, parse_file_reference, preview_kind, stable_file_id
from storage_mutation_lock import storage_mutation_lock

__all__ = ["content_hash", "parse_file_reference", "preview_kind", "stable_file_id"]


def uses_sqlite(data_root: Path) -> bool:
    try:
        with (data_root / 'inventory-store.json').open() as handle:
            marker = json.load(handle)
    except FileNotFoundError:
        return False
    if marker.get('adapter') not in ('json', 'sqlite'):
        raise RuntimeError('Invalid Storage inventory adapter; explicit recovery is required.')
    return marker['adapter'] == 'sqlite'


def inventory_path(data_root: Path) -> Path:
    return data_root / ('inventory.sqlite' if uses_sqlite(data_root) else 'files.json')


def _call(name: str, kwargs: dict, *, write: bool):
    data_root = kwargs["data_root"]
    with storage_mutation_lock(data_root, shared=not (write or kwargs.get('sync'))):
        if uses_sqlite(data_root):
            import inventory_indexed as backend
        else:
            import inventory_legacy as backend
        return getattr(backend, name)(**kwargs)


def load_inventory(data_root: Path) -> dict[str, Any]:
    return _call('load_inventory', locals(), write=False)


def ensure_inventory(data_root: Path, *, uploaded_root: Path, generated_root: Path) -> dict[str, Any]:
    return _call('ensure_inventory', locals(), write=False)


def list_inventory_files(
    *,
    data_root: Path,
    uploaded_root: Path,
    generated_root: Path,
    sync: bool = False,
    query: str = "",
    role: str = "all",
    kind: str = "all",
    offset: int = 0,
    limit: int | None = None,
    sort_by: str | None = None,
    sort_direction: str = "desc",
    folder_path: str | None = None,
    file_ids: list[str] | None = None,
    workspace_relative_paths: list[str] | None = None,
    dataset_revision: int | None = None,
) -> dict[str, Any]:
    return _call('list_inventory_files', locals(), write=False)


def catalog_inventory_payload(
    *,
    data_root: Path,
    uploaded_root: Path,
    generated_root: Path,
    sync: bool = False,
    query: str = "",
    role: str = "all",
    kind: str = "all",
    offset: int = 0,
    limit: int | None = None,
    sort_by: str | None = None,
    sort_direction: str = "desc",
    folder_path: str | None = None,
    file_ids: list[str] | None = None,
    workspace_relative_paths: list[str] | None = None,
    dataset_revision: int | None = None,
) -> dict[str, Any]:
    return _call('catalog_inventory_payload', locals(), write=False)


def list_inventory_folders(*, data_root: Path, uploaded_root: Path, generated_root: Path, sync: bool = False) -> list[dict[str, Any]]:
    return _call('list_inventory_folders', locals(), write=False)


def resolve_file_record(
    *,
    data_root: Path,
    uploaded_root: Path,
    generated_root: Path,
    entity_id: str,
) -> dict[str, Any] | None:
    return _call('resolve_file_record', locals(), write=False)


def sync_inventory(data_root: Path, *, uploaded_root: Path, generated_root: Path) -> dict[str, Any]:
    return _call('sync_inventory', locals(), write=True)


def refresh_inventory(data_root: Path, *, uploaded_root: Path, generated_root: Path) -> dict[str, Any]:
    return _call('refresh_inventory', locals(), write=True)


def refresh_known_files(data_root: Path, *, uploaded_root: Path, generated_root: Path) -> dict[str, Any]:
    return _call('refresh_known_files', locals(), write=True)


def upsert_file_record(
    *,
    data_root: Path,
    role: str,
    root: Path,
    path: Path,
    sha256: str | None = None,
    preserve_path_id: bool = True,
) -> dict[str, Any]:
    return _call('upsert_file_record', locals(), write=True)


def upsert_remote_file_records(*, data_root: Path, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _call('upsert_remote_file_records', locals(), write=True)


def rename_file_record(
    *,
    data_root: Path,
    role: str,
    root: Path,
    old_relative_path: str,
    new_path: Path,
) -> dict[str, Any]:
    return _call('rename_file_record', locals(), write=True)


def move_file_record(
    *,
    data_root: Path,
    role: str,
    root: Path,
    old_relative_path: str,
    new_path: Path,
) -> dict[str, Any]:
    return _call('move_file_record', locals(), write=True)


def move_folder_records(
    *,
    data_root: Path,
    role: str,
    root: Path,
    old_relative_path: str,
    new_path: Path,
) -> dict[str, Any]:
    return _call('move_folder_records', locals(), write=True)


def remove_file_record(*, data_root: Path, role: str, relative_path: str) -> None:
    return _call('remove_file_record', locals(), write=True)


def remove_folder_records(*, data_root: Path, role: str, relative_path: str) -> None:
    return _call('remove_folder_records', locals(), write=True)


def upsert_directory_record(*, data_root: Path, role: str, root: Path, path: Path) -> dict[str, Any]:
    return _call('upsert_directory_record', locals(), write=True)
