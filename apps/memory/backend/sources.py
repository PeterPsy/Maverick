"""Source and citation persistence for the Memory compiled wiki."""

from __future__ import annotations

from hashlib import sha256
import sqlite3
from typing import Any

from database import json_text, new_id, row_payload


def sync_sources(
    db: sqlite3.Connection,
    *,
    node_id: str,
    refs: list[sqlite3.Row],
    timestamp: str,
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for ref in refs:
        source_id = _source_id_for_ref(db, ref)
        source = {
            "id": source_id or new_id("src"),
            "source_kind": ref["ref_kind"],
            "external_ref_id": ref["id"],
            "owning_app_id": ref["owning_app_id"],
            "entity_type": ref["entity_type"],
            "entity_id": ref["entity_id"],
            "file_id": ref["file_id"],
            "workspace_relative_path": ref["workspace_relative_path"],
            "uri": ref["uri"],
            "title": ref["title"],
            "content_hash": source_hash(ref),
            "created_at": timestamp,
            "updated_at": timestamp,
            "metadata_json": ref["metadata_json"],
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
            ON CONFLICT(external_ref_id) DO UPDATE SET
              source_kind = excluded.source_kind,
              owning_app_id = excluded.owning_app_id,
              entity_type = excluded.entity_type,
              entity_id = excluded.entity_id,
              file_id = excluded.file_id,
              workspace_relative_path = excluded.workspace_relative_path,
              uri = excluded.uri,
              title = excluded.title,
              content_hash = excluded.content_hash,
              status = 'active',
              updated_at = excluded.updated_at,
              metadata_json = excluded.metadata_json
            """,
            source,
        )
        saved = row_payload(db.execute("SELECT * FROM sources WHERE external_ref_id = ?", (ref["id"],)).fetchone()) or {}
        version = ensure_source_version(db, source=saved, ref=ref, timestamp=timestamp)
        ensure_node_source_link(db, node_id=node_id, source_id=saved["id"], external_ref_id=ref["id"], timestamp=timestamp)
        saved["source_version_id"] = version["id"]
        sources.append(saved)
    return sources


def ensure_source_version(
    db: sqlite3.Connection,
    *,
    source: dict[str, Any],
    ref: sqlite3.Row,
    timestamp: str,
) -> dict[str, Any]:
    version_hash = source["content_hash"]
    existing = db.execute(
        "SELECT * FROM source_versions WHERE source_id = ? AND version_hash = ?",
        (source["id"], version_hash),
    ).fetchone()
    if existing is not None:
        return row_payload(existing) or {}
    version = {
        "id": new_id("srcv"),
        "source_id": source["id"],
        "version_hash": version_hash,
        "extracted_text": source_text(ref),
        "extracted_ref": source.get("workspace_relative_path") or source.get("entity_id") or source.get("uri") or "",
        "observed_at": timestamp,
        "created_at": timestamp,
        "metadata_json": json_text({"deterministic": True}),
    }
    db.execute(
        """
        INSERT INTO source_versions(id, source_id, version_hash, extracted_text, extracted_ref, observed_at, created_at, metadata_json)
        VALUES (:id, :source_id, :version_hash, :extracted_text, :extracted_ref, :observed_at, :created_at, :metadata_json)
        """,
        version,
    )
    return version


def ensure_node_source_link(
    db: sqlite3.Connection,
    *,
    node_id: str,
    source_id: str,
    external_ref_id: str,
    timestamp: str,
) -> None:
    db.execute(
        """
        INSERT INTO node_source_links(id, node_id, source_id, external_ref_id, relation, created_at, metadata_json)
        VALUES (?, ?, ?, ?, 'evidence', ?, '{}')
        ON CONFLICT(node_id, source_id) DO NOTHING
        """,
        (new_id("nsl"), node_id, source_id, external_ref_id, timestamp),
    )


def insert_citation(db: sqlite3.Connection, *, claim_id: str, source: dict[str, Any], timestamp: str) -> None:
    db.execute(
        """
        INSERT INTO citations(id, claim_id, source_id, source_version_id, external_ref_id, locator, quote, created_at, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}')
        """,
        (
            new_id("cite"),
            claim_id,
            source["id"],
            source.get("source_version_id"),
            source.get("external_ref_id"),
            source.get("workspace_relative_path") or source.get("entity_id") or source.get("file_id") or "",
            source.get("title") or source.get("workspace_relative_path") or source.get("entity_id") or "",
            timestamp,
        ),
    )


def source_hash(ref: sqlite3.Row) -> str:
    return sha256(source_text(ref).encode("utf-8")).hexdigest()


def source_text(ref: sqlite3.Row) -> str:
    return "\n".join(
        str(value or "")
        for value in (
            ref["ref_kind"],
            ref["owning_app_id"],
            ref["entity_type"],
            ref["entity_id"],
            ref["file_id"],
            ref["workspace_relative_path"],
            ref["uri"],
            ref["title"],
            ref["metadata_json"],
        )
    )


def _source_id_for_ref(db: sqlite3.Connection, ref: sqlite3.Row) -> str | None:
    row = db.execute("SELECT id FROM sources WHERE external_ref_id = ?", (ref["id"],)).fetchone()
    return row["id"] if row is not None else None
