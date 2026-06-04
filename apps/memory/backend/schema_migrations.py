"""Additive schema migrations for Memory."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from chunking import chunk_source_body
from content_store import write_body


def apply_additive_migrations(db: sqlite3.Connection, *, data_root: Path) -> None:
    """Bring existing Memory databases up to the current additive schema."""

    add_column_if_missing(db, "source_versions", "source_document_id", "TEXT")
    add_column_if_missing(db, "source_versions", "body_path", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(db, "source_versions", "body_sha256", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(db, "source_versions", "body_bytes", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(db, "source_versions", "hash_kind", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(db, "source_versions", "extraction_status", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(db, "source_versions", "source_modified_at", "TEXT")
    add_column_if_missing(db, "source_versions", "content_type", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(db, "citations", "source_chunk_id", "TEXT")
    add_column_if_missing(db, "citations", "locator_kind", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(db, "citations", "char_start", "INTEGER")
    add_column_if_missing(db, "citations", "char_end", "INTEGER")
    add_column_if_missing(db, "citations", "quote_sha256", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(db, "ingest_jobs", "lease_token", "TEXT NOT NULL DEFAULT ''")
    backfill_source_version_foundation(db, data_root=data_root)


def source_version_foundation_needs_backfill(db: sqlite3.Connection) -> bool:
    missing_document = db.execute(
        """
        SELECT 1
        FROM source_versions
        WHERE COALESCE(NULLIF(source_document_id, ''), '') = ''
        LIMIT 1
        """
    ).fetchone()
    if missing_document is not None:
        return True
    missing_content = db.execute(
        """
        SELECT 1
        FROM source_versions sv
        WHERE COALESCE(NULLIF(sv.extracted_text, ''), '') != ''
          AND (
            COALESCE(NULLIF(sv.body_path, ''), '') = ''
            OR COALESCE(NULLIF(sv.body_sha256, ''), '') = ''
            OR NOT EXISTS (
              SELECT 1 FROM source_chunks sc WHERE sc.source_version_id = sv.id
            )
          )
        LIMIT 1
        """
    ).fetchone()
    return missing_content is not None


def add_column_if_missing(db: sqlite3.Connection, table_name: str, column_name: str, column_definition: str) -> None:
    columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table_name})")}
    if column_name not in columns:
        db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def backfill_source_version_foundation(db: sqlite3.Connection, *, data_root: Path) -> None:
    """Attach legacy source versions to v3 source documents and verified content."""

    timestamp = now_timestamp()
    for row in db.execute("SELECT * FROM source_versions ORDER BY created_at, id"):
        version = row_payload(row) or {}
        source = ensure_migrated_source(db, version=version, timestamp=timestamp)
        document = ensure_migrated_source_document(db, source=source, version=version, timestamp=timestamp)
        if not str(version.get("source_document_id") or "").strip():
            db.execute(
                "UPDATE source_versions SET source_document_id = ? WHERE id = ?",
                (document["id"], version["id"]),
            )
            version["source_document_id"] = document["id"]
        if str(version.get("extracted_text") or "").strip():
            backfill_source_version_content(db, data_root=data_root, version=version, document=document, timestamp=timestamp)


def ensure_migrated_source(db: sqlite3.Connection, *, version: dict[str, Any], timestamp: str) -> dict[str, Any]:
    source_id = str(version.get("source_id") or "").strip()
    row = db.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if row is not None:
        return row_payload(row) or {}
    source = {
        "id": source_id or new_id("src"),
        "source_kind": "legacy_source_version",
        "external_ref_id": None,
        "owning_app_id": "",
        "entity_type": "",
        "entity_id": "",
        "file_id": "",
        "workspace_relative_path": "",
        "uri": "",
        "title": source_id or "Legacy Memory source",
        "content_hash": str(version.get("version_hash") or ""),
        "created_at": str(version.get("created_at") or timestamp),
        "updated_at": timestamp,
        "metadata_json": json_text({"migration": "v3_source_foundation"}),
    }
    db.execute(
        """
        INSERT INTO sources(
          id, source_kind, external_ref_id, owning_app_id, entity_type, entity_id, file_id,
          workspace_relative_path, uri, title, content_hash, created_at, updated_at, metadata_json
        )
        VALUES (
          :id, :source_kind, :external_ref_id, :owning_app_id, :entity_type, :entity_id, :file_id,
          :workspace_relative_path, :uri, :title, :content_hash, :created_at, :updated_at, :metadata_json
        )
        """,
        source,
    )
    return source


def ensure_migrated_source_document(
    db: sqlite3.Connection,
    *,
    source: dict[str, Any],
    version: dict[str, Any],
    timestamp: str,
) -> dict[str, Any]:
    source_key = migrated_source_key(source, version)
    existing = db.execute("SELECT * FROM source_documents WHERE source_key = ?", (source_key,)).fetchone()
    document = {
        "id": existing["id"] if existing is not None else new_id("srcdoc"),
        "source_key": source_key,
        "adapter_id": migrated_adapter_id(source),
        "source_kind": str(source.get("source_kind") or "legacy_source_version"),
        "owning_app_id": str(source.get("owning_app_id") or ""),
        "entity_type": str(source.get("entity_type") or ""),
        "entity_id": str(source.get("entity_id") or ""),
        "file_id": str(source.get("file_id") or ""),
        "workspace_relative_path": str(source.get("workspace_relative_path") or ""),
        "uri": str(source.get("uri") or ""),
        "title": str(source.get("title") or version.get("extracted_ref") or source.get("id") or "Legacy Memory source"),
        "created_at": str(source.get("created_at") or version.get("created_at") or timestamp),
        "updated_at": timestamp,
        "metadata_json": json_text(
            {
                "migration": "v3_source_foundation",
                "legacy_source_id": source.get("id"),
            }
        ),
    }
    db.execute(
        """
        INSERT INTO source_documents(
          id, source_key, adapter_id, source_kind, owning_app_id, entity_type, entity_id, file_id,
          workspace_relative_path, uri, title, created_at, updated_at, metadata_json
        )
        VALUES (
          :id, :source_key, :adapter_id, :source_kind, :owning_app_id, :entity_type, :entity_id, :file_id,
          :workspace_relative_path, :uri, :title, :created_at, :updated_at, :metadata_json
        )
        ON CONFLICT(source_key) DO UPDATE SET
          source_kind = excluded.source_kind,
          owning_app_id = excluded.owning_app_id,
          entity_type = excluded.entity_type,
          entity_id = excluded.entity_id,
          file_id = excluded.file_id,
          workspace_relative_path = excluded.workspace_relative_path,
          uri = excluded.uri,
          title = excluded.title,
          status = 'active',
          updated_at = excluded.updated_at,
          metadata_json = excluded.metadata_json
        """,
        document,
    )
    return row_payload(db.execute("SELECT * FROM source_documents WHERE source_key = ?", (source_key,)).fetchone()) or document


def migrated_adapter_id(source: dict[str, Any]) -> str:
    if str(source.get("workspace_relative_path") or "").strip():
        return "storage_file"
    if str(source.get("owning_app_id") or "").strip() or str(source.get("entity_id") or "").strip():
        return "app_entity"
    return "legacy"


def migrated_source_key(source: dict[str, Any], version: dict[str, Any]) -> str:
    adapter_id = migrated_adapter_id(source)
    stable_id = (
        str(source.get("entity_id") or "").strip()
        or str(source.get("file_id") or "").strip()
        or str(source.get("workspace_relative_path") or "").strip()
        or str(source.get("uri") or "").strip()
        or str(source.get("id") or "").strip()
        or str(version.get("source_id") or "").strip()
    )
    return f"{adapter_id}:{stable_id or version['id']}"


def backfill_source_version_content(
    db: sqlite3.Connection,
    *,
    data_root: Path,
    version: dict[str, Any],
    document: dict[str, Any],
    timestamp: str,
) -> None:
    body = str(version.get("extracted_text") or "")
    needs_body = not str(version.get("body_path") or "").strip() or not str(version.get("body_sha256") or "").strip()
    if needs_body:
        body_record = write_body(
            data_root,
            kind="sources",
            body_markdown=body,
            metadata={
                "source_id": version["source_id"],
                "source_document_id": document["id"],
                "version_hash": version["version_hash"],
                "migration": "v3_source_foundation",
            },
        )
        hash_kind = str(version.get("hash_kind") or "").strip() or "canonical_body"
        extraction_status = str(version.get("extraction_status") or "").strip() or "available"
        db.execute(
            """
            UPDATE source_versions
            SET body_path = ?,
                body_sha256 = ?,
                body_bytes = ?,
                hash_kind = ?,
                extraction_status = ?
            WHERE id = ?
            """,
            (
                body_record.relative_path,
                body_record.body_sha256,
                body_record.body_bytes,
                hash_kind,
                extraction_status,
                version["id"],
            ),
        )
    if not source_chunks_exist(db, str(version["id"])):
        write_migrated_source_chunks(db, data_root=data_root, version=version, body=body, timestamp=timestamp)


def source_chunks_exist(db: sqlite3.Connection, source_version_id: str) -> bool:
    row = db.execute("SELECT 1 FROM source_chunks WHERE source_version_id = ? LIMIT 1", (source_version_id,)).fetchone()
    return row is not None


def write_migrated_source_chunks(
    db: sqlite3.Connection,
    *,
    data_root: Path,
    version: dict[str, Any],
    body: str,
    timestamp: str,
) -> None:
    for draft in chunk_source_body(body):
        chunk_record = write_body(
            data_root,
            kind="chunks",
            body_markdown=draft.body,
            metadata={
                "source_version_id": version["id"],
                "chunk_index": draft.chunk_index,
                "migration": "v3_source_foundation",
            },
        )
        chunk = {
            "id": migrated_source_chunk_id(str(version["id"]), draft.chunk_index, chunk_record.body_sha256),
            "source_version_id": version["id"],
            "chunk_index": draft.chunk_index,
            "body_path": chunk_record.relative_path,
            "body_sha256": chunk_record.body_sha256,
            "token_count": max(1, len(str(draft.body or "").split())),
            "char_start": draft.char_start,
            "char_end": draft.char_end,
            "locator": str(version.get("extracted_ref") or ""),
            "locator_kind": "migration_extracted_text",
            "created_at": timestamp,
            "metadata_json": json_text({"migration": "v3_source_foundation"}),
        }
        db.execute(
            """
            INSERT OR IGNORE INTO source_chunks(
              id, source_version_id, chunk_index, body_path, body_sha256, token_count,
              char_start, char_end, locator, locator_kind, created_at, metadata_json
            )
            VALUES (
              :id, :source_version_id, :chunk_index, :body_path, :body_sha256, :token_count,
              :char_start, :char_end, :locator, :locator_kind, :created_at, :metadata_json
            )
            """,
            chunk,
        )


def migrated_source_chunk_id(source_version_id: str, chunk_index: int, chunk_body_sha256: str) -> str:
    digest = sha256(f"{source_version_id}:{chunk_index}:{chunk_body_sha256}".encode("utf-8")).hexdigest()
    return f"sch_{digest[:16]}"


def now_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


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
