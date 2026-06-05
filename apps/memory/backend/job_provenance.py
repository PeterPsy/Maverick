"""Resolve indexed provenance for Memory ingest jobs."""

from __future__ import annotations

import sqlite3
from typing import Any


REMOTE_STORAGE_PROVIDERS = {"google_drive"}
STORAGE_APP_ID = "storage"
STORAGE_FILE_ENTITY_TYPE = "file"


def resolve_job_provenance(db: sqlite3.Connection, payload: Any) -> tuple[str, str, str]:
    data = payload if isinstance(payload, dict) else {}
    payloads = nested_payloads(data)
    source_document = data.get("source_document") if isinstance(data.get("source_document"), dict) else {}
    source_version = data.get("source_version") if isinstance(data.get("source_version"), dict) else {}
    node = data.get("node") if isinstance(data.get("node"), dict) else {}
    node_id = first_text(data.get("node_id"), data.get("target_node_id"), node.get("id"), node.get("node_id"))
    source_document_id = first_text(data.get("source_document_id"), source_document.get("id"), source_version.get("source_document_id"))
    source_version_id = first_text(data.get("source_version_id"), source_version.get("id"))

    if source_version_id and not source_document_id:
        source_document_id = source_document_id_for_version(db, source_version_id)
    if not source_document_id:
        source_document_id = source_document_id_for_payload(db, payloads)
    if source_document_id and not source_version_id:
        source_version_id = latest_source_version_id(db, source_document_id)
    return node_id, source_document_id, source_version_id


def nested_payloads(data: dict[str, Any]) -> list[dict[str, Any]]:
    payloads = [data]
    for key in ("source", "memory_source", "source_document", "source_version", "storage_identity", "source_identity"):
        value = data.get(key)
        if isinstance(value, dict):
            payloads.append(value)
    return payloads


def source_document_id_for_version(db: sqlite3.Connection, source_version_id: str) -> str:
    row = db.execute("SELECT source_document_id FROM source_versions WHERE id = ? LIMIT 1", (source_version_id,)).fetchone()
    return str(row["source_document_id"] or "").strip() if row is not None else ""


def source_document_id_for_payload(db: sqlite3.Connection, payloads: list[dict[str, Any]]) -> str:
    for source_key in source_key_candidates(payloads):
        row = db.execute("SELECT id FROM source_documents WHERE source_key = ? LIMIT 1", (source_key,)).fetchone()
        if row is not None:
            return str(row["id"] or "").strip()

    for payload in payloads:
        owning_app_id = first_text(payload.get("owning_app_id"), payload.get("app_id"))
        entity_type = first_text(payload.get("entity_type"), payload.get("type"))
        entity_id = first_text(payload.get("entity_id"), payload.get("stable_storage_file_id"))
        if owning_app_id and entity_type and entity_id:
            row = db.execute(
                """
                SELECT id
                FROM source_documents
                WHERE owning_app_id = ? AND entity_type = ? AND entity_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (owning_app_id, entity_type, entity_id),
            ).fetchone()
            if row is not None:
                return str(row["id"] or "").strip()

        file_id = first_text(payload.get("file_id"), payload.get("stable_storage_file_id"))
        if file_id:
            row = db.execute(
                """
                SELECT id
                FROM source_documents
                WHERE file_id = ? OR entity_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (file_id, file_id),
            ).fetchone()
            if row is not None:
                return str(row["id"] or "").strip()

        workspace_relative_path = first_text(payload.get("workspace_relative_path"))
        if workspace_relative_path:
            row = db.execute(
                """
                SELECT id
                FROM source_documents
                WHERE workspace_relative_path = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (workspace_relative_path,),
            ).fetchone()
            if row is not None:
                return str(row["id"] or "").strip()
    return ""


def source_key_candidates(payloads: list[dict[str, Any]]) -> list[str]:
    candidates: list[str] = []
    for payload in payloads:
        adapter_id = first_text(payload.get("adapter_id"))
        raw_key = first_text(payload.get("source_key"), payload.get("stable_source_id"))
        if raw_key:
            append_unique(candidates, raw_key)
            if adapter_id and not raw_key.startswith(f"{adapter_id}:"):
                append_unique(candidates, f"{adapter_id}:{raw_key}")

        owning_app_id = first_text(payload.get("owning_app_id"), payload.get("app_id"))
        entity_type = first_text(payload.get("entity_type"), payload.get("type"))
        entity_id = first_text(payload.get("entity_id"), payload.get("stable_storage_file_id"))
        file_id = first_text(payload.get("file_id"), payload.get("stable_storage_file_id"), entity_id)
        workspace_relative_path = first_text(payload.get("workspace_relative_path"))
        source_kind = first_text(payload.get("source_kind"), payload.get("ref_kind"))
        provider = first_text(payload.get("provider"), nested_text(payload, "metadata", "provider"))
        is_remote_storage = bool(
            file_id and (source_kind == "remote_storage_file" or adapter_id == "remote_storage_file" or provider in REMOTE_STORAGE_PROVIDERS)
        )
        is_storage_file = bool(
            file_id and (adapter_id == "storage_file" or owning_app_id == STORAGE_APP_ID or entity_type == STORAGE_FILE_ENTITY_TYPE)
        )

        if is_remote_storage:
            append_unique(candidates, f"remote_storage_file:{file_id}")
        if is_storage_file:
            append_unique(candidates, f"storage_file:{file_id}")
        if workspace_relative_path:
            append_unique(candidates, f"storage_file:{workspace_relative_path}")
        if owning_app_id and entity_type and entity_id and not (is_remote_storage or is_storage_file):
            append_unique(candidates, f"app_entity:{owning_app_id}:{entity_type}:{entity_id}")
    return candidates


def latest_source_version_id(db: sqlite3.Connection, source_document_id: str) -> str:
    row = db.execute(
        """
        SELECT id
        FROM source_versions
        WHERE source_document_id = ?
        ORDER BY observed_at DESC, created_at DESC
        LIMIT 1
        """,
        (source_document_id,),
    ).fetchone()
    return str(row["id"] or "").strip() if row is not None else ""


def nested_text(payload: dict[str, Any], parent_key: str, child_key: str) -> str:
    parent = payload.get(parent_key) if isinstance(payload.get(parent_key), dict) else {}
    return first_text(parent.get(child_key))


def append_unique(values: list[str], value: str) -> None:
    normalized = str(value or "").strip()
    if normalized and normalized not in values:
        values.append(normalized)


def first_text(*values: Any) -> str:
    for value in values:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""
