"""User-owned sharing leases; raw connector secrets never reach agent surfaces."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import time
from uuid import UUID, uuid4

from companion_store import database, encoded, public_connection, public_operation, sweep
from platform_scope import PLATFORMS, platform_url, platform_for_url
from errors import BrowserValidationError

STOP_REASONS = frozenset({
    "user_stopped", "connector_scope_required", "sharing_revoked", "extension_unavailable",
    "companion_unavailable", "platform_route_unavailable", "connection_expired", "connection_revoked",
    "connection_unavailable", "connector_unauthorized", "authentication_failed", "heartbeat_failed", "connection_replaced",
})


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


def revoke(db: sqlite3.Connection, session_id: str, reason: str) -> None:
    db.execute("UPDATE connections SET status='revoked',secret_hash='',stop_reason=? WHERE session_id=? AND status!='revoked'", (reason, session_id))
    db.execute(
        "UPDATE operations SET status='cancelled',result_json=? WHERE session_id=? AND status IN ('queued','running','processing_media')",
        (encoded({"error": "connection_revoked"}), session_id),
    )


def connect(data_root: Path, workspace_id: str, user_id: str, display_name: str, allowed_platforms: object = None, agent_tab_id: object = None) -> dict:
    approved = [] if allowed_platforms is None else allowed_platforms
    if not isinstance(approved, list) or len(approved) > len(PLATFORMS) or any(not isinstance(key, str) or key not in PLATFORMS for key in approved) or len(set(approved)) != len(approved):
        raise BrowserValidationError("Choose supported platforms without duplicates.", field="allowed_platforms")
    if agent_tab_id is not None:
        try:
            valid = bool(approved) and isinstance(agent_tab_id, str) and len(agent_tab_id) == 36 and str(UUID(agent_tab_id)) == agent_tab_id
        except ValueError:
            valid = False
        if not valid:
            raise BrowserValidationError("Choose a valid agent tab identity.", field="agent_tab_id")
    now = time.time()
    secret = secrets.token_urlsafe(32)
    session_id = "chrome-" + str(uuid4())
    with database(data_root) as db:
        sweep(db, now)
        if agent_tab_id:
            previous = db.execute(
                "SELECT session_id FROM connections WHERE workspace_id=? AND user_id=? AND agent_tab_id=? AND status!='revoked'",
                (workspace_id, user_id, agent_tab_id),
            ).fetchall()
            for row in previous:
                revoke(db, row["session_id"], "connection_replaced")
        active = db.execute(
            "SELECT count(*) FROM connections WHERE workspace_id=? AND user_id=? AND status IN ('connecting','connected')",
            (workspace_id, user_id),
        ).fetchone()[0]
        if active >= 4:
            raise CompanionError("connection_limit", "Disconnect an existing Chrome connection first.", 409)
        db.execute(
            "INSERT INTO connections(session_id,workspace_id,user_id,display_name,secret_hash,status,created_at,seen_at,expires_at,allowed_platforms_json,agent_tab_id) "
            "VALUES(?,?,?,?,?,'connecting',?,?,?,?,?)",
            (session_id, workspace_id, user_id, display_name[:100], hashlib.sha256(secret.encode()).hexdigest(), now, now, now + 120, encoded(approved), agent_tab_id or ""),
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


def connection_url(row: sqlite3.Row, url: object, *, allow_empty: bool = False) -> str:
    approved = json.loads(row["allowed_platforms_json"])
    if approved:
        if allow_empty and url == "":
            return ""
        sanitized = platform_url(url)
        if platform_for_url(sanitized) not in approved:
            raise BrowserValidationError("This platform was not approved for the agent tab.", field="url")
        return sanitized
    return platform_url(url, expected_platform=platform_for_url(row["tab_url"]) if row["tab_url"] else None)


def heartbeat(db: sqlite3.Connection, row: sqlite3.Row, *, url: object, title: object) -> None:
    if row["expires_at"] <= time.time():
        raise CompanionError("connection_expired", "Open Browser and share the tab again.", 410)
    sanitized_url = connection_url(row, url, allow_empty=True)
    now = time.time()
    db.execute(
        "UPDATE connections SET status='connected',seen_at=?,expires_at=?,tab_url=?,tab_title=? WHERE session_id=?",
        (now, now + 120, sanitized_url, str(title or "")[:300], row["session_id"]),
    )


def disconnect(data_root: Path, workspace_id: str, user_id: str, session_id: str, reason: object = "user_stopped") -> dict:
    if not isinstance(reason, str) or reason not in STOP_REASONS:
        raise BrowserValidationError("Choose a supported sharing stop reason.", field="reason")
    with database(data_root) as db:
        require_owner(db, session_id, workspace_id, user_id, allow_revoked=True)
        revoke(db, session_id, reason)
    return {"status": "revoked", "session_id": session_id}
