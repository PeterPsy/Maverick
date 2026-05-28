"""Source and citation persistence for the Memory compiled wiki."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
from typing import Any

from database import json_text, new_id, row_payload
from storage_sources import (
    is_remote_storage_ref,
    ref_metadata,
    remote_storage_snapshot,
    storage_ref_staleness,
    update_remote_ref_metadata,
)


def sync_sources(
    db: sqlite3.Connection,
    *,
    data_root: Path,
    node_id: str,
    refs: list[sqlite3.Row],
    timestamp: str,
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for ref in refs:
        source_id = _source_id_for_ref(db, ref)
        snapshot = source_snapshot(ref, data_root, include_remote_preview=True)
        update_remote_ref_metadata(db, ref, snapshot, timestamp=timestamp)
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
            "content_hash": snapshot["hash"],
            "created_at": timestamp,
            "updated_at": timestamp,
            "metadata_json": source_metadata(ref, snapshot),
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
        version = ensure_source_version(db, source=saved, ref=ref, snapshot=snapshot, timestamp=timestamp)
        ensure_node_source_link(db, node_id=node_id, source_id=saved["id"], external_ref_id=ref["id"], timestamp=timestamp)
        saved["source_version_id"] = version["id"]
        sources.append(saved)
    return sources


def ensure_source_version(
    db: sqlite3.Connection,
    *,
    source: dict[str, Any],
    ref: sqlite3.Row,
    snapshot: dict[str, Any],
    timestamp: str,
) -> dict[str, Any]:
    version_hash = snapshot["hash"]
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
        "extracted_text": snapshot["extracted_text"],
        "extracted_ref": snapshot.get("extracted_ref")
        or source.get("workspace_relative_path")
        or source.get("entity_id")
        or source.get("uri")
        or "",
        "observed_at": timestamp,
        "created_at": timestamp,
        "metadata_json": json_text(
            {
                "deterministic": True,
                "hash_kind": snapshot["hash_kind"],
                "extracted_text_available": bool(snapshot["extracted_text"]),
                "reference_snapshot_hash": reference_snapshot_hash(ref),
                **snapshot.get("metadata", {}),
            }
        ),
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


def source_snapshot(
    ref: sqlite3.Row,
    data_root: Path | None,
    *,
    include_remote_preview: bool = False,
) -> dict[str, Any]:
    metadata = ref_metadata(ref)
    if is_remote_storage_ref(ref, metadata):
        return remote_storage_snapshot(ref, metadata, data_root, include_preview=include_remote_preview)
    file_path = workspace_file_path(data_root, str(ref["workspace_relative_path"] or ""))
    if file_path is not None and file_path.is_file():
        return {
            "hash": file_hash(file_path),
            "hash_kind": "file_bytes",
            "extracted_text": "",
        }
    return {
        "hash": reference_snapshot_hash(ref),
        "hash_kind": "reference_snapshot",
        "extracted_text": "",
    }


def source_metadata(ref: sqlite3.Row, snapshot: dict[str, Any]) -> str:
    metadata = ref_metadata(ref)
    metadata["content_hash_kind"] = snapshot["hash_kind"]
    metadata.update(snapshot.get("metadata", {}))
    staleness = storage_ref_staleness(ref)
    if staleness:
        metadata["storage_staleness"] = staleness
    return json_text(metadata)


def reference_snapshot_hash(ref: sqlite3.Row) -> str:
    return sha256(reference_snapshot_text(ref).encode("utf-8")).hexdigest()


def reference_snapshot_text(ref: sqlite3.Row) -> str:
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


def workspace_file_path(data_root: Path | None, workspace_relative_path: str) -> Path | None:
    if data_root is None or not workspace_relative_path:
        return None
    workspace_root = workspace_root_for_data_root(data_root)
    if workspace_root is None:
        return None
    return workspace_root / workspace_relative_path


def workspace_root_for_data_root(data_root: Path) -> Path | None:
    if data_root.parent.name != "data":
        return None
    return data_root.parent.parent


def file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_id_for_ref(db: sqlite3.Connection, ref: sqlite3.Row) -> str | None:
    row = db.execute("SELECT id FROM sources WHERE external_ref_id = ?", (ref["id"],)).fetchone()
    return row["id"] if row is not None else None
