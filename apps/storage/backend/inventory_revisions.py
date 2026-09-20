"""Persisted view revisions share the inventory mutation transaction."""

import json
import sqlite3


def _key(role: str, parent: str | None) -> str:
    return 'view_revision:' + json.dumps([role, parent], ensure_ascii=False, separators=(',', ':'))


def view_revision(connection: sqlite3.Connection, *, role: str, parent: str | None = None) -> int:
    key = 'revision' if role == 'all' else _key(role, parent)
    row = connection.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
    # Existing schema-2 inventories start each previously untracked scope at zero.
    # The first subsequent mutation advances it; ordinary reads never backfill.
    return int(row[0]) if row else 0


def mark_views_changed(connection: sqlite3.Connection, *records: dict | None, directory: bool = False) -> None:
    scopes: set[tuple[str, str | None]] = set()
    for record in records:
        if not record:
            continue
        role = record['role']
        scopes.add((role, None))
        parts = str(record.get('relative_path') or '').strip('/').split('/')
        # Ancestors expose subtree counts, so their folder pages also change.
        for length in range(len(parts) + int(directory)):
            scopes.add((role, '/'.join(parts[:length])))
    revision = view_revision(connection, role='all')
    connection.executemany('''INSERT INTO metadata(key,value) VALUES (?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value''',
        [(_key(role, parent), str(revision)) for role, parent in scopes])
