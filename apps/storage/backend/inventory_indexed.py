"""Indexed inventory API. Only explicit sync requests inspect unrelated files."""

from __future__ import annotations

import json
from pathlib import Path
import stat as stat_module

from errors import StorageConflictError, StorageValidationError
from inventory_queries import catalog_page, directory_children
from inventory_records import (
    _deleted_directory_entry, _deleted_entry, _directory_entry_for_path,
    _entry_for_path, _normalize_entry, _preserve_remote_index_state,
    _public_folder_record, _public_record as _record, _timestamp, parse_file_reference,
)
from inventory_sqlite import InventoryIndex


def _public_record(item: dict) -> dict:
    return {**_record(item), 'updated_at': item.get('updated_at', '')}


def load_inventory(data_root: Path) -> dict:
    # Compatibility export for administrative callers; never used by catalog/resolver.
    from inventory_migration import export_inventory
    return export_inventory(InventoryIndex(data_root))


def ensure_inventory(data_root: Path, *, uploaded_root: Path, generated_root: Path) -> dict:
    return load_inventory(data_root)


def sync_inventory(data_root: Path, *, uploaded_root: Path, generated_root: Path) -> dict:
    from inventory_reconcile import reconcile_inventory
    return reconcile_inventory(data_root, uploaded_root=uploaded_root, generated_root=generated_root)


refresh_inventory = sync_inventory
refresh_known_files = sync_inventory


def catalog_inventory_payload(*, data_root: Path, uploaded_root: Path, generated_root: Path,
                              sync: bool = False, **filters) -> dict:
    if sync:
        sync_inventory(data_root, uploaded_root=uploaded_root, generated_root=generated_root)
    payload = catalog_page(InventoryIndex(data_root), **filters)
    if payload['status'] == 'catalog_changed':
        return payload
    payload['files'] = [_public_record(item) for item in payload['files']]
    payload['folders'] = [{**_public_folder_record(item), **{key: item[key] for key in
        ('total_files', 'total_bytes', 'total_folders', 'count_scope')}} for item in payload['folders']]
    payload['inventory'] = {'schema_version': '2', 'updated_at': str(payload['dataset_revision'])}
    return payload


list_inventory_files = catalog_inventory_payload


def list_inventory_folders(*, data_root: Path, uploaded_root: Path, generated_root: Path,
                           sync: bool = False) -> list[dict]:
    if sync:
        sync_inventory(data_root, uploaded_root=uploaded_root, generated_root=generated_root)
    with InventoryIndex(data_root).transaction() as connection:
        return [{**_public_folder_record(item), 'total_files': item['total_files'],
            'total_bytes': item['total_bytes']} for role in ('uploaded', 'generated')
            for item in directory_children(connection, role=role, parent='')]


def resolve_file_record(*, data_root: Path, uploaded_root: Path, generated_root: Path,
                        entity_id: str) -> dict | None:
    value = str(entity_id or '').strip()
    index = InventoryIndex(data_root)
    with index.transaction() as connection:
        if connection.execute('SELECT 1 FROM operations LIMIT 1').fetchone():
            raise StorageConflictError('Storage is recovering an interrupted mutation.', conflict='inventory_recovery_required')
        item = index.get(connection, value)
        if item is None and (reference := parse_file_reference(value)):
            item = index.by_path(connection, *reference)
        return _public_record(item) if item and item.get('status') == 'active' else None


def file_signature(stat) -> tuple:
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_dev, stat.st_ino


def _local_path(root: Path, path: Path, *, directory: bool = False) -> tuple[Path, Path, object]:
    root = root.resolve()
    path = path.resolve()
    if root not in path.parents and not (directory and path == root):
        raise StorageValidationError('Storage path escapes the selected root.')
    info = path.stat()
    if not (stat_module.S_ISDIR(info.st_mode) if directory else stat_module.S_ISREG(info.st_mode)):
        raise StorageValidationError('Folder does not exist.' if directory else 'File does not exist.')
    return root, path, info


def capture_directories(*, role: str, root: Path, path: Path) -> list[dict]:
    relative = path.relative_to(root)
    entries = [_directory_entry_for_path(role=role, root=root, path=root)]
    for end in range(1, len(relative.parts) + 1):
        entries.append(_directory_entry_for_path(role=role, root=root, path=root.joinpath(*relative.parts[:end])))
    return entries


def put_directory(index: InventoryIndex, connection, entry: dict) -> None:
    previous = connection.execute('SELECT document FROM directories WHERE directory_id=?', (entry['id'],)).fetchone()
    if previous:
        old = json.loads(previous[0])
        # A directory mtime changes when children change; exposing that is substantive.
        entry['updated_at'] = old.get('updated_at', '')
        if entry != old:
            entry['updated_at'] = _timestamp()
    index.put_directory(connection, entry)


def put_local_file(index: InventoryIndex, connection, *, role: str, root: Path, path: Path,
                   info, previous: dict | None, sha256: str | None = None,
                   file_id: str | None = None, preserve_hash: bool = False) -> dict:
    signature = file_signature(info)
    same_source = bool(previous and index.signature(connection, previous['file_id']) == signature)
    entry = _entry_for_path(role=role, root=root, path=path, stat=info,
        file_id=previous['file_id'] if previous else file_id,
        sha256=sha256 if sha256 is not None else (previous.get('sha256', '') if previous and (same_source or preserve_hash) else ''),
        created_at=previous.get('created_at') or _timestamp() if previous else _timestamp(), status='active')
    if previous:
        for key in ('indexed', 'stale', 'index_status', 'indexed_at', 'indexed_source_version',
                    'memory_node_id', 'memory_external_ref_id', 'memory_source_version_id'):
            entry[key] = previous.get(key, entry[key])
        if not same_source and not preserve_hash and previous.get('indexed'):
            entry.update(stale=True, index_status='stale')
        entry['updated_at'] = previous.get('updated_at', '')
        if entry != previous or not same_source:
            entry['updated_at'] = _timestamp()
    index.put_file(connection, entry)
    index.set_signature(connection, entry['file_id'], signature)
    return entry


def upsert_file_record(*, data_root: Path, role: str, root: Path, path: Path,
                       sha256: str | None = None, preserve_path_id: bool = True,
                       file_id: str | None = None) -> dict:
    root, path, info = _local_path(root, path)
    directories = capture_directories(role=role, root=root, path=path.parent)
    index = InventoryIndex(data_root)
    with index.transaction(write=True) as connection:
        previous = index.by_path(connection, role, path.relative_to(root).as_posix())
        if previous and not preserve_path_id:
            index.put_file(connection, _deleted_entry(previous, now=_timestamp()))
            previous = None
        entry = put_local_file(index, connection, role=role, root=root, path=path,
            info=info, previous=previous, sha256=sha256, file_id=file_id)
        for directory in directories:
            put_directory(index, connection, directory)
    return _public_record(entry)


def upsert_directory_record(*, data_root: Path, role: str, root: Path, path: Path) -> dict:
    root, path, _ = _local_path(root, path, directory=True)
    entries = capture_directories(role=role, root=root, path=path)
    index = InventoryIndex(data_root)
    with index.transaction(write=True) as connection:
        for entry in entries:
            put_directory(index, connection, entry)
    return _public_folder_record(entries[-1])


def upsert_remote_file_records(*, data_root: Path, records: list[dict]) -> list[dict]:
    index = InventoryIndex(data_root)
    captured = []
    with index.transaction(write=True) as connection:
        for record in records:
            entry = _normalize_entry(record)
            previous = index.get(connection, entry['file_id']) or index.by_remote(connection,
                entry['provider'], entry['connection_id'], entry['drive_file_id'])
            if previous:
                entry['file_id'] = entry['id'] = previous['file_id']
                entry['created_at'] = previous.get('created_at', '')
                entry = _preserve_remote_index_state(existing=previous, entry=entry)
                entry['updated_at'] = previous.get('updated_at', '')
            if entry != previous:
                entry['updated_at'] = _timestamp()
            index.put_file(connection, entry)
            captured.append(_public_record(entry))
    return captured


def move_file_record(*, data_root: Path, role: str, root: Path, old_relative_path: str, new_path: Path) -> dict:
    root, new_path, info = _local_path(root, new_path)
    directories = capture_directories(role=role, root=root, path=new_path.parent)
    index = InventoryIndex(data_root)
    with index.transaction(write=True) as connection:
        previous = index.by_path(connection, role, old_relative_path) or index.by_path(connection, role, new_path.relative_to(root).as_posix())
        old_signature = index.signature(connection, previous['file_id']) if previous else None
        # A same-filesystem rename changes ctime but preserves bytes, mtime and inode.
        new_signature = file_signature(info)
        same_bytes = bool(old_signature and old_signature[:2] == new_signature[:2] and old_signature[3:] == new_signature[3:])
        entry = put_local_file(index, connection, role=role, root=root, path=new_path,
            info=info, previous=previous, preserve_hash=same_bytes)
        for directory in directories:
            put_directory(index, connection, directory)
    return _public_record(entry)


rename_file_record = move_file_record


def subtree_rows(connection, table: str, role: str, prefix: str) -> list[dict]:
    if table not in ('files', 'directories'):
        raise ValueError('Invalid Storage table.')
    # Binary path bounds use the role/status/path index, including literal % and _.
    return [json.loads(row[0]) for row in connection.execute(
        f"SELECT document FROM {table} WHERE role=? AND status='active' AND (path=? OR (path>=? AND path<?))",
        (role, prefix, prefix + '/', prefix + '0'))]


def remove_file_record(*, data_root: Path, role: str, relative_path: str) -> None:
    index = InventoryIndex(data_root)
    with index.transaction(write=True) as connection:
        previous = index.by_path(connection, role, relative_path)
        if previous:
            index.put_file(connection, _deleted_entry(previous, now=_timestamp()))


def remove_folder_records(*, data_root: Path, role: str, relative_path: str) -> None:
    if not relative_path.strip('/'):
        raise StorageValidationError('Storage roots cannot be removed.')
    index = InventoryIndex(data_root)
    with index.transaction(write=True) as connection:
        for entry in subtree_rows(connection, 'files', role, relative_path):
            index.put_file(connection, _deleted_entry(entry, now=_timestamp()))
        for entry in subtree_rows(connection, 'directories', role, relative_path):
            index.put_directory(connection, _deleted_directory_entry(entry, now=_timestamp()))


def move_folder_records(*, data_root: Path, role: str, root: Path, old_relative_path: str, new_path: Path) -> dict:
    root, new_path, _ = _local_path(root, new_path, directory=True)
    if not old_relative_path.strip('/'):
        raise StorageValidationError('Storage roots cannot be moved.')
    prefix = new_path.relative_to(root).as_posix()
    index = InventoryIndex(data_root)
    with index.transaction() as connection:
        files = subtree_rows(connection, 'files', role, old_relative_path)
        directories = subtree_rows(connection, 'directories', role, old_relative_path)
    # File inspection is outside the SQLite write transaction, under the app mutation fence.
    captured = [(entry, root / (prefix + entry['relative_path'][len(old_relative_path):])) for entry in files]
    captured = [(entry, path, path.stat()) for entry, path in captured]
    folder_entries = [_directory_entry_for_path(role=role, root=root,
        path=root / (prefix + entry['relative_path'][len(old_relative_path):])) for entry in directories]
    parents = capture_directories(role=role, root=root, path=new_path)
    with index.transaction(write=True) as connection:
        for previous, path, info in captured:
            old = index.signature(connection, previous['file_id'])
            new = file_signature(info)
            same_bytes = bool(old and old[:2] == new[:2] and old[3:] == new[3:])
            put_local_file(index, connection, role=role, root=root, path=path, info=info,
                previous=previous, preserve_hash=same_bytes)
        for directory in directories:
            index.put_directory(connection, _deleted_directory_entry(directory, now=_timestamp()))
        for directory in [*folder_entries, *parents]:
            put_directory(index, connection, directory)
    return _public_folder_record(parents[-1])
