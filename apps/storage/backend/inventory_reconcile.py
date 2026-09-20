"""Resumable, bounded discovery and signature validation, outside ordinary reads."""

from __future__ import annotations

import json
from itertools import islice
import os
from pathlib import Path
import stat
import time

from inventory_indexed import file_signature, put_directory, put_local_file
from inventory_records import _deleted_directory_entry, _deleted_entry, _directory_entry_for_path, _timestamp
from inventory_sqlite import InventoryIndex
from storage_mutation_lock import storage_mutation_lock


class _DirectoryScan:
    """Reuse scandir within one bounded pass; persist only its validated offset."""

    def __init__(self):
        self.handle = None
        self.key = None
        self.position = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self.handle is not None:
            self.handle.close()

    def children(self, path: Path, cursor: int, signature: str, *, remaining: int, deadline: float):
        key = (path, signature)
        if self.key != key or self.position != cursor:
            if self.handle is not None:
                self.handle.close()
            self.handle = os.scandir(path)
            self.entries = islice(self.handle, cursor, None)
            self.key, self.position = key, cursor
        captured = []
        while len(captured) < min(256, remaining) and time.monotonic() < deadline:
            entry = next(self.entries, None)
            if entry is None:
                return captured, self.position, True
            self.position += 1
            if not entry.name.startswith('.maverick-storage-write-'):
                captured.append((path / entry.name, entry.stat(follow_symlinks=False)))
        return captured, self.position, False


def _finish_directory(index, connection, *, role: str, parent: str, deadline: float) -> bool:
    # Only a stable completed enumeration establishes absence. Read indexed paths
    # first: unchanged directories must not deserialize every file document.
    for table, put, deleted in (('files', index.put_file, _deleted_entry),
                                ('directories', index.put_directory, _deleted_directory_entry)):
        parent_column = 'actual_parent' if table == 'files' else 'parent'
        rows = connection.execute(f'''SELECT document FROM {table}
            WHERE role=? AND status='active' AND path!='' AND {parent_column}=?
            AND NOT EXISTS(SELECT 1 FROM scan_seen s WHERE s.role=? AND s.parent=?
                AND s.name=substr({table}.path,?)) LIMIT 128''',
            (role, parent, role, parent, len(parent) + (2 if parent else 1))).fetchall()
        for row in rows:
            if time.monotonic() >= deadline:
                return False
            entry = json.loads(row[0])
            if table == 'directories':
                prefix = entry['relative_path']
                for child_table, child_put, child_deleted in (
                    ('files', index.put_file, _deleted_entry),
                    ('directories', index.put_directory, _deleted_directory_entry),
                ):
                    children = connection.execute(f'''SELECT document FROM {child_table}
                        WHERE role=? AND status='active' AND path>=? AND path<? LIMIT 64''',
                        (role, prefix + '/', prefix + '0')).fetchall()
                    for child in children:
                        if time.monotonic() >= deadline:
                            return False
                        child_put(connection, child_deleted(json.loads(child[0]), now=_timestamp()))
                    if children:
                        return False
                connection.execute('DELETE FROM scan_queue WHERE role=? AND (path=? OR (path>=? AND path<?))',
                    (role, prefix, prefix + '/', prefix + '0'))
            put(connection, deleted(entry, now=_timestamp()))
        if len(rows) == 128:
            return False
    connection.execute('DELETE FROM scan_seen WHERE role=? AND parent=?', (role, parent))
    return True


def reconcile_inventory(data_root: Path, *, uploaded_root: Path, generated_root: Path,
                        max_stats: int = 5000, max_seconds: float = .5) -> dict:
    start = time.monotonic()
    # Leave room for committing the last bounded batch and releasing the fence.
    deadline = start + max_seconds * .85
    index = InventoryIndex(data_root)
    roots = {'uploaded': uploaded_root, 'generated': generated_root}
    inspected = 0
    completed = 0
    errors = []
    # The scheduler and explicit sync share one cursor and the app mutation fence.
    with storage_mutation_lock(data_root), index.connect(write=True) as connection, _DirectoryScan() as scan:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            for role in roots:
                connection.execute('INSERT OR IGNORE INTO scan_queue(role,path) VALUES (?,?)', (role, ''))
            if connection.execute('SELECT 1 FROM operations LIMIT 1').fetchone():
                return {'status': 'pending_mutation', 'inspected': 0, 'next_due_in_seconds': 1}
        while inspected + 2 < max_stats and time.monotonic() < deadline:
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
                entries, consumed, done = scan.children(path, cursor, before, remaining=max_stats - inspected - 1, deadline=deadline)
                inspected += len(entries)
                after_info = path.stat()
                after = json.dumps(file_signature(after_info))
                inspected += 1
                if before != after:
                    with connection:
                        connection.execute("BEGIN IMMEDIATE")
                        connection.execute('UPDATE scan_queue SET cursor=0,signature=? WHERE role=? AND path=?', ('', role, parent))
                        connection.execute('DELETE FROM scan_seen WHERE role=? AND parent=?', (role, parent))
                    continue
                directory = _directory_entry_for_path(role=role, root=root, path=path, stat=after_info)
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    if cursor == 0:
                        connection.execute('DELETE FROM scan_seen WHERE role=? AND parent=?', (role, parent))
                    put_directory(index, connection, directory)
                    for entry_path, info in entries:
                        connection.execute('INSERT OR IGNORE INTO scan_seen VALUES (?,?,?)', (role, parent, entry_path.name))
                        if stat.S_ISREG(info.st_mode):
                            relative = entry_path.relative_to(root).as_posix()
                            checked = connection.execute("""SELECT c.signature FROM files f JOIN file_checks c USING(file_id)
                                WHERE f.provider='local' AND f.status='active' AND f.role=? AND f.path=?""",
                                (role, relative)).fetchone()
                            if checked and checked[0] == json.dumps(file_signature(info)):
                                continue
                            previous = index.by_path(connection, role, relative)
                            put_local_file(index, connection, role=role, root=root, path=entry_path, info=info, previous=previous)
                        elif stat.S_ISDIR(info.st_mode):
                            put_directory(index, connection, _directory_entry_for_path(role=role, root=root, path=entry_path, stat=info))
                    if done:
                        done = _finish_directory(index, connection, role=role, parent=parent, deadline=deadline)
                        completed += int(done)
                    connection.execute('''UPDATE scan_queue SET cursor=?,signature=?,last_completed=?,retry_at=0
                        WHERE role=? AND path=?''', (0 if done else consumed, before,
                        time.time() if done else target['last_completed'], role, parent))
            except OSError as error:
                # Missing/inaccessible directories are retried; only their parent scan may tombstone them.
                errors.append({'role': role, 'path': parent, 'error': type(error).__name__})
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute('UPDATE scan_queue SET retry_at=? WHERE role=? AND path=?', (time.time() + 15, role, parent))
        oldest = connection.execute('SELECT MIN(last_completed) FROM scan_queue').fetchone()[0]
        revision = index.revision(connection)
        backlog = connection.execute('SELECT 1 FROM scan_queue WHERE retry_at<=? AND last_completed<? LIMIT 1',
                (time.time(), time.time() - 15)).fetchone() is not None
    return {'status': 'ok' if not errors else 'retrying', 'inspected': inspected,
        'completed_directories': completed, 'duration_ms': (time.monotonic() - start) * 1000,
        'dataset_revision': revision, 'oldest_completed_at': oldest, 'errors': errors,
        'next_due_in_seconds': 1 if backlog else 15}
