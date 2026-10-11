"""Merge personal mailbox caches and drafts without moving OAuth authority."""

import sqlite3

from database import connect, db_path, ensure_schema

CACHE_TABLES = ("connections", "folders", "labels", "threads", "messages", "attachments",
                "drafts", "sync_state", "entity_links", "audit_log", "gmail_sync_inventory")


def migrate_state(source, root):
    if not db_path(source).exists():
        return
    if db_path(source).is_symlink():
        raise ValueError("Personal mailbox migration source may not be a symlink.")
    ensure_schema(root)
    previous = sqlite3.connect(db_path(source).as_uri() + "?mode=ro", uri=True)
    try:
        with connect(root) as db:
            db.execute("BEGIN IMMEDIATE")
            tables = {row[0] for row in previous.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in CACHE_TABLES:
                if table not in tables:
                    continue
                old_columns = {row[1] for row in previous.execute(f'PRAGMA table_info("{table}")')}
                columns = [row[1] for row in db.execute(f'PRAGMA table_info("{table}")') if row[1] in old_columns]
                names = ",".join('"' + name + '"' for name in columns)
                placeholders = ",".join("?" for _ in columns)
                # Existing shared rows win; retrying a partial import cannot
                # overwrite a later draft edit or a refreshed provider cache.
                db.executemany(f'INSERT OR IGNORE INTO "{table}" ({names}) VALUES ({placeholders})',
                               previous.execute(f'SELECT {names} FROM "{table}"'))
    finally:
        previous.close()
