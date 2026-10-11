"""Merge personal mailbox caches and drafts without moving OAuth authority."""

import sqlite3

from connections import upsert_credential_metadata
from database import connect, db_path, ensure_schema, now_timestamp

CACHE_TABLES = ("connections", "folders", "labels", "threads", "messages", "attachments",
                "drafts", "sync_state", "entity_links", "audit_log", "gmail_sync_inventory")


def migrate_state(source, root):
    _merge(source, root, {table: "1" for table in CACHE_TABLES})


def migrate_workspace_state(source, root, workspace_id):
    """Retain workspace IMAP mailboxes without importing shared Google data.

    Rebuild only password-grant metadata for the same workspace/resource IDs.
    Credentials, OAuth flows and pending send approvals never cross roots.
    """
    accounts = "SELECT id FROM connections WHERE provider='imap_smtp'"
    threads = f"SELECT id FROM threads WHERE connection_id IN ({accounts})"
    messages = f"SELECT id FROM messages WHERE thread_id IN ({threads})"
    attachments = f"SELECT id FROM attachments WHERE message_id IN ({messages})"
    drafts = f"SELECT id FROM drafts WHERE connection_id IN ({accounts})"
    filters = {"connections": f"id IN ({accounts})"}
    filters.update({table: f"connection_id IN ({accounts})" for table in
                   ("folders", "labels", "threads", "drafts", "sync_state")})
    filters.update(messages=f"thread_id IN ({threads})",
                   attachments=f"message_id IN ({messages})")
    entities = {"mail_connection": accounts, "email_thread": threads, "email_message": messages,
                "mail_attachment": attachments, "mail_draft": drafts}
    filters["entity_links"] = " OR ".join(
        f"(source_entity_type='{kind}' AND source_entity_id IN ({query}))" for kind, query in entities.items())
    filters["audit_log"] = " OR ".join(
        f"(target_type='{kind}' AND target_id IN ({query}))" for kind, query in entities.items())
    _merge(source, root, filters, workspace_id=workspace_id)


def _merge(source, root, filters, *, workspace_id=None):
    if not db_path(source).exists():
        return
    if db_path(source).is_symlink():
        raise ValueError("Personal mailbox migration source may not be a symlink.")
    ensure_schema(root)
    previous = sqlite3.connect(db_path(source).as_uri() + "?mode=ro", uri=True)
    try:
        previous.execute("BEGIN")
        with connect(root) as db:
            db.execute("BEGIN IMMEDIATE")
            tables = {row[0] for row in previous.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table, where in filters.items():
                if table not in tables:
                    continue
                old_columns = {row[1] for row in previous.execute(f'PRAGMA table_info("{table}")')}
                columns = [row[1] for row in db.execute(f'PRAGMA table_info("{table}")') if row[1] in old_columns]
                names = ",".join('"' + name + '"' for name in columns)
                placeholders = ",".join("?" for _ in columns)
                # Existing shared rows win; retrying a partial import cannot
                # overwrite a later draft edit or a refreshed provider cache.
                db.executemany(f'INSERT OR IGNORE INTO "{table}" ({names}) VALUES ({placeholders})',
                               previous.execute(f'SELECT {names} FROM "{table}" WHERE {where}'))
            if workspace_id is not None:
                for row in previous.execute("SELECT id FROM connections WHERE provider='imap_smtp'"):
                    if db.execute("SELECT 1 FROM connections WHERE id=? AND provider='imap_smtp'", (row[0],)).fetchone():
                        upsert_credential_metadata(db, row[0], workspace_id, now_timestamp())
    finally:
        previous.close()
