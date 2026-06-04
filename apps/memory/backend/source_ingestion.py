"""Generic app-owned source ingestion for Memory."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
from typing import Any

from content_store import body_hash, canonical_body, write_body
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
from storage_file_sources import fetch_local_storage_file_source
from sources import ensure_node_source_link, ensure_source_chunks, replace_source_chunks
from wiki import compile_node


SUPPORTED_ADAPTERS = {"inline_markdown", "storage_file"}


def ingest_source(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    """Ingest a normalized source payload into source document/version/chunk rows."""

    ensure_schema(data_root)
    request = normalized_ingest_request(data_root, body)
    with transaction(data_root, immediate=True) as db:
        timestamp = now_timestamp()
        source_document, document_created = upsert_source_document(db, request, timestamp=timestamp)
        source, source_created = upsert_source(db, request, source_document, timestamp=timestamp)
        source_version, version_created = upsert_source_version(
            db,
            data_root=data_root,
            request=request,
            source=source,
            source_document=source_document,
            timestamp=timestamp,
        )
        target_node_id, node_created = ensure_target_node(
            db,
            request,
            source_document=source_document,
            timestamp=timestamp,
        )
        ensure_node_source_link(db, node_id=target_node_id, source_id=source["id"], external_ref_id="", timestamp=timestamp)
        mark_wiki_stale(db, target_node_id, timestamp=timestamp, reason="source_ingested", data_root=data_root)
        record_event(
            db,
            event_type="source_ingested",
            node_id=target_node_id,
            payload={
                "adapter_id": request["adapter_id"],
                "source_document_id": source_document["id"],
                "source_version_id": source_version["id"],
                "version_created": version_created,
                "compile_after_ingest": request["compile_after_ingest"],
            },
        )
        if request["compile_after_ingest"]:
            enqueue_job_in_db(
                db,
                job_type="lint_node",
                dedupe_key=f"lint:{target_node_id}",
                payload={"node_id": target_node_id, "reason": "source_ingested"},
            )
        else:
            enqueue_job_in_db(
                db,
                job_type="compile_node",
                dedupe_key=f"compile:{target_node_id}",
                payload={"node_id": target_node_id, "reason": "source_ingested"},
            )
        node = get_node_with_details(db, target_node_id, data_root=data_root)

    compiled = None
    if request["compile_after_ingest"]:
        compiled = compile_node(data_root, {"node_id": target_node_id})
        node = inspect_node(data_root, target_node_id)

    return {
        "status": "ingested" if document_created or source_created or version_created or node_created else "updated",
        "adapter_id": request["adapter_id"],
        "source_document": source_document,
        "source": source,
        "source_version": source_version,
        "node": node,
        "document_created": document_created,
        "source_created": source_created,
        "source_version_created": version_created,
        "node_created": node_created,
        "compile_after_ingest": request["compile_after_ingest"],
        "compiled": compiled,
    }


def normalized_ingest_request(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    source = body.get("source") if isinstance(body.get("source"), dict) else body
    adapter_id = str(source.get("adapter_id") or body.get("adapter_id") or "").strip()
    if adapter_id not in SUPPORTED_ADAPTERS:
        raise MemoryValidationError("memory_ingest_source supports adapter_id=inline_markdown or storage_file.")
    if adapter_id == "storage_file":
        return normalized_storage_file_request(data_root, body, source)
    return normalized_inline_markdown_request(body, source, adapter_id=adapter_id)


def normalized_inline_markdown_request(body: dict[str, Any], source: dict[str, Any], *, adapter_id: str) -> dict[str, Any]:
    raw_body = source.get("body_markdown", source.get("body", body.get("body_markdown", body.get("body", ""))))
    body_markdown = canonical_body(str(raw_body or ""))
    if not body_markdown.strip():
        raise MemoryValidationError("inline_markdown ingest requires body_markdown.")
    stable_id = str(source.get("source_key") or source.get("stable_source_id") or body.get("source_key") or "").strip()
    title = " ".join(str(body.get("title") or source.get("title") or stable_id or "Inline Memory Source").split()).strip()
    if not stable_id:
        stable_id = f"sha256:{body_hash(body_markdown)}"
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    source_key = stable_id if stable_id.startswith(f"{adapter_id}:") else f"{adapter_id}:{stable_id}"
    return {
        "adapter_id": adapter_id,
        "source_key": source_key,
        "source_kind": "inline_markdown",
        "owning_app_id": "",
        "entity_type": "",
        "entity_id": "",
        "file_id": "",
        "workspace_relative_path": "",
        "uri": "",
        "title": title[:240],
        "summary": str(body.get("summary") or source.get("summary") or "").strip(),
        "body_markdown": body_markdown,
        "version_hash": body_hash(body_markdown),
        "extracted_ref": source_key,
        "hash_kind": "canonical_body",
        "extraction_status": "available",
        "source_modified_at": "",
        "content_type": "text/markdown",
        "node_id": str(body.get("node_id") or "").strip(),
        "node_type": str(body.get("type") or body.get("node_type") or "note").strip(),
        "importance": body.get("importance", 0.5),
        "confidence": body.get("confidence", 1.0),
        "compile_after_ingest": bool(body.get("compile_after_ingest")),
        "metadata": dict(metadata),
    }


def normalized_storage_file_request(data_root: Path, body: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    workspace_relative_path = validate_storage_workspace_relative_path(
        str(source.get("workspace_relative_path") or body.get("workspace_relative_path") or "")
    )
    if not workspace_relative_path:
        raise MemoryValidationError("storage_file ingest requires workspace_relative_path.")
    file_id = str(source.get("file_id") or body.get("file_id") or source.get("entity_id") or body.get("entity_id") or "").strip()
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    storage_snapshot = fetch_local_storage_file_source(data_root, workspace_relative_path)
    file_payload = storage_snapshot["file"]
    file_id = file_id or str(file_payload.get("file_id") or file_payload.get("id") or "").strip()
    resolved_workspace_relative_path = str(file_payload.get("workspace_relative_path") or workspace_relative_path).strip()
    body_markdown = str(storage_snapshot["body_markdown"])
    version_hash, hash_kind = storage_file_version_identity(file_payload, body_markdown)
    stable_id = file_id or resolved_workspace_relative_path
    source_key = f"storage_file:{stable_id}"
    title = " ".join(str(body.get("title") or source.get("title") or file_payload.get("name") or Path(resolved_workspace_relative_path).name).split()).strip()
    content_type = str(source.get("content_type") or body.get("content_type") or file_payload.get("content_type") or content_type_for_path(resolved_workspace_relative_path)).strip()
    modified_at = str(source.get("modified_at") or body.get("modified_at") or file_payload.get("modified_at") or "")
    return {
        "adapter_id": "storage_file",
        "source_key": source_key,
        "source_kind": "storage_file",
        "owning_app_id": "storage",
        "entity_type": "file",
        "entity_id": file_id,
        "file_id": file_id,
        "workspace_relative_path": resolved_workspace_relative_path,
        "uri": "",
        "title": title[:240] or "Storage file",
        "summary": str(body.get("summary") or source.get("summary") or "").strip(),
        "body_markdown": body_markdown,
        "version_hash": version_hash,
        "extracted_ref": resolved_workspace_relative_path,
        "hash_kind": hash_kind,
        "extraction_status": "available",
        "source_modified_at": modified_at,
        "content_type": content_type,
        "node_id": str(body.get("node_id") or "").strip(),
        "node_type": str(body.get("type") or body.get("node_type") or "file_ref").strip(),
        "importance": body.get("importance", 0.5),
        "confidence": body.get("confidence", 1.0),
        "compile_after_ingest": bool(body.get("compile_after_ingest")),
        "metadata": {
            "workspace_relative_path": resolved_workspace_relative_path,
            "file_id": file_id,
            "content_type": content_type,
            "source_modified_at": modified_at,
            "storage_preview_truncated": bool(storage_snapshot.get("preview_truncated")),
            **dict(metadata),
            "storage_sha256": version_hash if hash_kind == "file_bytes" else "",
        },
    }


def upsert_source_document(
    db: sqlite3.Connection,
    request: dict[str, Any],
    *,
    timestamp: str,
) -> tuple[dict[str, Any], bool]:
    existing = db.execute("SELECT * FROM source_documents WHERE source_key = ?", (request["source_key"],)).fetchone()
    document = {
        "id": existing["id"] if existing is not None else new_id("srcdoc"),
        "source_key": request["source_key"],
        "adapter_id": request["adapter_id"],
        "source_kind": request["source_kind"],
        "owning_app_id": request["owning_app_id"],
        "entity_type": request["entity_type"],
        "entity_id": request["entity_id"],
        "file_id": request["file_id"],
        "workspace_relative_path": request["workspace_relative_path"],
        "uri": request["uri"],
        "title": request["title"],
        "created_at": existing["created_at"] if existing is not None else timestamp,
        "updated_at": timestamp,
        "metadata_json": json_text(request["metadata"]),
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
    return row_payload(db.execute("SELECT * FROM source_documents WHERE source_key = ?", (request["source_key"],)).fetchone()) or document, existing is None


def storage_file_version_identity(file_payload: dict[str, Any], body_markdown: str) -> tuple[str, str]:
    for key in ("sha256", "content_sha256", "file_sha256"):
        observed_hash = str(file_payload.get(key) or "").strip().lower()
        if is_sha256_hex(observed_hash):
            return observed_hash, "file_bytes"
    return body_hash(body_markdown), "canonical_body"


def is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def upsert_source(
    db: sqlite3.Connection,
    request: dict[str, Any],
    source_document: dict[str, Any],
    *,
    timestamp: str,
) -> tuple[dict[str, Any], bool]:
    existing = db.execute(
        """
        SELECT s.*
        FROM sources s
        JOIN source_versions sv ON sv.source_id = s.id
        WHERE sv.source_document_id = ?
        ORDER BY sv.observed_at DESC
        LIMIT 1
        """,
        (source_document["id"],),
    ).fetchone()
    source = {
        "id": existing["id"] if existing is not None else new_id("src"),
        "source_kind": request["source_kind"],
        "external_ref_id": None,
        "owning_app_id": request["owning_app_id"],
        "entity_type": request["entity_type"],
        "entity_id": request["entity_id"],
        "file_id": request["file_id"],
        "workspace_relative_path": request["workspace_relative_path"],
        "uri": request["uri"],
        "title": request["title"],
        "content_hash": request["version_hash"],
        "created_at": existing["created_at"] if existing is not None else timestamp,
        "updated_at": timestamp,
        "metadata_json": json_text({"source_document_id": source_document["id"], "adapter_id": request["adapter_id"]}),
    }
    if existing is None:
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
    else:
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
    return row_payload(db.execute("SELECT * FROM sources WHERE id = ?", (source["id"],)).fetchone()) or source, existing is None


def upsert_source_version(
    db: sqlite3.Connection,
    *,
    data_root: Path,
    request: dict[str, Any],
    source: dict[str, Any],
    source_document: dict[str, Any],
    timestamp: str,
) -> tuple[dict[str, Any], bool]:
    existing = db.execute(
        "SELECT * FROM source_versions WHERE source_id = ? AND version_hash = ?",
        (source["id"], request["version_hash"]),
    ).fetchone()
    if existing is not None:
        version = row_payload(existing) or {}
        ensure_source_chunks(
            db,
            data_root=data_root,
            version=version,
            snapshot={"extracted_text": request["body_markdown"], "hash_kind": request["hash_kind"], "extracted_ref": request["extracted_ref"]},
            timestamp=timestamp,
        )
        return version, False
    body_record = write_body(
        data_root,
        kind="sources",
        body_markdown=request["body_markdown"],
        metadata={
            "source_id": source["id"],
            "source_document_id": source_document["id"],
            "version_hash": request["version_hash"],
            "hash_kind": request["hash_kind"],
        },
    )
    version = {
        "id": new_id("srcv"),
        "source_id": source["id"],
        "source_document_id": source_document["id"],
        "version_hash": request["version_hash"],
        "extracted_text": request["body_markdown"],
        "extracted_ref": request["extracted_ref"],
        "body_path": body_record.relative_path,
        "body_sha256": body_record.body_sha256,
        "body_bytes": body_record.body_bytes,
        "hash_kind": request["hash_kind"],
        "extraction_status": request["extraction_status"],
        "source_modified_at": request["source_modified_at"],
        "content_type": request["content_type"],
        "observed_at": timestamp,
        "created_at": timestamp,
        "metadata_json": json_text({"adapter_id": request["adapter_id"], **request["metadata"]}),
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
    replace_source_chunks(
        db,
        data_root=data_root,
        version=version,
        body=request["body_markdown"],
        base_locator=request["extracted_ref"],
        locator_kind=locator_kind_for_version(version),
        hash_kind=request["hash_kind"],
        timestamp=timestamp,
    )
    return row_payload(db.execute("SELECT * FROM source_versions WHERE id = ?", (version["id"],)).fetchone()) or version, True


def ensure_target_node(
    db: sqlite3.Connection,
    request: dict[str, Any],
    *,
    source_document: dict[str, Any],
    timestamp: str,
) -> tuple[str, bool]:
    node_id = request["node_id"]
    if node_id:
        row = db.execute("SELECT id FROM nodes WHERE id = ? AND status = 'active'", (node_id,)).fetchone()
        if row is None:
            raise MemoryValidationError("node not found.")
        return node_id, False
    existing = db.execute(
        """
        SELECT n.id
        FROM nodes n
        JOIN node_source_links nsl ON nsl.node_id = n.id
        JOIN sources s ON s.id = nsl.source_id
        JOIN source_versions sv ON sv.source_id = s.id
        WHERE sv.source_document_id = ? AND n.status = 'active'
        ORDER BY n.updated_at DESC
        LIMIT 1
        """,
        (source_document["id"],),
    ).fetchone()
    if existing is not None:
        return str(existing["id"]), False
    node_id = f"node_{sha256(source_document['source_key'].encode('utf-8')).hexdigest()[:16]}"
    row = db.execute("SELECT id FROM nodes WHERE id = ? AND status = 'active'", (node_id,)).fetchone()
    if row is not None:
        return node_id, False
    db.execute(
        """
        INSERT INTO nodes(id, type, title, summary, body_text, importance, confidence, created_at, updated_at, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            node_id,
            normalize_node_type(request["node_type"]),
            request["title"],
            request["summary"] or "Inline Memory source.",
            request["body_markdown"],
            normalize_float(request["importance"], default=0.5, minimum=0, maximum=1, field_name="importance"),
            normalize_float(request["confidence"], default=1.0, minimum=0, maximum=1, field_name="confidence"),
            timestamp,
            timestamp,
            json_text({"created_from": "source_ingest", "source_document_id": source_document["id"], "adapter_id": request["adapter_id"]}),
        ),
    )
    refresh_fts(db, node_id)
    record_event(db, event_type="node_created", node_id=node_id, payload={"title": request["title"], "source": "source_ingest"})
    return node_id, True


def locator_kind_for_version(version: dict[str, Any]) -> str:
    extracted_ref = str(version.get("extracted_ref") or "")
    if extracted_ref.startswith(("storage/uploaded/", "storage/generated/")):
        return "workspace_relative_path"
    return "inline_markdown"


def validate_storage_workspace_relative_path(value: str) -> str:
    normalized = str(value or "").strip()
    path = Path(normalized)
    if not normalized:
        return ""
    if path.is_absolute() or ".." in path.parts:
        raise MemoryValidationError("workspace_relative_path must stay inside the workspace.")
    if not normalized.startswith(("storage/uploaded/", "storage/generated/")):
        raise MemoryValidationError("workspace_relative_path must point to workspace storage.")
    return path.as_posix()


def content_type_for_path(workspace_relative_path: str) -> str:
    suffix = Path(workspace_relative_path).suffix.lower()
    if suffix == ".md":
        return "text/markdown"
    if suffix == ".json":
        return "application/json"
    if suffix in {".yaml", ".yml"}:
        return "application/yaml"
    if suffix == ".csv":
        return "text/csv"
    return "text/plain"
