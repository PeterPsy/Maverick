"""Explicit operational surfaces for Storage lifecycle and bounded metadata reads."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from errors import StorageAuthorizationError, StorageValidationError
from inventory import catalog_inventory_payload, list_inventory_folders, uses_sqlite
from inventory_migration import cutover_inventory, prepare_inventory, rollback_inventory, validate_inventory
from inventory_queries import directory_children, summary_payload
from inventory_records import _public_folder_record
from inventory_sqlite import InventoryIndex
from storage_mutation_lock import storage_mutation_lock


def migration_action(data_root: Path, uploaded_root: Path, generated_root: Path, body: dict) -> dict:
    phase = str(body.get('phase') or 'status')
    if phase == 'status':
        return {'adapter': 'sqlite' if uses_sqlite(data_root) else 'json',
            'sqlite_runtime': sqlite3.sqlite_version, 'wal_runtime_safe': sqlite3.sqlite_version_info >= (3, 51, 3)}
    if body.get('_surface') not in ('cli', 'migrate'):
        raise StorageAuthorizationError('Storage inventory migration requires the administrative CLI.', operation='inventory.migration')
    roots = {'uploaded_root': uploaded_root, 'generated_root': generated_root}
    migration_id = str(body.get('migration_id') or '')
    if phase == 'prepare':
        return prepare_inventory(data_root, **roots)
    if phase == 'validate':
        return validate_inventory(data_root, migration_id)
    if phase == 'cutover':
        return cutover_inventory(data_root, migration_id, **roots)
    if phase == 'rollback':
        return rollback_inventory(data_root)
    if phase == 'recover':
        from inventory_operations import recover_operations
        return recover_operations(data_root, {'uploaded': uploaded_root, 'generated': generated_root})
    raise StorageValidationError('Unknown inventory migration phase.', allowed_values={
        'phase': ['status', 'prepare', 'validate', 'cutover', 'rollback', 'recover']})


def catalog_summary(data_root: Path, uploaded_root: Path, generated_root: Path) -> dict:
    with storage_mutation_lock(data_root, shared=True):
        if uses_sqlite(data_root):
            return summary_payload(InventoryIndex(data_root))
        catalog = catalog_inventory_payload(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root)
        return {'scope': 'local-roots', 'available_kinds': catalog['available_kinds'], 'containers': [
            {'role': role, 'total_files': sum(item['role'] == role for item in catalog['files']),
                'total_bytes': sum(item['size_bytes'] for item in catalog['files'] if item['role'] == role),
                'total_folders': sum(item['role'] == role for item in catalog['folders'])}
            for role in ('uploaded', 'generated')]}


def catalog_directories(data_root: Path, uploaded_root: Path, generated_root: Path, *,
                        role: str, parent: str, offset: int, limit: int, dataset_revision: int | None) -> dict:
    with storage_mutation_lock(data_root, shared=True):
        if uses_sqlite(data_root):
            index = InventoryIndex(data_root)
            with index.transaction() as connection:
                revision = index.revision(connection)
                if dataset_revision is not None and revision != dataset_revision:
                    return {'status': 'catalog_changed', 'dataset_revision': revision}
                total = connection.execute("SELECT COUNT(*) FROM directories WHERE role=? AND parent=? AND status='active' AND path!=''",
                    (role, parent)).fetchone()[0]
                entries = directory_children(connection, role=role, parent=parent, offset=offset, limit=limit)
            entries = [{**_public_folder_record(item), **{key: item[key] for key in ('total_files', 'total_bytes', 'total_folders')}} for item in entries]
        else:
            folders = list_inventory_folders(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root)
            folders = [entry for entry in folders if entry['role'] == role and entry['relative_path'].rpartition('/')[0] == parent]
            total, revision, entries = len(folders), None, folders[offset:offset + limit]
        return {'status': 'ok', 'folders': entries, 'dataset_revision': revision,
            'pagination': {'offset': offset, 'limit': limit, 'total': total, 'has_more': offset + len(entries) < total}}
