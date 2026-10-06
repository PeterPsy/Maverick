"""Finite asynchronous read operations on a user-shared Chrome connection."""

from __future__ import annotations

import json
from pathlib import Path
import time
from uuid import uuid4

from companion_connections import CompanionError, heartbeat, require_connector, require_owner
from companion_store import database, encoded, public_operation, sweep
from companion_validation import command_payload


MAX_RESULT_BYTES = 8 * 1024 * 1024
TERMINAL = frozenset({"completed", "failed", "cancelled", "expired"})


def enqueue(data_root: Path, workspace_id: str, user_id: str, body: dict) -> dict:
    session_id = str(body.get("session_id") or "")
    action = str(body.get("action") or "")
    parameters = command_payload(action, body)
    now = time.time()
    with database(data_root) as db:
        sweep(db, now)
        connection = require_owner(db, session_id, workspace_id, user_id)
        if connection["status"] != "connected" or connection["expires_at"] <= now:
            raise CompanionError("connector_offline", "Keep the Browser connector window open and share an Instagram tab.", 409)
        pending = db.execute(
            "SELECT count(*) FROM operations WHERE session_id=? AND status IN ('queued','running','processing_media')", (session_id,)
        ).fetchone()[0]
        if pending >= 16:
            raise CompanionError("operation_queue_full", "Wait for or cancel pending Chrome operations.", 429)
        operation_id = str(uuid4())
        db.execute(
            "INSERT INTO operations(operation_id,session_id,action,input_json,status,created_at,expires_at) "
            "VALUES(?,?,?,?,'queued',?,?)", (operation_id, session_id, action, encoded(parameters), now, now + 600),
        )
        row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        return public_operation(row)


def poll(data_root: Path, workspace_id: str, user_id: str, body: dict) -> dict:
    now = time.time()
    session_id = str(body.get("session_id") or "")
    with database(data_root) as db:
        sweep(db, now)
        connection = require_connector(db, session_id, workspace_id, user_id, body.get("connector_secret"))
        heartbeat(db, connection, url=body.get("url"), title=body.get("title"))
        if body.get("active_operation_id"):
            # The local worker must finish/abort before it can claim the next command.
            return {"status": "connected", "command": None}
        active = db.execute(
            "SELECT operation_id FROM operations WHERE session_id=? AND status='running' LIMIT 1", (session_id,)
        ).fetchone()
        if active:
            return {"status": "connected", "command": None}
        row = db.execute(
            "SELECT * FROM operations WHERE session_id=? AND status='queued' ORDER BY created_at LIMIT 1", (session_id,)
        ).fetchone()
        if row is None:
            return {"status": "connected", "command": None}
        lease_id = str(uuid4())
        db.execute(
            "UPDATE operations SET status='running',lease_id=?,lease_until=? WHERE operation_id=?",
            (lease_id, now + 60, row["operation_id"]),
        )
        return {"status": "connected", "command": {
            "operation_id": row["operation_id"], "action": row["action"],
            "parameters": json.loads(row["input_json"]), "lease_id": lease_id, "expires_at": row["expires_at"],
        }}


def claimed_operation(db, workspace_id: str, user_id: str, body: dict):
    require_connector(db, str(body.get("session_id") or ""), workspace_id, user_id, body.get("connector_secret"))
    row = db.execute("SELECT * FROM operations WHERE operation_id=?", (str(body.get("operation_id") or ""),)).fetchone()
    if row is None or row["session_id"] != body.get("session_id") or row["lease_id"] != body.get("lease_id"):
        raise CompanionError("operation_lease_invalid", "The operation does not belong to this connector lease.", 403)
    if row["status"] != "running" or row["expires_at"] <= time.time() or row["lease_until"] <= time.time():
        raise CompanionError("operation_not_running", "The operation is already terminal or its lease has expired.", 409)
    return row


def progress(data_root: Path, workspace_id: str, user_id: str, body: dict) -> dict:
    phase = body.get("phase")
    if not isinstance(phase, str) or len(phase) > 120:
        raise CompanionError("invalid_progress", "A bounded progress phase is required.")
    progress_payload = {"phase": phase, "updated_at": time.time()}
    with database(data_root) as db:
        row = claimed_operation(db, workspace_id, user_id, body)
        db.execute(
            "UPDATE operations SET progress_json=?,lease_until=? WHERE operation_id=?",
            (encoded(progress_payload), time.time() + 60, row["operation_id"]),
        )
    return {"status": "running"}


def complete(data_root: Path, workspace_id: str, user_id: str, body: dict, dependencies: dict | None = None) -> dict:
    result = body.get("result")
    if not isinstance(result, dict):
        raise CompanionError("invalid_result", "Chrome must return a structured observation.")
    serialized = encoded(result)
    if len(serialized.encode()) > MAX_RESULT_BYTES:
        raise CompanionError("result_too_large", "The Chrome observation exceeds the bounded result budget.", 413)
    status = "failed" if result.get("error") else "completed"
    with database(data_root) as db:
        row = claimed_operation(db, workspace_id, user_id, body)
        from companion_media import prepare
        requests = prepare(db, row, result, dependencies)
        status = "processing_media" if requests else status
        serialized = encoded(result)
        db.execute(
            "UPDATE operations SET status=?,result_json=?,lease_until=NULL WHERE operation_id=?",
            (status, serialized, row["operation_id"]),
        )
        updated = db.execute("SELECT * FROM operations WHERE operation_id=?", (row["operation_id"],)).fetchone()
        response = public_operation(updated, include_result=False)
        if requests:
            response["dependency_backend_requests"] = requests
        return response


def get(data_root: Path, workspace_id: str, user_id: str, operation_id: str) -> dict:
    with database(data_root) as db:
        sweep(db, time.time())
        row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            raise CompanionError("operation_unavailable", "The Chrome operation is unavailable.", 404)
        require_owner(db, row["session_id"], workspace_id, user_id, allow_revoked=True)
        return public_operation(row)


def cancel(data_root: Path, workspace_id: str, user_id: str, operation_id: str) -> dict:
    with database(data_root) as db:
        row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            raise CompanionError("operation_unavailable", "The Chrome operation is unavailable.", 404)
        require_owner(db, row["session_id"], workspace_id, user_id, allow_revoked=True)
        if row["status"] not in TERMINAL:
            db.execute(
                "UPDATE operations SET status='cancelled',result_json=?,lease_until=NULL WHERE operation_id=?",
                (encoded({"error": "operation_cancelled"}), operation_id),
            )
        updated = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        return public_operation(updated, include_result=False)


def recent(data_root: Path, workspace_id: str, user_id: str) -> list[dict]:
    with database(data_root) as db:
        sweep(db, time.time())
        rows = db.execute(
            "SELECT o.* FROM operations o JOIN connections c ON o.session_id=c.session_id "
            "WHERE c.workspace_id=? AND c.user_id=? ORDER BY o.created_at DESC LIMIT 30", (workspace_id, user_id),
        ).fetchall()
        return [public_operation(row, include_result=False) for row in rows]
