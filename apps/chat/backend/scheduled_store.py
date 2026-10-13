"""Transactional storage for Chat-owned schedules and dispatch outboxes."""

from contextlib import contextmanager
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


def now():
    return datetime.now(UTC).timestamp()


def new_id():
    return uuid4().hex


def iso(timestamp):
    return datetime.fromtimestamp(timestamp, UTC).isoformat() if timestamp else None


@contextmanager
def connection(data_root, *, write=False):
    root = Path(data_root)
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "scheduled.sqlite", timeout=15)
    db.row_factory = sqlite3.Row
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version > 1:
        db.close()
        raise ValueError("Unsupported scheduled task database schema")
    db.execute("PRAGMA foreign_keys=ON")
    if version == 0:
        initialize(db)
    try:
        if write:
            db.execute("BEGIN IMMEDIATE")
        yield db
        if write:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize(db):
    db.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS scheduled_chats(
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, config TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1, paused INTEGER NOT NULL DEFAULT 0,
            deleted INTEGER NOT NULL DEFAULT 0, next_due REAL,
            chat_session_id TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS scheduled_due ON scheduled_chats(deleted,paused,next_due);
        CREATE TABLE IF NOT EXISTS scheduled_runs(
            id TEXT PRIMARY KEY, chat_id TEXT NOT NULL REFERENCES scheduled_chats(id),
            graph TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL, finished_at REAL);
        CREATE INDEX IF NOT EXISTS scheduled_run_chat ON scheduled_runs(chat_id,created_at);
        CREATE UNIQUE INDEX IF NOT EXISTS scheduled_open_run ON scheduled_runs(chat_id)
            WHERE finished_at IS NULL;
        CREATE TABLE IF NOT EXISTS scheduled_steps(
            run_id TEXT NOT NULL REFERENCES scheduled_runs(id), node_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', request_id TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(run_id,node_id));
        CREATE TABLE IF NOT EXISTS scheduled_requests(
            id TEXT PRIMARY KEY, chat_id TEXT NOT NULL REFERENCES scheduled_chats(id),
            kind TEXT NOT NULL, run_id TEXT NOT NULL DEFAULT '', node_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL, request_json TEXT NOT NULL,
            session_id TEXT NOT NULL DEFAULT '', turn_id TEXT NOT NULL DEFAULT '',
            output TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS scheduled_request_active ON scheduled_requests(status,updated_at);
        CREATE INDEX IF NOT EXISTS scheduled_request_turn ON scheduled_requests(turn_id);
        CREATE TABLE IF NOT EXISTS scheduled_events(id TEXT PRIMARY KEY, created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS scheduled_notifications(
            id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, owner TEXT NOT NULL, title TEXT NOT NULL,
            body TEXT NOT NULL, created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS scheduled_receipts(
            notification_id TEXT NOT NULL, user_id TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0,
            dismissed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(notification_id,user_id));
        PRAGMA user_version=1;
    """)


def owned_chat(db, chat_id, actor):
    row = db.execute("SELECT * FROM scheduled_chats WHERE id=? AND owner=? AND deleted=0", (chat_id, actor)).fetchone()
    if not row:
        raise ValueError("Scheduled task not found")
    return row


def open_run(db, chat_id):
    return db.execute("SELECT * FROM scheduled_runs WHERE chat_id=? AND finished_at IS NULL", (chat_id,)).fetchone()


def project_chat(db, row, *, detail=False):
    config = json.loads(row["config"])
    run = db.execute("SELECT * FROM scheduled_runs WHERE chat_id=? ORDER BY created_at DESC LIMIT 1", (row["id"],)).fetchone()
    completed = config["schedule"]["frequency"] == "once" and row["next_due"] is None and run and run["status"] == "completed"
    public_config = config if detail else {key: value for key, value in config.items() if key != "graph"}
    if not detail:
        public_config["instructions"] = config["instructions"][:500]
        public_config["block_count"] = len(config["graph"]["nodes"])
    result = {"id": row["id"], **public_config, "revision": row["revision"],
              "status": "completed" if completed else "paused" if row["paused"] else "active",
              "next_run_at": iso(row["next_due"]) if not row["paused"] else None,
              "chat_session_id": row["chat_session_id"], "created_at": iso(row["created_at"]),
              "updated_at": iso(row["updated_at"]), "run_status": run["status"] if run else None}
    if detail:
        result["run"] = project_run(db, run) if run else None
        result["history"] = [{"id": item["id"], "status": item["status"], "created_at": iso(item["created_at"]),
                              "finished_at": iso(item["finished_at"])} for item in
                             db.execute("SELECT * FROM scheduled_runs WHERE chat_id=? ORDER BY created_at DESC LIMIT 20", (row["id"],))]
        request = db.execute("SELECT * FROM scheduled_requests WHERE chat_id=? AND kind='message' ORDER BY updated_at DESC LIMIT 1", (row["id"],)).fetchone()
        result["message_status"] = request["status"] if request else None
        result["message_error"] = request["error"] if request else ""
    return result


def project_run(db, run):
    steps = []
    for step in db.execute("SELECT * FROM scheduled_steps WHERE run_id=?", (run["id"],)):
        request = db.execute("SELECT * FROM scheduled_requests WHERE id=?", (step["request_id"],)).fetchone()
        steps.append({"node_id": step["node_id"], "status": step["status"],
                      "session_id": request["session_id"] if request else "",
                      "turn_id": request["turn_id"] if request else "",
                      "output": request["output"] if request else "", "error": request["error"] if request else ""})
    return {"id": run["id"], "status": run["status"], "created_at": iso(run["created_at"]),
            "finished_at": iso(run["finished_at"]), "steps": steps}
