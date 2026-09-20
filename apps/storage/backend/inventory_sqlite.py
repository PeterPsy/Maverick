"""Storage-owned transactional metadata index. Document bytes remain on disk."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import unicodedata
from typing import Any, Iterator

from core.shared.sqlite_runtime import require_safe_wal_runtime
from inventory_revisions import mark_views_changed

SCHEMA_VERSION = 2
INDEX_FILE = 'inventory.sqlite'

SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
INSERT INTO metadata VALUES ('revision', '0');
CREATE TABLE files (
    file_id TEXT PRIMARY KEY, provider TEXT NOT NULL, connection_id TEXT NOT NULL,
    remote_id TEXT NOT NULL, role TEXT NOT NULL, path TEXT NOT NULL,
    parent TEXT NOT NULL, actual_parent TEXT NOT NULL, status TEXT NOT NULL, kind TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0), date_sort TEXT NOT NULL, modified_sort TEXT NOT NULL,
    name_sort TEXT NOT NULL, type_sort TEXT NOT NULL, search_text TEXT NOT NULL,
    document TEXT NOT NULL
);
CREATE UNIQUE INDEX active_local_path ON files(role, path)
    WHERE provider='local' AND status='active';
CREATE UNIQUE INDEX remote_identity ON files(provider, connection_id, remote_id)
    WHERE provider!='local' AND remote_id!='';
CREATE INDEX file_parent_date ON files(role, status, parent, date_sort DESC, name_sort, file_id);
CREATE INDEX file_parent_name ON files(role, status, parent, name_sort, file_id);
CREATE INDEX file_path ON files(role, status, path);
CREATE INDEX file_actual_parent ON files(role, status, actual_parent);
CREATE INDEX file_parent_size ON files(role, status, parent, size_bytes DESC, name_sort, file_id);
CREATE INDEX file_parent_type ON files(role, status, parent, type_sort, name_sort, file_id);
CREATE INDEX file_kind ON files(status, kind);
CREATE INDEX file_role_date ON files(role, status, date_sort DESC, name_sort, file_id);
CREATE INDEX file_totals ON files(role, status, parent, kind, size_bytes);
CREATE TABLE file_checks (
    file_id TEXT PRIMARY KEY REFERENCES files(file_id), signature TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE directories (
    directory_id TEXT PRIMARY KEY, role TEXT NOT NULL, path TEXT NOT NULL,
    parent TEXT NOT NULL, status TEXT NOT NULL, name_sort TEXT NOT NULL, search_text TEXT NOT NULL,
    document TEXT NOT NULL, UNIQUE(role, path)
);
CREATE INDEX directory_parent ON directories(role, status, parent, name_sort, directory_id);
CREATE INDEX directory_path ON directories(role, status, path);
CREATE TABLE folder_totals (
    role TEXT NOT NULL, path TEXT NOT NULL, total_files INTEGER NOT NULL,
    total_bytes INTEGER NOT NULL, total_folders INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(role, path)
) WITHOUT ROWID;
CREATE TABLE reconciliation (
    key TEXT PRIMARY KEY, document TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE scan_queue (
    role TEXT NOT NULL, path TEXT NOT NULL, cursor INTEGER NOT NULL DEFAULT 0,
    signature TEXT NOT NULL DEFAULT '', last_completed REAL NOT NULL DEFAULT 0,
    retry_at REAL NOT NULL DEFAULT 0, PRIMARY KEY(role,path)
) WITHOUT ROWID;
CREATE TABLE scan_seen (
    role TEXT NOT NULL, parent TEXT NOT NULL, name TEXT NOT NULL,
    PRIMARY KEY(role,parent,name)
) WITHOUT ROWID;
CREATE TABLE operations (
    operation_id TEXT PRIMARY KEY, document TEXT NOT NULL
) WITHOUT ROWID;
"""


def natural_key(value: object) -> str:
    """Locale-independent NFKC/casefold ordering with arbitrary-length integer runs."""
    parts = re.split(r'([0-9]+)', unicodedata.normalize('NFKC', '' if value is None else str(value)).casefold())
    return '\x00'.join(
        f'1{len(part.lstrip("0") or "0"):08d}:{part.lstrip("0") or "0"}' if index % 2 else f'0{part}'
        for index, part in enumerate(parts)
    )


def _date_key(record: dict) -> str:
    for value in (record.get('created_at'), record.get('modified_at')):
        if value:
            try:
                date = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
                return date.replace(tzinfo=UTC).isoformat(timespec='microseconds') if date.tzinfo is None else date.astimezone(UTC).isoformat(timespec='microseconds')
            except ValueError:
                continue
    return ''


def _json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def searchable_text(record: dict) -> str:
    raw = unicodedata.normalize('NFKC', ' '.join(str(record.get(key) or '') for key in
        ('name', 'workspace_relative_path', 'display_path', 'content_type', 'preview_kind', 'file_id', 'path_id'))).casefold()
    return raw + ' ' + re.sub(r'[\s._/\\-]+', ' ', raw)


def _ancestors(path: str) -> Iterator[str]:
    yield ''
    parts = path.split('/')[:-1]
    for end in range(1, len(parts) + 1):
        yield '/'.join(parts[:end])


class InventoryIndex:
    def __init__(self, data_root: Path):
        self.path = data_root.absolute() / INDEX_FILE
        self.last_transaction = {'lock_ms': 0.0, 'transaction_ms': 0.0}

    def initialize(self) -> None:
        """Explicit install/migration only; ordinary reads cannot create a database."""
        require_safe_wal_runtime()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o660)
        os.close(descriptor)
        try:
            with self.connect(check_schema=False, write=True) as connection:
                if connection.execute('PRAGMA journal_mode=WAL').fetchone()[0] != 'wal':
                    raise RuntimeError('Storage requires a local filesystem supporting SQLite WAL.')
                connection.executescript(f'BEGIN IMMEDIATE;\n{SCHEMA}\nPRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;')
        except BaseException:
            self.path.unlink(missing_ok=True)
            raise

    @contextmanager
    def connect(self, *, check_schema: bool = True, write: bool = False) -> Iterator[sqlite3.Connection]:
        require_safe_wal_runtime()
        connection = sqlite3.connect(self.path.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True, timeout=1.0, isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA synchronous=FULL')
            if check_schema and connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
                raise RuntimeError('Unsupported Storage index schema; explicit migration is required.')
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        with self.connect(write=write) as connection:
            start = time.monotonic()
            connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            acquired = time.monotonic()
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                self.last_transaction = {'lock_ms': (acquired - start) * 1000,
                    'transaction_ms': (time.monotonic() - acquired) * 1000}

    @staticmethod
    def revision(connection: sqlite3.Connection) -> int:
        return int(connection.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0])

    @staticmethod
    def changed(connection: sqlite3.Connection) -> None:
        connection.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")

    @staticmethod
    def get(connection: sqlite3.Connection, file_id: str) -> dict | None:
        row = connection.execute('SELECT document FROM files WHERE file_id=?', (file_id,)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def by_path(connection: sqlite3.Connection, role: str, path: str) -> dict | None:
        row = connection.execute("SELECT document FROM files WHERE provider='local' AND status='active' AND role=? AND path=?", (role, path)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def by_remote(connection: sqlite3.Connection, provider: str, connection_id: str, remote_id: str) -> dict | None:
        row = connection.execute('SELECT document FROM files WHERE provider=? AND connection_id=? AND remote_id=?',
            (provider, connection_id, remote_id)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def signature(connection: sqlite3.Connection, file_id: str) -> tuple | None:
        row = connection.execute('SELECT signature FROM file_checks WHERE file_id=?', (file_id,)).fetchone()
        return tuple(json.loads(row[0])) if row else None

    @staticmethod
    def set_signature(connection: sqlite3.Connection, file_id: str, signature: tuple) -> None:
        connection.execute('''INSERT INTO file_checks VALUES (?,?) ON CONFLICT(file_id)
            DO UPDATE SET signature=excluded.signature WHERE signature!=excluded.signature''',
            (file_id, json.dumps(signature)))

    def put_file(self, connection: sqlite3.Connection, record: dict[str, Any]) -> bool:
        if not re.fullmatch(r'file_[0-9a-f]{32}', str(record.get('file_id') or '')):
            raise ValueError('Storage requires a canonical stable file id.')
        previous = self.get(connection, record['file_id'])
        document = _json(record)
        if previous is not None and _json(previous) == document:
            return False
        path = str(record.get('relative_path') or '')
        parent = path.rpartition('/')[0]
        # System upload buckets are transparent in the ordinary Uploaded root.
        if record['role'] == 'uploaded' and re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', parent):
            parent = ''
        values = (record['file_id'], record.get('provider', 'local'), record.get('connection_id', ''),
            record.get('drive_file_id', ''), record['role'], path, parent, path.rpartition('/')[0], record['status'], record['preview_kind'],
            int(record.get('size_bytes') or 0), _date_key(record), _date_key({'modified_at': record.get('modified_at')}),
            natural_key(record['name']), natural_key(record['preview_kind']) + '\x00' + natural_key(record.get('extension', '')),
            searchable_text(record), document)
        connection.execute('''INSERT INTO files VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(file_id) DO UPDATE SET provider=excluded.provider, connection_id=excluded.connection_id,
            remote_id=excluded.remote_id, role=excluded.role, path=excluded.path, parent=excluded.parent, actual_parent=excluded.actual_parent,
            status=excluded.status, kind=excluded.kind, size_bytes=excluded.size_bytes,
            date_sort=excluded.date_sort, modified_sort=excluded.modified_sort, name_sort=excluded.name_sort, type_sort=excluded.type_sort,
            search_text=excluded.search_text, document=excluded.document''', values)
        for entry, direction in ((previous, -1), (record, 1)):
            if entry is None or entry.get('status') != 'active' or entry.get('provider', 'local') != 'local':
                continue
            for parent in _ancestors(entry['relative_path']):
                connection.execute('''INSERT INTO folder_totals(role,path,total_files,total_bytes) VALUES (?, ?, ?, ?)
                    ON CONFLICT(role,path) DO UPDATE SET total_files=total_files+excluded.total_files,
                    total_bytes=total_bytes+excluded.total_bytes''',
                    (entry['role'], parent, direction, direction * int(entry.get('size_bytes') or 0)))
        self.changed(connection)
        mark_views_changed(connection, previous, record)
        return True

    def put_directory(self, connection: sqlite3.Connection, record: dict) -> bool:
        document = _json(record)
        previous = connection.execute('SELECT document FROM directories WHERE directory_id=?', (record['id'],)).fetchone()
        if previous and previous[0] == document:
            return False
        path = record['relative_path']
        connection.execute('''INSERT INTO directories VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(directory_id) DO UPDATE SET role=excluded.role, path=excluded.path,
            parent=excluded.parent, status=excluded.status, name_sort=excluded.name_sort, search_text=excluded.search_text, document=excluded.document''',
            (record['id'], record['role'], path, path.rpartition('/')[0], record['status'], natural_key(record['name']), searchable_text(record), document))
        for entry, direction in ((json.loads(previous[0]) if previous else None, -1), (record, 1)):
            if not entry or entry.get('status') != 'active' or not entry.get('relative_path') or entry.get('provider', 'local') != 'local':
                continue
            for parent in _ancestors(entry['relative_path']):
                connection.execute('''INSERT INTO folder_totals VALUES (?,?,0,0,?) ON CONFLICT(role,path)
                    DO UPDATE SET total_folders=total_folders+excluded.total_folders''', (entry['role'], parent, direction))
        self.changed(connection)
        mark_views_changed(connection, json.loads(previous[0]) if previous else None, record, directory=True)
        if record.get('provider', 'local') == 'local' and record['status'] == 'active':
            connection.execute('INSERT OR IGNORE INTO scan_queue(role,path) VALUES (?,?)', (record['role'], path))
        return True

    def backup(self, destination: Path) -> None:
        """Capture a consistent snapshot including committed WAL pages."""
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o660)
        os.close(descriptor)
        with self.connect() as source:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
            finally:
                target.close()
