"""Workspace-owned connection metadata and user notification receipts."""
from contextlib import contextmanager
from pathlib import Path
import json
import hashlib
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
 session_id TEXT NOT NULL, created_at TEXT NOT NULL, dismissed INTEGER NOT NULL DEFAULT 0
);
"""

@contextmanager
def database(data_root: str):
    root = Path(data_root)
    if not root.is_absolute():
        raise ValueError("A trusted absolute app data root is required.")
    root.mkdir(parents=True, exist_ok=True)
    target = root / "app.sqlite"
    if target.is_symlink():
        raise ValueError("Database symlinks are not permitted.")
    db = sqlite3.connect(target, timeout=10)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    target.chmod(0o600)
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()

def configuration(data_root: str) -> dict:
    with database(data_root) as db:
        row = db.execute("SELECT value FROM settings WHERE key='connection'").fetchone()
        return json.loads(row[0]) if row else {"url": "http://127.0.0.1:2785", "configured": False}

def save_configuration(data_root: str, value: dict):
    with database(data_root) as db:
        db.execute("INSERT INTO settings VALUES ('connection',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(value),))

def notify(data_root: str, user_id: str, identifier: str, title: str, body: str, session_id: str):
    identifier = hashlib.sha256(json.dumps([user_id, identifier]).encode()).hexdigest()
    with database(data_root) as db:
        db.execute("INSERT OR IGNORE INTO notifications(id,user_id,title,body,session_id,created_at) VALUES (?,?,?,?,?,?)",
                   (identifier, user_id, title, body[:300], session_id, datetime.now(timezone.utc).isoformat()))
        db.execute("DELETE FROM notifications WHERE id IN (SELECT id FROM notifications ORDER BY created_at DESC LIMIT -1 OFFSET 1000)")

def notifications(data_root: str, user_id: str, offset: int, limit: int) -> dict:
    with database(data_root) as db:
        rows = db.execute("SELECT * FROM notifications WHERE user_id=? AND dismissed=0 ORDER BY created_at DESC LIMIT ? OFFSET ?", (user_id, limit, offset)).fetchall()
        total = db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND dismissed=0", (user_id,)).fetchone()[0]
    return {"notifications": [{"id": r["id"], "title": r["title"], "body": r["body"], "created_at": r["created_at"],
            "open_params": {"session_id": r["session_id"]}} for r in rows], "total": total, "has_more": offset + limit < total}

def dismiss(data_root: str, user_id: str, identifier: str):
    with database(data_root) as db:
        db.execute("UPDATE notifications SET dismissed=1 WHERE id=? AND user_id=?", (identifier, user_id))
