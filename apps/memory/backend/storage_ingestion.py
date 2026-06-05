"""Storage-source ingestion operations for Memory."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import sqlite3
from typing import Any

from database import (
    ensure_schema,
    json_text,
    new_id,
    normalize_float,
    normalize_node_type,
    now_timestamp,
    record_event,
    refresh_fts,
    row_payload,
    transaction,
)
from errors import MemoryValidationError
from ingest_jobs import enqueue_job_in_db
from lint import mark_wiki_stale
from nodes import get_node_with_details, inspect_node
from references import validate_storage_ref
from sources import sync_sources
from storage_sources import (
    INGEST_PREVIEW_TEXT_KEY,
    INGEST_PREVIEW_TRUNCATED_KEY,
    MAX_REMOTE_PREVIEW_CHARS,
    REMOTE_STORAGE_PROVIDERS,
    preview_remote_storage_source,
)
from wiki import compile_node


FORBIDDEN_REMOTE_METADATA_KEYS = {
    "access_token",
    "accesstoken",
    "refresh_token",
    "refreshtoken",
    "id_token",
    "idtoken",
    "client_secret",
    "clientsecret",
    "oauth_code",
    "oauthcode",
    "authorization_code",
    "authorizationcode",
    "credential",
    "credentials",
    "token_response",
    "tokenresponse",
    "app_secrets",
    "appsecrets",
}


def ingest_storage_source(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    """Create or update a Memory node/reference from a Storage memory_source."""

    ensure_schema(data_root)
    request = normalized_ingest_request(body)
    if INGEST_PREVIEW_TEXT_KEY not in request["metadata"]:
        attach_preview_from_storage(data_root, request)
    require_source_version(request)
    with transaction(data_root, immediate=True) as db:
        target_node_id, node_created = ensure_target_node(db, request)
        existing_ref = find_existing_storage_ref_for_node(db, request["storage_file_id"], target_node_id)
        old_node_id = str(existing_ref["node_id"] or "") if existing_ref is not None else ""
        old_source_version = source_version_for_ref(existing_ref)
        external_ref, ref_created = upsert_storage_ref(
            db,
            request=request,
            node_id=target_node_id,
            existing_ref=existing_ref,
        )
        timestamp = now_timestamp()
        ref_row = db.execute("SELECT * FROM external_refs WHERE id = ?", (external_ref["id"],)).fetchone()
        ingested_sources = (
            sync_sources(db, data_root=data_root, node_id=target_node_id, refs=[ref_row], timestamp=timestamp)
            if ref_row is not None
            else []
        )
        mark_wiki_stale(db, target_node_id, timestamp=timestamp, reason="storage_source_ingested", data_root=data_root)
        if old_node_id and old_node_id != target_node_id:
            mark_wiki_stale(db, old_node_id, timestamp=timestamp, reason="storage_source_moved", data_root=data_root)
        record_event(
            db,
            event_type="storage_source_ingested",
            node_id=target_node_id,
            external_ref_id=external_ref["id"],
            payload={
                "storage_file_id": request["storage_file_id"],
                "source_version": request["metadata"].get("source_version", ""),
                "node_created": node_created,
                "external_ref_created": ref_created,
                "compile_after_ingest": request["compile_after_ingest"],
            },
        )
        new_source_version = str(request["metadata"].get("source_version") or "").strip()
        source_version_changed = bool(new_source_version and old_source_version != new_source_version)
        work_changed = ref_created or node_created or source_version_changed or (old_node_id and old_node_id != target_node_id)
        if not request["compile_after_ingest"] and work_changed:
            source_provenance = first_source_provenance(ingested_sources)
            enqueue_job_in_db(
                db,
                job_type="compile_node",
                dedupe_key=f"compile:{target_node_id}",
                payload={
                    "node_id": target_node_id,
                    "source_document_id": source_provenance["source_document_id"],
                    "source_version_id": source_provenance["source_version_id"],
                    "reason": "storage_source_ingested",
                },
            )
        node = get_node_with_details(db, target_node_id, data_root=data_root)

    compiled = None
    if request["compile_after_ingest"]:
        compiled = compile_node(data_root, {"node_id": target_node_id})
        node = inspect_node(data_root, target_node_id)

    return {
        "status": "ingested" if ref_created or node_created else "updated",
        "node": node,
        "external_ref": external_ref,
        "sources": ingested_sources,
        "storage_identity": {
            "owning_app_id": "storage",
            "entity_type": "file",
            "entity_id": request["storage_file_id"],
        },
        "node_created": node_created,
        "external_ref_created": ref_created,
        "compile_after_ingest": request["compile_after_ingest"],
        "compiled": compiled,
    }


def source_version_for_ref(ref: sqlite3.Row | None) -> str:
    if ref is None:
        return ""
    payload = row_payload(ref) or {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return str(metadata.get("source_version") or "").strip()


def first_source_provenance(ingested_sources: list[dict[str, Any]]) -> dict[str, str]:
    for source in ingested_sources:
        source_document_id = str(source.get("source_document_id") or "").strip()
        source_version_id = str(source.get("source_version_id") or "").strip()
        if source_document_id or source_version_id:
            return {"source_document_id": source_document_id, "source_version_id": source_version_id}
    return {"source_document_id": "", "source_version_id": ""}


def normalized_ingest_request(body: dict[str, Any]) -> dict[str, Any]:
    source = body.get("memory_source")
    if not isinstance(source, dict):
        raise MemoryValidationError("memory_source is required.")
    source_kind = str(source.get("source_kind") or source.get("ref_kind") or "").strip()
    if source_kind != "remote_storage_file":
        raise MemoryValidationError("ingest_storage_source requires memory_source.source_kind=remote_storage_file.")
    metadata = dict(source.get("metadata") if isinstance(source.get("metadata"), dict) else {})
    reject_secret_metadata(metadata)
    provider = str(source.get("provider") or metadata.get("provider") or "").strip()
    if provider not in REMOTE_STORAGE_PROVIDERS:
        raise MemoryValidationError("remote_storage_file requires a supported remote provider.")
    storage_file_id = str(source.get("entity_id") or source.get("file_id") or "").strip()
    source_version = str(body.get("source_version") or metadata.get("source_version") or "").strip()
    if source_version:
        metadata["source_version"] = source_version
    metadata["provider"] = provider
    preview_text = body.get("preview_text")
    if preview_text is not None:
        preview_text_value = str(preview_text)
        if len(preview_text_value) > MAX_REMOTE_PREVIEW_CHARS:
            raise MemoryValidationError(f"preview_text must be at most {MAX_REMOTE_PREVIEW_CHARS} characters.")
        metadata[INGEST_PREVIEW_TEXT_KEY] = preview_text_value
        metadata[INGEST_PREVIEW_TRUNCATED_KEY] = bool(body.get("preview_truncated", body.get("truncated", False)))
    title = " ".join(str(body.get("title") or source.get("title") or "").split()).strip()
    if not title:
        title = title_from_display_path(str(metadata.get("display_path") or "")) or "Storage Drive file"
    ref = {
        "ref_kind": "remote_storage_file",
        "owning_app_id": str(source.get("owning_app_id") or "storage").strip(),
        "entity_type": str(source.get("entity_type") or "file").strip(),
        "entity_id": storage_file_id,
        "file_id": str(source.get("file_id") or storage_file_id).strip(),
        "workspace_relative_path": str(source.get("workspace_relative_path") or "").strip(),
    }
    validate_storage_ref(ref, metadata=metadata, provider=provider)
    return {
        "node_id": str(body.get("node_id") or "").strip(),
        "storage_file_id": storage_file_id,
        "source": source,
        "metadata": metadata,
        "title": title[:240],
        "summary": str(body.get("summary") or "").strip(),
        "body_text": str(body.get("body") or body.get("body_text") or body.get("preview_text") or "").strip(),
        "type": str(body.get("type") or body.get("node_type") or "file_ref").strip(),
        "importance": body.get("importance", 0.5),
        "confidence": body.get("confidence", 1.0),
        "compile_after_ingest": bool(body.get("compile_after_ingest")),
        "ref": ref,
    }


def reject_secret_metadata(metadata: dict[str, Any]) -> None:
    forbidden = sorted(set(_forbidden_metadata_paths(metadata)))
    if forbidden:
        raise MemoryValidationError(f"memory_source metadata must not include Google secret fields: {', '.join(forbidden)}.")


def _forbidden_metadata_paths(value: Any, *, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            normalized = _metadata_key_token(key_text)
            if (
                normalized in FORBIDDEN_REMOTE_METADATA_KEYS
                or normalized.endswith("token")
                or normalized.endswith("secret")
            ):
                paths.append(path)
            paths.extend(_forbidden_metadata_paths(child, prefix=path))
        return paths
    if isinstance(value, list):
        paths = []
        for index, child in enumerate(value):
            paths.extend(_forbidden_metadata_paths(child, prefix=f"{prefix}[{index}]"))
        return paths
    return []


def _metadata_key_token(key: str) -> str:
    return "".join(char for char in key.casefold() if char.isalnum() or char == "_")


def require_source_version(request: dict[str, Any]) -> None:
    if str(request["metadata"].get("source_version") or "").strip():
        return
    raise MemoryValidationError("remote_storage_file ingest requires source_version from Storage drive_index.")


def attach_preview_from_storage(data_root: Path, request: dict[str, Any]) -> None:
    metadata = request["metadata"]
    preview = preview_remote_storage_source(
        data_root,
        provider=str(metadata.get("provider") or ""),
        stable_storage_file_id=request["storage_file_id"],
        connection_id=str(metadata.get("connection_id") or ""),
        drive_file_id=str(metadata.get("drive_file_id") or ""),
    )
    preview_text = str(preview.get("preview_text") or "")
    if len(preview_text) > MAX_REMOTE_PREVIEW_CHARS:
        raise MemoryValidationError(f"preview_text must be at most {MAX_REMOTE_PREVIEW_CHARS} characters.")
    metadata[INGEST_PREVIEW_TEXT_KEY] = preview_text
    metadata[INGEST_PREVIEW_TRUNCATED_KEY] = bool(preview.get("truncated"))
    file_payload = preview.get("file") if isinstance(preview.get("file"), dict) else {}
    source_version = str(
        preview.get("source_version")
        or file_payload.get("source_version")
        or file_payload.get("etag_or_version")
        or file_payload.get("modified_at")
        or metadata.get("source_version")
        or ""
    )
    if source_version:
        metadata["source_version"] = source_version
    display_path = str(file_payload.get("display_path") or metadata.get("display_path") or "")
    if display_path:
        metadata["display_path"] = display_path


def ensure_target_node(db: sqlite3.Connection, request: dict[str, Any]) -> tuple[str, bool]:
    node_id = request["node_id"]
    if node_id:
        row = db.execute("SELECT id FROM nodes WHERE id = ? AND status = 'active'", (node_id,)).fetchone()
        if row is None:
            raise MemoryValidationError("node not found.")
        return node_id, False
    existing_ref = find_existing_storage_ref(db, request["storage_file_id"])
    if existing_ref is not None:
        row = db.execute("SELECT id FROM nodes WHERE id = ? AND status = 'active'", (existing_ref["node_id"],)).fetchone()
        if row is not None:
            return str(row["id"]), False
    timestamp = now_timestamp()
    node_id = new_id("node")
    metadata = {
        "created_from": "storage_source_ingest",
        "owning_app_id": "storage",
        "entity_type": "file",
        "entity_id": request["storage_file_id"],
        "provider": request["metadata"].get("provider", ""),
    }
    db.execute(
        """
        INSERT INTO nodes(id, type, title, summary, body_text, importance, confidence, created_at, updated_at, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            node_id,
            normalize_node_type(request["type"]),
            request["title"],
            request["summary"] or f"Storage file indexed from {request['metadata'].get('provider', 'storage')}.",
            request["body_text"],
            normalize_float(request["importance"], default=0.5, minimum=0, maximum=1, field_name="importance"),
            normalize_float(request["confidence"], default=1.0, minimum=0, maximum=1, field_name="confidence"),
            timestamp,
            timestamp,
            json_text(metadata),
        ),
    )
    refresh_fts(db, node_id)
    record_event(db, event_type="node_created", node_id=node_id, payload={"title": request["title"], "source": "storage_source_ingest"})
    return node_id, True


def find_existing_storage_ref(db: sqlite3.Connection, storage_file_id: str) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT *
        FROM external_refs
        WHERE ref_kind = 'remote_storage_file'
          AND owning_app_id = 'storage'
          AND entity_type = 'file'
          AND (entity_id = ? OR file_id = ?)
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (storage_file_id, storage_file_id),
    ).fetchone()


def find_existing_storage_ref_for_node(db: sqlite3.Connection, storage_file_id: str, node_id: str) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT *
        FROM external_refs
        WHERE node_id = ?
          AND ref_kind = 'remote_storage_file'
          AND owning_app_id = 'storage'
          AND entity_type = 'file'
          AND (entity_id = ? OR file_id = ?)
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (node_id, storage_file_id, storage_file_id),
    ).fetchone()


def upsert_storage_ref(
    db: sqlite3.Connection,
    *,
    request: dict[str, Any],
    node_id: str,
    existing_ref: sqlite3.Row | None,
) -> tuple[dict[str, Any], bool]:
    timestamp = now_timestamp()
    existing_metadata = {}
    if existing_ref is not None:
        existing_payload = row_payload(existing_ref) or {}
        existing_metadata = dict(existing_payload.get("metadata") or {})
    metadata = {**existing_metadata, **request["metadata"]}
    clear_resolved_staleness(metadata)
    if (
        INGEST_PREVIEW_TEXT_KEY not in request["metadata"]
        and existing_metadata.get("source_version")
        and request["metadata"].get("source_version")
        and existing_metadata.get("source_version") != request["metadata"].get("source_version")
    ):
        metadata.pop(INGEST_PREVIEW_TEXT_KEY, None)
        metadata.pop(INGEST_PREVIEW_TRUNCATED_KEY, None)
    ref = {
        "id": str((existing_ref["id"] if existing_ref is not None else "") or request["source"].get("external_ref_id") or new_id("ref")),
        "node_id": node_id,
        "ref_kind": "remote_storage_file",
        "owning_app_id": "storage",
        "entity_type": "file",
        "entity_id": request["storage_file_id"],
        "file_id": request["storage_file_id"],
        "workspace_relative_path": "",
        "uri": str(request["source"].get("uri") or "").strip(),
        "title": request["title"],
        "metadata_json": json_text(metadata),
        "created_at": existing_ref["created_at"] if existing_ref is not None else timestamp,
        "updated_at": timestamp,
    }
    if existing_ref is None:
        db.execute(
            """
            INSERT INTO external_refs(id, node_id, ref_kind, owning_app_id, entity_type, entity_id, file_id,
              workspace_relative_path, uri, title, metadata_json, created_at, updated_at)
            VALUES (:id, :node_id, :ref_kind, :owning_app_id, :entity_type, :entity_id, :file_id,
              :workspace_relative_path, :uri, :title, :metadata_json, :created_at, :updated_at)
            """,
            ref,
        )
        return row_payload(db.execute("SELECT * FROM external_refs WHERE id = ?", (ref["id"],)).fetchone()) or {}, True
    db.execute(
        """
        UPDATE external_refs
        SET node_id = :node_id,
            ref_kind = :ref_kind,
            owning_app_id = :owning_app_id,
            entity_type = :entity_type,
            entity_id = :entity_id,
            file_id = :file_id,
            workspace_relative_path = :workspace_relative_path,
            uri = :uri,
            title = :title,
            metadata_json = :metadata_json,
            updated_at = :updated_at
        WHERE id = :id
        """,
        ref,
    )
    return row_payload(db.execute("SELECT * FROM external_refs WHERE id = ?", (ref["id"],)).fetchone()) or {}, False


def clear_resolved_staleness(metadata: dict[str, Any]) -> None:
    for key in ("stale", "stale_reason", "staleness"):
        metadata.pop(key, None)
    sync_state = metadata.get("sync_state")
    if isinstance(sync_state, dict):
        cleaned = {
            key: value
            for key, value in sync_state.items()
            if key not in {"status", "reason", "error", "last_staleness_at"}
        }
        if cleaned:
            cleaned["status"] = "synced"
            metadata["sync_state"] = cleaned
        else:
            metadata.pop("sync_state", None)


def title_from_display_path(display_path: str) -> str:
    normalized = display_path.strip().rstrip("/")
    if not normalized:
        return ""
    return PurePosixPath(normalized).name
