"""Database schema and shared persistence helpers for Memory."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from errors import MemoryValidationError
from models import EDGE_KINDS, NODE_TYPES, SCHEMA_VERSION

def now_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def db_path(data_root: Path) -> Path:
    return data_root / "memory.sqlite"


def artifacts_root(data_root: Path) -> Path:
    return data_root / "artifacts"


def connect(data_root: Path) -> sqlite3.Connection:
    data_root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path(data_root))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def ensure_schema(data_root: Path) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    (artifacts_root(data_root) / "extracted").mkdir(parents=True, exist_ok=True)
    (artifacts_root(data_root) / "previews").mkdir(parents=True, exist_ok=True)
    with connect(data_root) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_metadata (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS nodes (
              id TEXT PRIMARY KEY,
              type TEXT NOT NULL,
              title TEXT NOT NULL,
              summary TEXT NOT NULL DEFAULT '',
              body_text TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'active',
              importance REAL NOT NULL DEFAULT 0.5,
              confidence REAL NOT NULL DEFAULT 1.0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              deleted_at TEXT,
              deleted_by TEXT,
              delete_reason TEXT,
              last_accessed_at TEXT,
              metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS edges (
              id TEXT PRIMARY KEY,
              source_node_id TEXT NOT NULL,
              target_node_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              weight REAL NOT NULL DEFAULT 0.5,
              confidence REAL NOT NULL DEFAULT 1.0,
              reason TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'active',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              deleted_at TEXT,
              metadata_json TEXT NOT NULL DEFAULT '{}',
              FOREIGN KEY(source_node_id) REFERENCES nodes(id),
              FOREIGN KEY(target_node_id) REFERENCES nodes(id)
            );
            CREATE TABLE IF NOT EXISTS external_refs (
              id TEXT PRIMARY KEY,
              node_id TEXT NOT NULL,
              ref_kind TEXT NOT NULL,
              owning_app_id TEXT NOT NULL DEFAULT '',
              entity_type TEXT NOT NULL DEFAULT '',
              entity_id TEXT NOT NULL DEFAULT '',
              file_id TEXT NOT NULL DEFAULT '',
              workspace_relative_path TEXT NOT NULL DEFAULT '',
              uri TEXT NOT NULL DEFAULT '',
              title TEXT NOT NULL DEFAULT '',
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY(node_id) REFERENCES nodes(id)
            );
            CREATE TABLE IF NOT EXISTS chunks (
              id TEXT PRIMARY KEY,
              node_id TEXT NOT NULL,
              external_ref_id TEXT,
              chunk_index INTEGER NOT NULL DEFAULT 0,
              content_text TEXT NOT NULL,
              content_hash TEXT NOT NULL DEFAULT '',
              token_count INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              metadata_json TEXT NOT NULL DEFAULT '{}',
              FOREIGN KEY(node_id) REFERENCES nodes(id),
              FOREIGN KEY(external_ref_id) REFERENCES external_refs(id)
            );
            CREATE TABLE IF NOT EXISTS events (
              id TEXT PRIMARY KEY,
              event_type TEXT NOT NULL,
              actor_type TEXT NOT NULL DEFAULT '',
              actor_id TEXT NOT NULL DEFAULT '',
              node_id TEXT,
              edge_id TEXT,
              external_ref_id TEXT,
              payload_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS retrieval_feedback (
              id TEXT PRIMARY KEY,
              query TEXT NOT NULL,
              node_id TEXT,
              edge_id TEXT,
              feedback_kind TEXT NOT NULL,
              actor_type TEXT NOT NULL DEFAULT '',
              actor_id TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS index_jobs (
              id TEXT PRIMARY KEY,
              job_type TEXT NOT NULL,
              status TEXT NOT NULL,
              target_kind TEXT NOT NULL,
              target_id TEXT NOT NULL,
              attempt_count INTEGER NOT NULL DEFAULT 0,
              last_error TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
              node_id UNINDEXED,
              title,
              summary,
              body_text
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_type_status ON nodes(type, status);
            CREATE INDEX IF NOT EXISTS idx_nodes_updated ON nodes(updated_at);
            CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_node_id, status);
            CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_node_id, status);
            CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind, status);
            CREATE INDEX IF NOT EXISTS idx_external_refs_app_entity ON external_refs(owning_app_id, entity_type, entity_id);
            CREATE INDEX IF NOT EXISTS idx_external_refs_file ON external_refs(file_id, workspace_relative_path);
            """
        )
        db.execute(
            "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )


def health_payload(data_root: Path) -> dict[str, Any]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        schema_version = db.execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone()["value"]
        node_count = db.execute("SELECT COUNT(*) AS count FROM nodes WHERE status = 'active'").fetchone()["count"]
        edge_count = db.execute("SELECT COUNT(*) AS count FROM edges WHERE status = 'active'").fetchone()["count"]
    return {"status": "ok", "schema_version": schema_version, "node_count": node_count, "edge_count": edge_count}


def normalize_node_type(value: str) -> str:
    normalized = str(value or "note").strip()
    if normalized not in NODE_TYPES:
        raise MemoryValidationError(f"Unsupported node type `{normalized}`.")
    return normalized


def normalize_edge_kind(value: str) -> str:
    normalized = str(value or "related_to").strip()
    if normalized not in EDGE_KINDS:
        raise MemoryValidationError(f"Unsupported edge kind `{normalized}`.")
    return normalized


def json_text(value: Any) -> str:
    return json.dumps(value if isinstance(value, dict) else {}, sort_keys=True, ensure_ascii=False)


def row_payload(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    payload = dict(row)
    for key in ("metadata_json", "payload_json"):
        if key in payload:
            try:
                payload[key.removesuffix("_json")] = json.loads(payload.pop(key) or "{}")
            except json.JSONDecodeError:
                payload[key.removesuffix("_json")] = {}
    return payload


def record_event(
    db: sqlite3.Connection,
    *,
    event_type: str,
    actor_type: str = "",
    actor_id: str = "",
    node_id: str | None = None,
    edge_id: str | None = None,
    external_ref_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "id": new_id("evt"),
        "event_type": event_type,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "node_id": node_id,
        "edge_id": edge_id,
        "external_ref_id": external_ref_id,
        "payload_json": json_text(payload),
        "created_at": now_timestamp(),
    }
    db.execute(
        """
        INSERT INTO events(id, event_type, actor_type, actor_id, node_id, edge_id, external_ref_id, payload_json, created_at)
        VALUES (:id, :event_type, :actor_type, :actor_id, :node_id, :edge_id, :external_ref_id, :payload_json, :created_at)
        """,
        event,
    )
    return row_payload(db.execute("SELECT * FROM events WHERE id = ?", (event["id"],)).fetchone()) or {}


def refresh_fts(db: sqlite3.Connection, node_id: str) -> None:
    row = db.execute("SELECT id, title, summary, body_text FROM nodes WHERE id = ?", (node_id,)).fetchone()
    db.execute("DELETE FROM memory_fts WHERE node_id = ?", (node_id,))
    if row is not None:
        db.execute(
            "INSERT INTO memory_fts(node_id, title, summary, body_text) VALUES (?, ?, ?, ?)",
            (row["id"], row["title"], row["summary"], row["body_text"]),
        )
