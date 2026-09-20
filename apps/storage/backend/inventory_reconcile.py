"""Resumable, bounded discovery and signature validation, outside ordinary reads."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import time

from inventory_indexed import file_signature, put_directory, put_local_file, subtree_rows
from inventory_records import _deleted_directory_entry, _deleted_entry, _directory_entry_for_path, _timestamp
from inventory_sqlite import InventoryIndex
from storage_mutation_lock import storage_mutation_lock


def _children(path: Path, cursor: int, *, remaining: int, deadline: float):
    captured = []
    complete = True
    consumed = cursor
    # Scandir order is resumed only while the directory signature remains unchanged.
    # Skipping names uses no stat calls, including in a flat 100k-file directory.
    with os.scandir(path) as entries:
        for position, entry in enumerate(entries):
            if position < cursor:
                continue
            if len(captured) >= min(256, remaining) or time.monotonic() >= deadline:
                complete = False
                break
            if entry.name.startswith('.maverick-storage-write-'):
                consumed = position + 1
                continue
            info = entry.stat(follow_symlinks=False)
            target = path / entry.name
            captured.append((target, info))
            consumed = position + 1
    return captured, consumed, complete


def _finish_directory(index, connection, *, role: str, parent: str) -> None:
    # Only a completed, stable directory enumeration can establish absence.
    for table, put, deleted in (('files', index.put_file, _deleted_entry),
                                ('directories', index.put_directory, _deleted_directory_entry)):
        parent_column = 'actual_parent' if table == 'files' else 'parent'
        rows = connection.execute(f'''SELECT document FROM {table}
            WHERE role=? AND status='active' AND path!='' AND {parent_column}=?
            AND NOT EXISTS(SELECT 1 FROM scan_seen s WHERE s.role=? AND s.parent=?
                AND s.name=json_extract({table}.document,'$.name'))''', (role, parent, role, parent))
        missing = [json.loads(row[0]) for row in rows]
        for entry in missing:
            put(connection, deleted(entry, now=_timestamp()))
            if table == 'directories':
                prefix = entry['relative_path']
                for child in subtree_rows(connection, 'files', role, prefix):
                    index.put_file(connection, _deleted_entry(child, now=_timestamp()))
                for child in subtree_rows(connection, 'directories', role, prefix):
                    index.put_directory(connection, _deleted_directory_entry(child, now=_timestamp()))
                connection.execute('DELETE FROM scan_queue WHERE role=? AND (path=? OR (path>=? AND path<?))',
                    (role, prefix, prefix + '/', prefix + '0'))
    connection.execute('DELETE FROM scan_seen WHERE role=? AND parent=?', (role, parent))


def reconcile_inventory(data_root: Path, *, uploaded_root: Path, generated_root: Path,
                        max_stats: int = 5000, max_seconds: float = .5) -> dict:
    start = time.monotonic()
    deadline = start + max_seconds
    index = InventoryIndex(data_root)
    roots = {'uploaded': uploaded_root, 'generated': generated_root}
    inspected = 0
    completed = 0
    errors = []
    # The scheduler and explicit sync share one cursor and the app mutation fence.
    with storage_mutation_lock(data_root):
        with index.transaction(write=True) as connection:
            for role in roots:
                connection.execute('INSERT OR IGNORE INTO scan_queue(role,path) VALUES (?,?)', (role, ''))
            if connection.execute('SELECT 1 FROM operations LIMIT 1').fetchone():
                return {'status': 'pending_mutation', 'inspected': 0, 'next_due_in_seconds': 1}
        while inspected + 2 < max_stats and time.monotonic() < deadline:
            with index.transaction() as connection:
                target = connection.execute('''SELECT * FROM scan_queue WHERE retry_at<=? AND last_completed<?
                    ORDER BY (cursor>0) DESC,last_completed,role,path LIMIT 1''', (time.time(), time.time() - 15)).fetchone()
            if target is None:
                break
            role, parent = target['role'], target['path']
            root = roots[role]
            path = root / parent
            try:
                before = json.dumps(file_signature(path.stat()))
                inspected += 1
                cursor = target['cursor'] if before == target['signature'] else 0
                entries, consumed, done = _children(path, cursor, remaining=max_stats - inspected - 1, deadline=deadline)
                inspected += len(entries)
                after_info = path.stat()
                after = json.dumps(file_signature(after_info))
                inspected += 1
                if before != after:
                    with index.transaction(write=True) as connection:
                        connection.execute('UPDATE scan_queue SET cursor=0,signature=? WHERE role=? AND path=?', ('', role, parent))
                        connection.execute('DELETE FROM scan_seen WHERE role=? AND parent=?', (role, parent))
                    continue
                directory = _directory_entry_for_path(role=role, root=root, path=path, stat=after_info)
                with index.transaction(write=True) as connection:
                    if cursor == 0:
                        connection.execute('DELETE FROM scan_seen WHERE role=? AND parent=?', (role, parent))
                    put_directory(index, connection, directory)
                    for entry_path, info in entries:
                        connection.execute('INSERT OR IGNORE INTO scan_seen VALUES (?,?,?)', (role, parent, entry_path.name))
                        if stat.S_ISREG(info.st_mode):
                            previous = index.by_path(connection, role, entry_path.relative_to(root).as_posix())
                            if previous and index.signature(connection, previous['file_id']) == file_signature(info):
                                continue
                            put_local_file(index, connection, role=role, root=root, path=entry_path, info=info, previous=previous)
                        elif stat.S_ISDIR(info.st_mode):
                            put_directory(index, connection, _directory_entry_for_path(role=role, root=root, path=entry_path, stat=info))
                    if done:
                        _finish_directory(index, connection, role=role, parent=parent)
                        completed += 1
                    connection.execute('''UPDATE scan_queue SET cursor=?,signature=?,last_completed=?,retry_at=0
                        WHERE role=? AND path=?''', (0 if done else consumed, before,
                        time.time() if done else target['last_completed'], role, parent))
            except OSError as error:
                # Missing/inaccessible directories are retried; only their parent scan may tombstone them.
                errors.append({'role': role, 'path': parent, 'error': type(error).__name__})
                with index.transaction(write=True) as connection:
                    connection.execute('UPDATE scan_queue SET retry_at=? WHERE role=? AND path=?', (time.time() + 15, role, parent))
        with index.transaction() as connection:
            oldest = connection.execute('SELECT MIN(last_completed) FROM scan_queue').fetchone()[0]
            revision = index.revision(connection)
    return {'status': 'ok' if not errors else 'retrying', 'inspected': inspected,
        'completed_directories': completed, 'duration_ms': (time.monotonic() - start) * 1000,
        'dataset_revision': revision, 'oldest_completed_at': oldest, 'errors': errors, 'next_due_in_seconds': 15}
