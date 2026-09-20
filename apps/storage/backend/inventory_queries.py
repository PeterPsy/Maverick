"""Bounded indexed Storage reads; no filesystem reconciliation on the read path."""

from __future__ import annotations

import json
import sqlite3
import unicodedata

from inventory_sqlite import InventoryIndex, natural_key
from errors import StorageConflictError

SORT_COLUMNS = {
    'created_at': 'date_sort', 'modified_at': 'modified_sort', 'date': 'date_sort',
    'name': 'name_sort', 'relative_path': 'path', 'size_bytes': 'size_bytes',
    'preview_kind': 'type_sort',
}


def _like(value: str) -> str:
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def catalog_page(index: InventoryIndex, *, query: str = '', role: str = 'all', kind: str = 'all',
                 folder_path: str | None = None, file_ids: list[str] | None = None,
                 workspace_relative_paths: list[str] | None = None,
                 offset: int = 0, limit: int | None = 100, sort_by: str | None = None,
                 sort_direction: str = 'desc', dataset_revision: int | None = None) -> dict:
    where = ["status='active'"]
    values: list = []
    if role != 'all':
        where.append('role=?')
        values.append(role)
    if kind != 'all':
        where.append('kind=?')
        values.append(kind)
    needle = unicodedata.normalize('NFKC', ' '.join(query.split())).casefold()
    if needle:
        where.append("search_text LIKE ? ESCAPE '\\'")
        values.append('%' + _like(needle) + '%')
    elif folder_path is not None and role != 'all':
        where.append('parent=?')
        values.append(folder_path.strip('/'))
    custom: list[str] = []
    custom_order: list[str] = []
    for field, entries in (('file_id', file_ids), ("'storage/' || role || '/' || path", workspace_relative_paths)):
        if entries:
            custom.append(f'{field} IN (SELECT value FROM json_each(?))')
            values.append(json.dumps(entries))
            custom_order.extend(entries)
    if custom:
        where.append('(' + ' OR '.join(custom) + ')')
    clause = ' AND '.join(where)
    order = SORT_COLUMNS.get(sort_by or 'created_at', 'date_sort')
    direction = 'ASC' if sort_direction.lower() == 'asc' else 'DESC'
    order_sql = f'{order} {direction}, name_sort ASC, file_id ASC'
    order_values: list = []
    if custom_order and sort_by is None:
        order_sql = '''COALESCE((SELECT CAST(key AS INTEGER) FROM json_each(?)
            WHERE value=files.file_id OR value='storage/' || files.role || '/' || files.path LIMIT 1), 2147483647), file_id'''
        order_values.append(json.dumps(custom_order))
    page_limit = min(2000, max(1, limit if limit is not None else 100))
    page_offset = max(0, offset)
    with index.transaction() as connection:
        if connection.execute('SELECT 1 FROM operations LIMIT 1').fetchone():
            raise StorageConflictError('Storage is recovering an interrupted mutation.', conflict='inventory_recovery_required')
        revision = index.revision(connection)
        if dataset_revision is not None and revision != dataset_revision:
            return {'status': 'catalog_changed', 'dataset_revision': revision}
        totals = connection.execute(f'SELECT COUNT(*), COALESCE(SUM(size_bytes),0) FROM files WHERE {clause}', values).fetchone()
        files = [json.loads(row[0]) for row in connection.execute(
            f'SELECT document FROM files WHERE {clause} ORDER BY {order_sql} LIMIT ? OFFSET ?',
            [*values, *order_values, page_limit, page_offset])]
        folders = directory_children(connection, role=role, parent=folder_path or '') if role != 'all' and not needle and not custom else []
        summary = root_summary(connection)
        kinds = [row[0] for row in connection.execute("SELECT DISTINCT kind FROM files WHERE status='active' ORDER BY kind")]
        return {'status': 'ok', 'files': files, 'folders': folders, 'dataset_revision': revision,
            'pagination': {'offset': page_offset, 'limit': page_limit, 'total': totals[0],
                'has_more': page_offset + len(files) < totals[0], 'dataset_revision': revision},
            'totals': {'scope': 'filtered', 'total_files': totals[0], 'total_bytes': totals[1]},
            'summary': summary, 'available_kinds': kinds}


def root_summary(connection: sqlite3.Connection) -> dict:
    rows = {row['role']: dict(row) for row in connection.execute("SELECT role,total_files,total_bytes,total_folders FROM folder_totals WHERE path=''")}
    return {'scope': 'local-roots', 'containers': [
        {'role': role, 'total_files': rows.get(role, {}).get('total_files', 0),
            'total_bytes': rows.get(role, {}).get('total_bytes', 0),
            'total_folders': rows.get(role, {}).get('total_folders', 0)}
        for role in ('uploaded', 'generated')
    ]}


def directory_children(connection: sqlite3.Connection, *, role: str, parent: str,
                       offset: int = 0, limit: int = 200) -> list[dict]:
    rows = connection.execute('''SELECT d.document, COALESCE(t.total_files,0), COALESCE(t.total_bytes,0), COALESCE(t.total_folders,0)
        FROM directories d LEFT JOIN folder_totals t ON t.role=d.role AND t.path=d.path
        WHERE d.role=? AND d.status='active' AND d.parent=? AND d.path!=''
        ORDER BY d.name_sort,d.directory_id LIMIT ? OFFSET ?''', (role, parent, limit, offset))
    return [{**json.loads(row[0]), 'total_files': row[1], 'total_bytes': row[2], 'total_folders': row[3], 'count_scope': 'subtree'} for row in rows]


def summary_payload(index: InventoryIndex) -> dict:
    with index.transaction() as connection:
        return {**root_summary(connection), 'dataset_revision': index.revision(connection),
            'available_kinds': [row[0] for row in connection.execute("SELECT DISTINCT kind FROM files WHERE status='active' ORDER BY kind")]}


def reference_records(index: InventoryIndex, *, query: str, folder: bool, limit: int) -> list[dict]:
    table = 'directories' if folder else 'files'
    identity = 'directory_id' if folder else 'file_id'
    needle = unicodedata.normalize('NFKC', query).casefold().strip()
    tokens = needle.replace('/', ' ').replace('_', ' ').replace('.', ' ').replace('-', ' ').split()
    conditions = ["status='active'"]
    values = []
    for token in tokens:
        conditions.append("search_text LIKE ? ESCAPE '\\'")
        values.append('%' + _like(token) + '%')
    order = f'(name_sort=?) DESC, name_sort, {identity}' if needle else ('name_sort,directory_id' if folder else 'date_sort DESC,name_sort,file_id')
    with index.transaction() as connection:
        return [json.loads(row[0]) for row in connection.execute(
            f'SELECT document FROM {table} WHERE {" AND ".join(conditions)} ORDER BY {order} LIMIT ?',
            [*values, *([natural_key(needle)] if needle else []), limit])]
