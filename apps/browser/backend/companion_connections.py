"""User-owned sharing leases; raw connector secrets never reach agent surfaces."""

from __future__ import annotations

import hashlib
from pathlib import Path
import secrets
import sqlite3
import time
from uuid import uuid4

from companion_store import database, encoded, public_connection, public_operation, sweep
from platform_scope import platform_url, platform_for_url


class CompanionError(Exception):
    def __init__(self, code: str, detail: str, status: int = 400):
        super().__init__(detail)
        self.code, self.status = code, status


def require_owner(db: sqlite3.Connection, session_id: str, workspace_id: str, user_id: str, *, allow_revoked: bool = False) -> sqlite3.Row:
    row = db.execute("SELECT * FROM connections WHERE session_id=?", (session_id,)).fetchone()
    if row is None or row["workspace_id"] != workspace_id or row["user_id"] != user_id:
        raise CompanionError("connection_unavailable", "No shared Chrome connection belongs to this actor.", 404)
    if row["status"] == "revoked" and not allow_revoked:
        raise CompanionError("connection_revoked", "Chrome sharing was revoked.", 410)
    return row


def require_connector(db: sqlite3.Connection, session_id: str, workspace_id: str, user_id: str, secret: object) -> sqlite3.Row:
    row = require_owner(db, session_id, workspace_id, user_id)
    digest = hashlib.sha256(secret.encode()).hexdigest() if isinstance(secret, str) and len(secret) <= 256 else ""
    if not secrets.compare_digest(row["secret_hash"], digest):
        raise CompanionError("connector_unauthorized", "The connector lease is invalid.", 403)
    if row["expires_at"] <= time.time():
        raise CompanionError("connection_expired", "Open Browser and share the tab again.", 410)
    return row


def connect(data_root: Path, workspace_id: str, user_id: str, display_name: str) -> dict:
    now = time.time()
    secret = secrets.token_urlsafe(32)
    session_id = "chrome-" + str(uuid4())
    with database(data_root) as db:
        sweep(db, now)
        active = db.execute(
            "SELECT count(*) FROM connections WHERE workspace_id=? AND user_id=? AND status IN ('connecting','connected')",
            (workspace_id, user_id),
        ).fetchone()[0]
        if active >= 4:
            raise CompanionError("connection_limit", "Disconnect an existing Chrome connection first.", 409)
        db.execute(
            "INSERT INTO connections(session_id,workspace_id,user_id,display_name,secret_hash,status,created_at,seen_at,expires_at) "
            "VALUES(?,?,?,?,?,'connecting',?,?,?)",
            (session_id, workspace_id, user_id, display_name[:100], hashlib.sha256(secret.encode()).hexdigest(), now, now, now + 120),
        )
        row = require_owner(db, session_id, workspace_id, user_id)
        return {"connection": public_connection(row), "connector_secret": secret}


def overview(data_root: Path, workspace_id: str, user_id: str) -> dict:
    with database(data_root) as db:
        sweep(db, time.time())
        rows = db.execute(
            "SELECT * FROM connections WHERE workspace_id=? AND user_id=? "
            "ORDER BY CASE WHEN status IN ('connecting','connected') THEN 0 WHEN status='offline' THEN 1 ELSE 2 END,created_at DESC LIMIT 20",
            (workspace_id, user_id),
        ).fetchall()
        # Polling needs only metadata. Never fetch multi-megabyte media results here.
        operations = db.execute(
            "SELECT o.operation_id,o.session_id,o.action,o.status,o.created_at,o.expires_at,o.progress_json "
            "FROM operations o JOIN connections c ON o.session_id=c.session_id "
            "WHERE c.workspace_id=? AND c.user_id=? ORDER BY o.created_at DESC LIMIT 30",
            (workspace_id, user_id),
        ).fetchall()
        pending_count = db.execute(
            "SELECT count(*) FROM operations o JOIN connections c ON o.session_id=c.session_id "
            "WHERE c.workspace_id=? AND c.user_id=? AND o.status IN ('queued','running','processing_media')",
            (workspace_id, user_id),
        ).fetchone()[0]
        return {
            "connections": [public_connection(row) for row in rows],
            "operations": [public_operation(row, include_result=False) for row in operations],
            "workspace_id": workspace_id,
            "pending_count": pending_count,
        }


def heartbeat(db: sqlite3.Connection, row: sqlite3.Row, *, url: object, title: object) -> None:
    if row["expires_at"] <= time.time():
        raise CompanionError("connection_expired", "Open Browser and share the tab again.", 410)
    sanitized_url = platform_url(url, expected_platform=platform_for_url(row["tab_url"]) if row["tab_url"] else None)
    now = time.time()
    db.execute(
        "UPDATE connections SET status='connected',seen_at=?,expires_at=?,tab_url=?,tab_title=? WHERE session_id=?",
        (now, now + 120, sanitized_url, str(title or "")[:300], row["session_id"]),
    )


def disconnect(data_root: Path, workspace_id: str, user_id: str, session_id: str) -> dict:
    with database(data_root) as db:
        require_owner(db, session_id, workspace_id, user_id, allow_revoked=True)
        db.execute("UPDATE connections SET status='revoked',secret_hash='' WHERE session_id=?", (session_id,))
        db.execute(
            "UPDATE operations SET status='cancelled',result_json=? WHERE session_id=? AND status IN ('queued','running','processing_media')",
            (encoded({"error": "connection_revoked"}), session_id),
        )
    return {"status": "revoked", "session_id": session_id}
