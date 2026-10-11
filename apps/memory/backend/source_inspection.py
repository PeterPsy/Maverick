"""Paginated source version, chunk and job inspection."""

from pathlib import Path
import sqlite3
from typing import Any

from database import connect, ensure_schema, normalize_limit, row_payload
from errors import MemoryValidationError
from source_retrieval import chunk_freshness, chunk_marked_stale, citations_for_chunk


def inspect_source(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(data_root)
    version_limit = normalize_limit(body.get("version_limit"), default=20, minimum=1, maximum=50, field_name="version_limit")
    version_offset = normalize_limit(body.get("version_offset"), default=0, minimum=0, maximum=1000000, field_name="version_offset")
    chunk_limit = normalize_limit(body.get("chunk_limit"), default=50, minimum=1, maximum=100, field_name="chunk_limit")
    chunk_offset = normalize_limit(body.get("chunk_offset"), default=0, minimum=0, maximum=1000000, field_name="chunk_offset")
    with connect(data_root) as db:
        document = _resolve_source_document(db, body)
        if document is None:
            raise MemoryValidationError("source not found.")
        raw_versions = [
            row_payload(row) or {}
            for row in db.execute(
                """
                SELECT sv.*
                FROM source_versions sv
                WHERE sv.source_document_id = ?
                ORDER BY sv.observed_at DESC, sv.id DESC LIMIT ? OFFSET ?
                """,
                (document["id"], version_limit, version_offset),
            )
        ]
        version_ids = [version["id"] for version in raw_versions]
        current = db.execute("""SELECT s.current_version_id FROM sources s JOIN source_versions sv ON sv.id = s.current_version_id
            WHERE sv.source_document_id = ? ORDER BY s.updated_at DESC LIMIT 1""", (document["id"],)).fetchone()
        latest_version_id = str(current["current_version_id"] or "") if current else ""
        raw_chunks = _chunks_for_versions(db, version_ids, limit=chunk_limit, offset=chunk_offset)
        versions = [_normalized_source_version(version, latest_version_id=latest_version_id) for version in raw_versions]
        chunks = [_normalized_source_chunk(db, chunk) for chunk in raw_chunks]
        linked_nodes = [
            row_payload(row) or {}
            for row in db.execute(
                """
                SELECT DISTINCT n.id, n.title, n.type, n.summary, n.updated_at
                FROM node_source_links nsl
                JOIN sources s ON s.id = nsl.source_id
                JOIN source_versions sv ON sv.source_id = s.id
                JOIN nodes n ON n.id = nsl.node_id
                WHERE sv.source_document_id = ? AND n.status = 'active'
                ORDER BY n.updated_at DESC
                """,
                (document["id"],),
            )
        ]
        jobs = _jobs_for_source_document(db, document_id=str(document["id"]), version_ids=version_ids)
        freshness = _source_freshness_summary(document, versions, chunks, current_version_id=latest_version_id)
        # Freshness describes the whole source even when its current observation
        # is outside the requested history page (for example A -> B -> A).
        current_version = row_payload(db.execute("SELECT * FROM source_versions WHERE id = ?", (latest_version_id,)).fetchone()) or {}
        stale_current_chunks = db.execute("""SELECT count(*) FROM source_chunks WHERE source_version_id = ?
            AND (json_extract(metadata_json, '$.stale') = 1 OR json_extract(metadata_json, '$.staleness.state') = 'stale')""", (latest_version_id,)).fetchone()[0]
        current_stale = _metadata_marks_stale(document) or _metadata_marks_stale(current_version) or stale_current_chunks > 0
        freshness["state"] = "stale" if current_stale else "fresh" if latest_version_id else "unknown"
        freshness["stale_version_count"] = db.execute("""SELECT count(*) FROM source_versions WHERE source_document_id = ?
            AND (id != ? OR json_extract(metadata_json, '$.stale') = 1 OR json_extract(metadata_json, '$.staleness.state') = 'stale')""", (document["id"], latest_version_id)).fetchone()[0]
        freshness["stale_chunk_count"] = db.execute("""SELECT count(*) FROM source_chunks sc JOIN source_versions sv ON sv.id = sc.source_version_id
            WHERE sv.source_document_id = ? AND (sv.id != ? OR json_extract(sv.metadata_json, '$.stale') = 1
            OR json_extract(sv.metadata_json, '$.staleness.state') = 'stale' OR json_extract(sc.metadata_json, '$.stale') = 1
            OR json_extract(sc.metadata_json, '$.staleness.state') = 'stale')""", (document["id"], latest_version_id)).fetchone()[0]
        freshness["reasons"] = sorted(set(freshness["reasons"]) | ({_stale_reason(current_version)} if _stale_reason(current_version) else set()))
        total_versions = db.execute("SELECT count(*) FROM source_versions WHERE source_document_id = ?", (document["id"],)).fetchone()[0]
        total_chunks = db.execute("SELECT count(*) FROM source_chunks sc JOIN source_versions sv ON sv.id = sc.source_version_id WHERE sv.source_document_id = ?", (document["id"],)).fetchone()[0]
        selected_chunks = db.execute("SELECT count(*) FROM source_chunks sc JOIN source_versions sv ON sv.id = sc.source_version_id WHERE sv.source_document_id = ? AND sv.id IN (SELECT id FROM source_versions WHERE source_document_id = ? ORDER BY observed_at DESC, id DESC LIMIT ? OFFSET ?)", (document["id"], document["id"], version_limit, version_offset)).fetchone()[0]
        freshness["version_count"], freshness["chunk_count"] = total_versions, total_chunks
    return {
        "source_document": _normalized_source_document(document, freshness=freshness),
        "freshness": freshness,
        "versions": versions,
        "chunks": chunks,
        "linked_nodes": linked_nodes,
        "ingest_jobs": jobs,
        "pagination": {"version_limit": version_limit, "version_offset": version_offset,
            "next_version_offset": version_offset + version_limit if version_offset + version_limit < total_versions else None,
            "chunk_limit": chunk_limit, "chunk_offset": chunk_offset,
            "next_chunk_offset": chunk_offset + chunk_limit if chunk_offset + chunk_limit < selected_chunks else None,
            "total_versions": total_versions, "total_chunks": total_chunks},
    }


def _resolve_source_document(db: sqlite3.Connection, body: dict[str, Any]) -> dict[str, Any] | None:
    for field in ("source_document_id", "id"):
        value = str(body.get(field) or "").strip()
        if value:
            row = db.execute("SELECT * FROM source_documents WHERE id = ?", (value,)).fetchone()
            if row is not None:
                return row_payload(row)
    source_key = str(body.get("source_key") or "").strip()
    if source_key:
        row = db.execute("SELECT * FROM source_documents WHERE source_key = ?", (source_key,)).fetchone()
        if row is not None:
            return row_payload(row)
    source_id = str(body.get("source_id") or "").strip()
    if source_id:
        row = db.execute(
            """
            SELECT sd.*
            FROM source_documents sd
            JOIN source_versions sv ON sv.source_document_id = sd.id
            WHERE sv.source_id = ?
            ORDER BY sv.observed_at DESC
            LIMIT 1
            """,
            (source_id,),
        ).fetchone()
        if row is not None:
            return row_payload(row)
    for field in ("file_id", "entity_id"):
        value = str(body.get(field) or "").strip()
        if value:
            row = db.execute(f"SELECT * FROM source_documents WHERE {field} = ? ORDER BY updated_at DESC LIMIT 1", (value,)).fetchone()
            if row is not None:
                return row_payload(row)
    return None


def _chunks_for_versions(db: sqlite3.Connection, version_ids: list[str], *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    if not version_ids:
        return []
    placeholders = ",".join("?" for _item in version_ids)
    return [
        row_payload(row) or {}
        for row in db.execute(
            f"""
            SELECT sc.*, sv.source_id, sv.source_document_id
            FROM source_chunks sc
            JOIN source_versions sv ON sv.id = sc.source_version_id
            WHERE source_version_id IN ({placeholders})
            ORDER BY source_version_id, chunk_index LIMIT ? OFFSET ?
            """,
            (*version_ids, limit, offset),
        )
    ]


def _normalized_source_document(document: dict[str, Any], *, freshness: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "source_document",
        "id": document.get("id") or "",
        "source_document_id": document.get("id") or "",
        "source_key": document.get("source_key") or "",
        "adapter_id": document.get("adapter_id") or "",
        "source_kind": document.get("source_kind") or "",
        "owning_app_id": document.get("owning_app_id") or "",
        "entity_type": document.get("entity_type") or "",
        "entity_id": document.get("entity_id") or "",
        "file_id": document.get("file_id") or "",
        "workspace_relative_path": document.get("workspace_relative_path") or "",
        "uri": document.get("uri") or "",
        "title": document.get("title") or document.get("source_key") or "",
        "status": document.get("status") or "active",
        "freshness": freshness,
        "created_at": document.get("created_at") or "",
        "updated_at": document.get("updated_at") or "",
        "metadata": document.get("metadata") if isinstance(document.get("metadata"), dict) else {},
    }


def _normalized_source_version(version: dict[str, Any], *, latest_version_id: str) -> dict[str, Any]:
    freshness = "stale" if chunk_marked_stale(version) else "fresh" if str(version.get("id") or "") == latest_version_id else "stale"
    return {
        "kind": "source_version",
        "id": version.get("id") or "",
        "source_version_id": version.get("id") or "",
        "source_id": version.get("source_id") or "",
        "source_document_id": version.get("source_document_id") or "",
        "version_hash": version.get("version_hash") or "",
        "hash_kind": version.get("hash_kind") or "",
        "extraction_status": version.get("extraction_status") or "",
        "freshness": freshness,
        "is_latest": str(version.get("id") or "") == latest_version_id,
        "body": {
            "path": version.get("body_path") or "",
            "sha256": version.get("body_sha256") or "",
            "bytes": version.get("body_bytes") or 0,
        },
        "extracted_ref": version.get("extracted_ref") or "",
        "content_type": version.get("content_type") or "",
        "source_modified_at": version.get("source_modified_at") or "",
        "observed_at": version.get("observed_at") or "",
        "created_at": version.get("created_at") or "",
        "metadata": version.get("metadata") if isinstance(version.get("metadata"), dict) else {},
    }


def _normalized_source_chunk(db: sqlite3.Connection, chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "source_chunk",
        "id": chunk.get("id") or "",
        "chunk_id": chunk.get("id") or "",
        "source_version_id": chunk.get("source_version_id") or "",
        "chunk_index": chunk.get("chunk_index") or 0,
        "freshness": chunk_freshness(db, chunk),
        "hash": chunk.get("body_sha256") or "",
        "body": {
            "path": chunk.get("body_path") or "",
            "sha256": chunk.get("body_sha256") or "",
        },
        "locator": {
            "kind": chunk.get("locator_kind") or "",
            "value": chunk.get("locator") or "",
            "char_start": chunk.get("char_start"),
            "char_end": chunk.get("char_end"),
        },
        "citations": citations_for_chunk(db, str(chunk.get("id") or "")),
        "created_at": chunk.get("created_at") or "",
        "metadata": chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {},
    }


def _jobs_for_source_document(db: sqlite3.Connection, *, document_id: str, version_ids: list[str]) -> list[dict[str, Any]]:
    where = ["source_document_id = ?"]
    values: list[Any] = [document_id]
    if version_ids:
        placeholders = ",".join("?" for _item in version_ids)
        where.append(f"source_version_id IN ({placeholders})")
        values.extend(version_ids)
    rows = db.execute(
        f"""
        SELECT *
        FROM ingest_jobs
        WHERE {" OR ".join(where)}
        ORDER BY updated_at DESC
        LIMIT 20
        """,
        tuple(values),
    )
    return [_normalized_ingest_job(row_payload(row) or {}) for row in rows]


def _normalized_ingest_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "ingest_job",
        "id": job.get("id") or "",
        "job_id": job.get("id") or "",
        "job_type": job.get("job_type") or "",
        "dedupe_key": job.get("dedupe_key") or "",
        "status": job.get("status") or "",
        "attempt_count": job.get("attempt_count") or 0,
        "max_attempts": job.get("max_attempts") or 0,
        "available_at": job.get("available_at") or "",
        "locked_until": job.get("locked_until") or "",
        "last_error": job.get("last_error") or "",
        "node_id": job.get("node_id") or "",
        "source_document_id": job.get("source_document_id") or "",
        "source_version_id": job.get("source_version_id") or "",
        "payload": job.get("payload") if isinstance(job.get("payload"), dict) else {},
        "created_at": job.get("created_at") or "",
        "updated_at": job.get("updated_at") or "",
    }


def _source_freshness_summary(
    document: dict[str, Any],
    versions: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    current_version_id: str = "",
) -> dict[str, Any]:
    stale_reasons = sorted(
        {
            reason
            for payload in [document, *versions, *chunks]
            for reason in [_stale_reason(payload)]
            if reason
        }
    )
    stale_version_count = sum(1 for version in versions if version.get("freshness") == "stale")
    stale_chunk_count = sum(1 for chunk in chunks if chunk.get("freshness") == "stale")
    latest_source_version_id = current_version_id
    current_version = next((version for version in versions if version["id"] == current_version_id), {})
    current_version_stale = bool(current_version and _metadata_marks_stale(current_version))
    current_chunk_stale = any(
        chunk.get("source_version_id") == latest_source_version_id and chunk.get("freshness") == "stale"
        for chunk in chunks
    )
    state = "stale" if _metadata_marks_stale(document) or current_version_stale or current_chunk_stale else "fresh" if current_version_id else "unknown"
    return {
        "state": state,
        "latest_source_version_id": latest_source_version_id,
        "version_count": len(versions),
        "chunk_count": len(chunks),
        "stale_version_count": stale_version_count,
        "stale_chunk_count": stale_chunk_count,
        "reasons": stale_reasons,
    }


def _metadata_marks_stale(payload: dict[str, Any]) -> bool:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    staleness = metadata.get("staleness") if isinstance(metadata.get("staleness"), dict) else {}
    return bool(metadata.get("stale") or staleness.get("state") == "stale")


def _stale_reason(payload: dict[str, Any]) -> str:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    staleness = metadata.get("staleness") if isinstance(metadata.get("staleness"), dict) else {}
    return str(metadata.get("stale_reason") or staleness.get("reason") or "").strip()
