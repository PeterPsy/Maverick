"""Source and citation persistence for the Memory compiled wiki."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
from typing import Any

from chunking import chunk_source_body
from content_store import canonical_body, write_body
from database import json_text, new_id, row_payload
from source_chunk_index import delete_source_chunk_fts_for_version, upsert_source_chunk_fts
from storage_sources import (
    INGEST_PREVIEW_METADATA_KEYS,
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
        if source_id:
            db.execute(
                """
                UPDATE sources
                SET source_kind = :source_kind,
                    owning_app_id = :owning_app_id,
                    entity_type = :entity_type,
                    entity_id = :entity_id,
                    file_id = :file_id,
                    workspace_relative_path = :workspace_relative_path,
                    uri = :uri,
                    title = :title,
                    content_hash = :content_hash,
                    status = 'active',
                    updated_at = :updated_at,
                    metadata_json = :metadata_json
                WHERE id = :id
                """,
                source,
            )
        else:
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
        saved = row_payload(db.execute("SELECT * FROM sources WHERE external_ref_id = ?", (ref["id"],)).fetchone()) or {}
        version = ensure_source_version(db, data_root=data_root, source=saved, ref=ref, snapshot=snapshot, timestamp=timestamp)
        ensure_node_source_link(db, node_id=node_id, source_id=saved["id"], external_ref_id=ref["id"], timestamp=timestamp)
        saved["source_version_id"] = version["id"]
        sources.append(saved)
    return sources


def ensure_source_version(
    db: sqlite3.Connection,
    *,
    data_root: Path,
    source: dict[str, Any],
    ref: sqlite3.Row,
    snapshot: dict[str, Any],
    timestamp: str,
) -> dict[str, Any]:
    version_hash = snapshot["hash"]
    source_document = ensure_source_document(db, source=source, ref=ref, timestamp=timestamp)
    existing = db.execute(
        "SELECT * FROM source_versions WHERE source_id = ? AND version_hash = ?",
        (source["id"], version_hash),
    ).fetchone()
    if existing is not None:
        ensure_source_chunks(db, data_root=data_root, version=row_payload(existing) or {}, snapshot=snapshot, timestamp=timestamp)
        return row_payload(existing) or {}
    snapshot_metadata = snapshot.get("metadata", {})
    preview_truncated = bool(snapshot_metadata.get("preview_truncated"))
    extraction_status = "truncated" if preview_truncated else "available" if snapshot["extracted_text"] else "unavailable"
    body = str(snapshot["extracted_text"] or "")
    body_record = None
    if body:
        body_record = write_body(
            data_root,
            kind="sources",
            body_markdown=body,
            metadata={
                "source_id": source["id"],
                "source_document_id": source_document["id"],
                "version_hash": version_hash,
                "hash_kind": snapshot["hash_kind"],
            },
        )
    version = {
        "id": new_id("srcv"),
        "source_id": source["id"],
        "source_document_id": source_document["id"],
        "version_hash": version_hash,
        "extracted_text": snapshot["extracted_text"],
        "extracted_ref": snapshot.get("extracted_ref")
        or source.get("workspace_relative_path")
        or source.get("entity_id")
        or source.get("uri")
        or "",
        "body_path": body_record.relative_path if body_record is not None else "",
        "body_sha256": body_record.body_sha256 if body_record is not None else "",
        "body_bytes": body_record.body_bytes if body_record is not None else 0,
        "hash_kind": snapshot["hash_kind"],
        "extraction_status": extraction_status,
        "source_modified_at": str(snapshot_metadata.get("source_modified_at") or snapshot_metadata.get("modified_at") or ""),
        "content_type": str(snapshot_metadata.get("content_type") or ""),
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
        INSERT INTO source_versions(
          id, source_id, source_document_id, version_hash, extracted_text, extracted_ref,
          body_path, body_sha256, body_bytes, hash_kind, extraction_status, source_modified_at,
          content_type, observed_at, created_at, metadata_json
        )
        VALUES (
          :id, :source_id, :source_document_id, :version_hash, :extracted_text, :extracted_ref,
          :body_path, :body_sha256, :body_bytes, :hash_kind, :extraction_status, :source_modified_at,
          :content_type, :observed_at, :created_at, :metadata_json
        )
        """,
        version,
    )
    ensure_source_chunks(db, data_root=data_root, version=version, snapshot=snapshot, timestamp=timestamp)
    return version


def ensure_source_document(
    db: sqlite3.Connection,
    *,
    source: dict[str, Any],
    ref: sqlite3.Row,
    timestamp: str,
) -> dict[str, Any]:
    source_key = source_document_key(source, ref)
    existing = db.execute("SELECT * FROM source_documents WHERE source_key = ?", (source_key,)).fetchone()
    document = {
        "id": existing["id"] if existing is not None else new_id("srcdoc"),
        "source_key": source_key,
        "adapter_id": source_adapter_id(source, ref),
        "source_kind": source.get("source_kind") or ref["ref_kind"],
        "owning_app_id": source.get("owning_app_id") or ref["owning_app_id"],
        "entity_type": source.get("entity_type") or ref["entity_type"],
        "entity_id": source.get("entity_id") or ref["entity_id"],
        "file_id": source.get("file_id") or ref["file_id"],
        "workspace_relative_path": source.get("workspace_relative_path") or ref["workspace_relative_path"],
        "uri": source.get("uri") or ref["uri"],
        "title": source.get("title") or ref["title"],
        "created_at": existing["created_at"] if existing is not None else timestamp,
        "updated_at": timestamp,
        "metadata_json": json_text({"external_ref_id": ref["id"]}),
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


def ensure_source_chunks(
    db: sqlite3.Connection,
    *,
    data_root: Path,
    version: dict[str, Any],
    snapshot: dict[str, Any],
    timestamp: str,
) -> list[dict[str, Any]]:
    body = str(snapshot.get("extracted_text") or version.get("extracted_text") or "")
    if not body:
        return []
    normalized_body = canonical_body(body)
    return replace_source_chunks(
        db,
        data_root=data_root,
        version=version,
        body=normalized_body,
        base_locator=str(snapshot.get("extracted_ref") or version.get("extracted_ref") or ""),
        locator_kind="preview_text",
        hash_kind=str(snapshot.get("hash_kind") or version.get("hash_kind") or ""),
        timestamp=timestamp,
    )


def replace_source_chunks(
    db: sqlite3.Connection,
    *,
    data_root: Path,
    version: dict[str, Any],
    body: str,
    base_locator: str,
    locator_kind: str,
    hash_kind: str,
    timestamp: str,
) -> list[dict[str, Any]]:
    existing_citation = db.execute(
        """
        SELECT c.id
        FROM citations c
        JOIN source_chunks sc ON sc.id = c.source_chunk_id
        WHERE sc.source_version_id = ?
        LIMIT 1
        """,
        (version["id"],),
    ).fetchone()
    if existing_citation is not None:
        return [
            row_payload(row) or {}
            for row in db.execute(
                "SELECT * FROM source_chunks WHERE source_version_id = ? ORDER BY chunk_index",
                (version["id"],),
            )
        ]

    delete_source_chunk_fts_for_version(db, str(version["id"]))
    db.execute("DELETE FROM source_chunks WHERE source_version_id = ?", (version["id"],))
    chunks: list[dict[str, Any]] = []
    for draft in chunk_source_body(body):
        chunk_record = write_body(
            data_root,
            kind="chunks",
            body_markdown=draft.body,
            metadata={"source_version_id": version["id"], "chunk_index": draft.chunk_index},
        )
        chunk = {
            "id": source_chunk_id(version["id"], draft.chunk_index, chunk_record.body_sha256),
            "source_version_id": version["id"],
            "chunk_index": draft.chunk_index,
            "body_path": chunk_record.relative_path,
            "body_sha256": chunk_record.body_sha256,
            "token_count": approximate_token_count(draft.body),
            "char_start": draft.char_start,
            "char_end": draft.char_end,
            "locator": base_locator,
            "locator_kind": locator_kind,
            "created_at": timestamp,
            "metadata_json": json_text({"hash_kind": hash_kind}),
        }
        db.execute(
            """
            INSERT INTO source_chunks(
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
        upsert_source_chunk_fts(db, chunk_id=chunk["id"], body_text=draft.body)
        chunks.append(row_payload(db.execute("SELECT * FROM source_chunks WHERE id = ?", (chunk["id"],)).fetchone()) or chunk)
    return chunks


def source_document_key(source: dict[str, Any], ref: sqlite3.Row) -> str:
    adapter_id = source_adapter_id(source, ref)
    stable_id = (
        source.get("entity_id")
        or source.get("file_id")
        or source.get("workspace_relative_path")
        or source.get("uri")
        or ref["id"]
    )
    return f"{adapter_id}:{stable_id}"


def source_adapter_id(source: dict[str, Any], ref: sqlite3.Row) -> str:
    if is_remote_storage_ref(ref):
        return "remote_storage_file"
    if source.get("workspace_relative_path") or ref["workspace_relative_path"]:
        return "storage_file"
    if source.get("owning_app_id") or ref["owning_app_id"]:
        return "app_entity"
    return str(source.get("source_kind") or ref["ref_kind"] or "reference")


def source_chunk_id(source_version_id: str, chunk_index: int, chunk_body_sha256: str) -> str:
    digest = sha256(f"{source_version_id}:{chunk_index}:{chunk_body_sha256}".encode("utf-8")).hexdigest()
    return f"sch_{digest[:16]}"


def approximate_token_count(body: str) -> int:
    return max(1, len(str(body or "").split()))


def ensure_node_source_link(
    db: sqlite3.Connection,
    *,
    node_id: str,
    source_id: str,
    external_ref_id: str | None,
    timestamp: str,
) -> None:
    db.execute(
        """
        INSERT INTO node_source_links(id, node_id, source_id, external_ref_id, relation, created_at, metadata_json)
        VALUES (?, ?, ?, ?, 'evidence', ?, '{}')
        ON CONFLICT(node_id, source_id) DO NOTHING
        """,
        (new_id("nsl"), node_id, source_id, external_ref_id or None, timestamp),
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
    for key in INGEST_PREVIEW_METADATA_KEYS:
        metadata.pop(key, None)
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
