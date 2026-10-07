"""Transactional Chat-owned learning records and settings."""

from contextlib import contextmanager
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

DEFAULTS = {
    "enabled": False, "paused": False, "memory_enabled": True,
    "improvements_enabled": True, "memory_mode": "review", "idle_seconds": 120,
    "model_source": "workspace", "model_id": "", "reasoning_effort": "low",
    "max_context_chars": 30_000, "max_output_tokens": 2048, "timeout_seconds": 120,
    "daily_token_budget": 100_000, "excluded_thread_ids": [], "excluded_project_ids": [],
    "instructions": "", "retention_days": 30,
    "improvement_concurrency": 4,
}


def now():
    return datetime.now(UTC).timestamp()


def new_id(prefix):
    return prefix + "_" + uuid4().hex


@contextmanager
def connection(data_root, *, write=False):
    root = Path(data_root)
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "learning.sqlite", timeout=15)
    db.row_factory = sqlite3.Row
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version > 3:
        db.close()
        raise ValueError("Unsupported learning database schema")
    db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS learning_settings(id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS learning_conversations(
            session_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, busy INTEGER NOT NULL DEFAULT 0,
            last_activity REAL NOT NULL, cursor INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS learning_exchanges(
            seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, turn_id TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL, input_text TEXT NOT NULL, output_text TEXT NOT NULL,
            metrics TEXT NOT NULL, created_at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS learning_exchange_cursor ON learning_exchanges(session_id,seq);
        CREATE TABLE IF NOT EXISTS learning_jobs(
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, status TEXT NOT NULL, upto INTEGER NOT NULL,
            request_id TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
            due REAL NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
            reserved INTEGER NOT NULL DEFAULT 0, usage INTEGER NOT NULL DEFAULT 0,
            input_json TEXT NOT NULL DEFAULT '{}', output_text TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
            reservation_day TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS learning_jobs_status ON learning_jobs(status,due);
        CREATE TABLE IF NOT EXISTS learning_attempts(
            request_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, day TEXT NOT NULL,
            reserved INTEGER NOT NULL, usage INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'running');
        CREATE TABLE IF NOT EXISTS learning_items(
            id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
            title TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL,
            evidence TEXT NOT NULL, details TEXT NOT NULL, occurrences INTEGER NOT NULL DEFAULT 1,
            node_id TEXT NOT NULL DEFAULT '', provider_id TEXT NOT NULL DEFAULT '',
            operation_id TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS learning_audit(
            id INTEGER PRIMARY KEY, action TEXT NOT NULL, target TEXT NOT NULL,
            actor TEXT NOT NULL, created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS learning_implementations(
            item_id TEXT PRIMARY KEY, status TEXT NOT NULL, actor TEXT NOT NULL,
            session_id TEXT NOT NULL DEFAULT '', turn_id TEXT NOT NULL DEFAULT '',
            request_id TEXT NOT NULL DEFAULT '', request_json TEXT NOT NULL DEFAULT '{}',
            attempt INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS learning_implementation_queue ON learning_implementations(status,created_at);
        CREATE INDEX IF NOT EXISTS learning_implementation_session ON learning_implementations(session_id);
        CREATE TABLE IF NOT EXISTS learning_item_sources(
            item_id TEXT NOT NULL, job_id TEXT NOT NULL, session_id TEXT NOT NULL,
            PRIMARY KEY(item_id,job_id));
        CREATE TABLE IF NOT EXISTS learning_implementation_events(
            event_id TEXT PRIMARY KEY, item_id TEXT NOT NULL, created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS learning_runtime_state(id INTEGER PRIMARY KEY CHECK(id=1), ready INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS learning_context(
            session_id TEXT PRIMARY KEY, episode_json TEXT NOT NULL DEFAULT '{}',
            current_input TEXT NOT NULL DEFAULT '', latest_turn_id TEXT NOT NULL DEFAULT '');
    """)
    if version < 3:
        db.execute("BEGIN IMMEDIATE")
        columns = {row[1] for row in db.execute("PRAGMA table_info(learning_jobs)")}
        if "reservation_day" not in columns:
            db.execute("ALTER TABLE learning_jobs ADD COLUMN reservation_day TEXT NOT NULL DEFAULT ''")
        db.execute("PRAGMA user_version=3")
        db.commit()
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


def settings(db):
    row = db.execute("SELECT body FROM learning_settings WHERE id=1").fetchone()
    return {**DEFAULTS, **(json.loads(row[0]) if row else {})}


def audit(db, action, target="", actor="system"):
    db.execute("INSERT INTO learning_audit(action,target,actor,created_at) VALUES(?,?,?,?)",
               (action, target, actor, now()))


def daily_consumption(db, day):
    return db.execute("SELECT COALESCE(SUM(MAX(reserved,usage)),0) FROM learning_attempts WHERE day=? AND status!='busy'", (day,)).fetchone()[0]


def validate_settings(body, current):
    if not isinstance(body, dict):
        raise ValueError("Learning settings must be an object")
    result = dict(current)
    if set(body) - set(DEFAULTS):
        raise ValueError("Unknown learning setting")
    for key, value in body.items():
        if isinstance(DEFAULTS[key], bool):
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be a boolean")
        elif isinstance(DEFAULTS[key], list):
            if not isinstance(value, list) or len(value) > 100 or any(not isinstance(x, str) or len(x) > 128 for x in value):
                raise ValueError(f"{key} must contain at most 100 identifiers")
        elif isinstance(DEFAULTS[key], int):
            ranges = {"idle_seconds": (0, 3600), "max_context_chars": (4000, 60_000),
                      "max_output_tokens": (128, 8192), "timeout_seconds": (10, 300),
                      "daily_token_budget": (1000, 10_000_000), "retention_days": (1, 365)}
            ranges["improvement_concurrency"] = (1, 8)
            low, high = ranges[key]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f"{key} must be between {low} and {high}")
        elif not isinstance(value, str) or len(value) > (4000 if key == "instructions" else 128):
            raise ValueError(f"Invalid {key}")
        result[key] = value
    for key, options in (("model_source", {"workspace", "fast_model"}),
                         ("memory_mode", {"review", "automatic"}),
                         ("reasoning_effort", {"low", "medium", "high"})):
        if result[key] not in options:
            raise ValueError(f"Invalid {key}")
    return result
