"""Database connection and shared persistence helpers for Memory."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from errors import MemoryValidationError
from memory_schema import SCHEMA_STATEMENTS
from models import EDGE_KINDS, NODE_TYPES, SCHEMA_VERSION
from schema_migrations import apply_additive_migrations, source_version_foundation_needs_backfill
from source_chunk_index import source_chunk_fts_needs_rebuild


SQLITE_BUSY_TIMEOUT_MS = 10000
SqliteFileSignature = tuple[int, int, int]
_WAL_CONFIGURED_PATHS: dict[Path, SqliteFileSignature] = {}


def now_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def db_path(data_root: Path) -> Path:
    return data_root / "memory.sqlite"


def artifacts_root(data_root: Path) -> Path:
    return data_root / "artifacts"


def sqlite_file_signature(path: Path) -> SqliteFileSignature | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_dev, stat.st_ino, stat.st_ctime_ns)


def configure_wal_if_needed(connection: sqlite3.Connection, path: Path) -> None:
    resolved_path = path.resolve(strict=False)
    signature = sqlite_file_signature(path)
    if signature is None or _WAL_CONFIGURED_PATHS.get(resolved_path) != signature:
        connection.execute("PRAGMA journal_mode = WAL")
        signature = sqlite_file_signature(path) or signature
    if signature is not None:
        _WAL_CONFIGURED_PATHS[resolved_path] = signature


def open_connection(data_root: Path) -> sqlite3.Connection:
    data_root.mkdir(parents=True, exist_ok=True)
    path = db_path(data_root)
    connection = sqlite3.connect(path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    configure_wal_if_needed(connection, path)
    connection.execute("PRAGMA synchronous = NORMAL")
    signature = sqlite_file_signature(path)
    if signature is not None:
        _WAL_CONFIGURED_PATHS[path.resolve(strict=False)] = signature
    return connection


@contextmanager
def connect(data_root: Path):
    db = open_connection(data_root)
    path = db_path(data_root)
    try:
        yield db
    finally:
        db.close()
        signature = sqlite_file_signature(path)
        if signature is not None:
            _WAL_CONFIGURED_PATHS[path.resolve(strict=False)] = signature


@contextmanager
def transaction(data_root: Path, *, immediate: bool = False):
    with connect(data_root) as db:
        db.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        else:
            db.commit()


def ensure_schema(data_root: Path) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    (artifacts_root(data_root) / "extracted").mkdir(parents=True, exist_ok=True)
    (artifacts_root(data_root) / "previews").mkdir(parents=True, exist_ok=True)
    (data_root / "content").mkdir(parents=True, exist_ok=True)
    if schema_is_current(data_root):
        return
    with transaction(data_root, immediate=True) as db:
        for statement in SCHEMA_STATEMENTS:
            db.execute(statement)
        apply_additive_migrations(db, data_root=data_root)
        db.execute(
            "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )


def schema_is_current(data_root: Path) -> bool:
    if not db_path(data_root).exists():
        return False
    try:
        with connect(data_root) as db:
            row = db.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()
            if row is None or row["value"] != SCHEMA_VERSION:
                return False
            return schema_has_current_shape(db)
    except sqlite3.Error:
        return False


def schema_has_current_shape(db: sqlite3.Connection) -> bool:
    required_tables = {
        "source_documents",
        "source_versions",
        "source_chunks",
        "source_chunk_fts",
        "citations",
        "ingest_jobs",
    }
    existing_tables = {
        row["name"]
        for row in db.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type IN ('table', 'virtual table')
            """
        )
    }
    if not required_tables.issubset(existing_tables):
        return False

    required_columns = {
        "source_documents": {
            "id",
            "source_key",
            "adapter_id",
            "source_kind",
            "owning_app_id",
            "entity_type",
            "entity_id",
            "file_id",
            "workspace_relative_path",
            "uri",
            "title",
            "status",
            "created_at",
            "updated_at",
            "metadata_json",
        },
        "source_versions": {
            "id",
            "source_id",
            "source_document_id",
            "version_hash",
            "extracted_text",
            "extracted_ref",
            "body_path",
            "body_sha256",
            "body_bytes",
            "hash_kind",
            "extraction_status",
            "source_modified_at",
            "content_type",
            "observed_at",
            "created_at",
            "metadata_json",
        },
        "source_chunks": {
            "id",
            "source_version_id",
            "chunk_index",
            "body_path",
            "body_sha256",
            "token_count",
            "char_start",
            "char_end",
            "locator",
            "locator_kind",
            "created_at",
            "metadata_json",
        },
        "citations": {
            "id",
            "claim_id",
            "source_id",
            "source_version_id",
            "source_chunk_id",
            "external_ref_id",
            "locator",
            "locator_kind",
            "char_start",
            "char_end",
            "quote_sha256",
            "quote",
            "created_at",
            "metadata_json",
        },
        "ingest_jobs": {
            "id",
            "job_type",
            "dedupe_key",
            "status",
            "attempt_count",
            "max_attempts",
            "available_at",
            "locked_until",
            "lease_token",
            "last_error",
            "payload_json",
            "node_id",
            "source_document_id",
            "source_version_id",
            "created_at",
            "updated_at",
        },
    }
    for table_name, required in required_columns.items():
        columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table_name})")}
        if not required.issubset(columns):
            return False

    required_indexes = {
        "source_documents": {
            "idx_source_documents_key",
            "idx_source_documents_file",
            "idx_source_documents_app_entity",
        },
        "source_versions": {"idx_source_versions_hash"},
        "source_chunks": {"idx_source_chunks_version_index", "idx_source_chunks_hash"},
        "ingest_jobs": {
            "idx_ingest_jobs_ready_dedupe",
            "idx_ingest_jobs_status_available",
            "idx_ingest_jobs_source_provenance",
        },
    }
    for table_name, required in required_indexes.items():
        indexes = {row["name"] for row in db.execute(f"PRAGMA index_list({table_name})")}
        if not required.issubset(indexes):
            return False
    if source_version_foundation_needs_backfill(db):
        return False
    if source_chunk_fts_needs_rebuild(db):
        return False
    return True

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


def normalize_limit(value: object, *, default: int, minimum: int, maximum: int, field_name: str = "limit") -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise MemoryValidationError(f"{field_name} must be an integer.") from error
    return max(minimum, min(parsed, maximum))


def normalize_float(
    value: object,
    *,
    default: float,
    minimum: float,
    maximum: float,
    field_name: str,
) -> float:
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise MemoryValidationError(f"{field_name} must be a number.") from error
    if not math.isfinite(parsed):
        raise MemoryValidationError(f"{field_name} must be a finite number.")
    if parsed < minimum or parsed > maximum:
        raise MemoryValidationError(f"{field_name} must be between {minimum:g} and {maximum:g}.")
    return parsed


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
