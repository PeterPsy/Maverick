"""App-owned ingest job lifecycle for Memory."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from database import connect, ensure_schema, json_text, new_id, normalize_limit, now_timestamp, record_event, row_payload, transaction
from errors import MemoryValidationError
from job_provenance import resolve_job_provenance


JOB_TYPES = {"ingest_source", "compile_node", "lint_node", "mark_stale", "requires_storage_reindex"}
TERMINAL_STATUSES = {"done", "failed", "cancelled"}


def enqueue_job(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(data_root)
    with transaction(data_root, immediate=True) as db:
        return enqueue_job_in_db(
            db,
            job_type=str(body.get("job_type") or ""),
            dedupe_key=str(body.get("dedupe_key") or ""),
            payload=body.get("payload") if isinstance(body.get("payload"), dict) else {},
            available_at=str(body.get("available_at") or ""),
            max_attempts=body.get("max_attempts"),
        )


def enqueue_job_in_db(
    db: sqlite3.Connection,
    *,
    job_type: str,
    dedupe_key: str = "",
    payload: dict[str, Any] | None = None,
    available_at: str = "",
    max_attempts: object = None,
) -> dict[str, Any]:
    normalized_type = normalize_job_type(job_type)
    normalized_dedupe = dedupe_key.strip()
    timestamp = now_timestamp()
    available = normalize_timestamp(available_at, default=timestamp)
    attempts = normalize_limit(max_attempts, default=3, minimum=1, maximum=20, field_name="max_attempts")
    node_id, source_document_id, source_version_id = resolve_job_provenance(db, payload)
    if normalized_dedupe:
        existing = db.execute(
            """
            SELECT *
            FROM ingest_jobs
            WHERE dedupe_key = ? AND status IN ('ready', 'running')
            ORDER BY created_at
            LIMIT 1
            """,
            (normalized_dedupe,),
        ).fetchone()
        if existing is not None:
            if existing["status"] == "ready":
                db.execute(
                    """
                    UPDATE ingest_jobs
                    SET payload_json = ?,
                        node_id = ?,
                        source_document_id = ?,
                        source_version_id = ?,
                        available_at = ?,
                        max_attempts = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (json_text(payload), node_id, source_document_id, source_version_id, available, attempts, timestamp, existing["id"]),
                )
            job = row_payload(db.execute("SELECT * FROM ingest_jobs WHERE id = ?", (existing["id"],)).fetchone()) or {}
            job["enqueued"] = False
            return job
    job = {
        "id": new_id("job"),
        "job_type": normalized_type,
        "dedupe_key": normalized_dedupe,
        "status": "ready",
        "attempt_count": 0,
        "max_attempts": attempts,
        "available_at": available,
        "locked_until": None,
        "lease_token": "",
        "last_error": "",
        "payload_json": json_text(payload),
        "node_id": node_id,
        "source_document_id": source_document_id,
        "source_version_id": source_version_id,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    db.execute(
        """
        INSERT INTO ingest_jobs(
          id, job_type, dedupe_key, status, attempt_count, max_attempts, available_at,
          locked_until, lease_token, last_error, payload_json, node_id, source_document_id,
          source_version_id, created_at, updated_at
        )
        VALUES (
          :id, :job_type, :dedupe_key, :status, :attempt_count, :max_attempts, :available_at,
          :locked_until, :lease_token, :last_error, :payload_json, :node_id, :source_document_id,
          :source_version_id, :created_at, :updated_at
        )
        """,
        job,
    )
    record_event(db, event_type="ingest_job_enqueued", payload={"job_id": job["id"], "job_type": normalized_type, "dedupe_key": normalized_dedupe})
    payload_job = row_payload(db.execute("SELECT * FROM ingest_jobs WHERE id = ?", (job["id"],)).fetchone()) or {}
    payload_job["enqueued"] = True
    return payload_job


def claim_job(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(data_root)
    job_types = normalize_job_types(body.get("job_types"))
    lease_seconds = normalize_limit(body.get("lease_seconds"), default=300, minimum=30, maximum=3600, field_name="lease_seconds")
    timestamp = now_timestamp()
    locked_until = (datetime.now(tz=UTC) + timedelta(seconds=lease_seconds)).isoformat()
    lease_token = f"lease_{uuid4().hex}"
    with transaction(data_root, immediate=True) as db:
        row = next_ready_job(db, job_types=job_types, timestamp=timestamp)
        if row is None:
            return {"job": None}
        db.execute(
            """
            UPDATE ingest_jobs
            SET status = 'running',
                attempt_count = attempt_count + 1,
                locked_until = ?,
                lease_token = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (locked_until, lease_token, timestamp, row["id"]),
        )
        record_event(db, event_type="ingest_job_claimed", payload={"job_id": row["id"], "job_type": row["job_type"]})
        return {"job": row_payload(db.execute("SELECT * FROM ingest_jobs WHERE id = ?", (row["id"],)).fetchone())}


def complete_job(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(data_root)
    job_id, lease_token = require_job_lease(body)
    with transaction(data_root, immediate=True) as db:
        job = running_job_for_lease(db, job_id, lease_token)
        timestamp = now_timestamp()
        db.execute(
            """
            UPDATE ingest_jobs
            SET status = 'done', locked_until = NULL, lease_token = '', last_error = '', updated_at = ?
            WHERE id = ?
            """,
            (timestamp, job_id),
        )
        record_event(db, event_type="ingest_job_completed", payload={"job_id": job_id, "job_type": job["job_type"]})
        return {"job": row_payload(db.execute("SELECT * FROM ingest_jobs WHERE id = ?", (job_id,)).fetchone())}


def fail_job(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(data_root)
    job_id, lease_token = require_job_lease(body)
    error = str(body.get("error") or body.get("last_error") or "job failed").strip()[:1000]
    with transaction(data_root, immediate=True) as db:
        job = running_job_for_lease(db, job_id, lease_token)
        timestamp = now_timestamp()
        attempt_count = int(job["attempt_count"] or 0)
        max_attempts = int(job["max_attempts"] or 1)
        if attempt_count >= max_attempts:
            status = "failed"
            available_at = timestamp
        else:
            status = "ready"
            available_at = (datetime.now(tz=UTC) + timedelta(seconds=retry_backoff_seconds(attempt_count))).isoformat()
        db.execute(
            """
            UPDATE ingest_jobs
            SET status = ?, available_at = ?, locked_until = NULL, lease_token = '', last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, available_at, error, timestamp, job_id),
        )
        record_event(db, event_type="ingest_job_failed", payload={"job_id": job_id, "job_type": job["job_type"], "status": status})
        return {"job": row_payload(db.execute("SELECT * FROM ingest_jobs WHERE id = ?", (job_id,)).fetchone())}


def cancel_job(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(data_root)
    job_id = str(body.get("job_id") or body.get("id") or "").strip()
    if not job_id:
        raise MemoryValidationError("job_id is required.")
    with transaction(data_root, immediate=True) as db:
        row = db.execute("SELECT * FROM ingest_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise MemoryValidationError("job not found.")
        if row["status"] in TERMINAL_STATUSES:
            return {"job": row_payload(row)}
        timestamp = now_timestamp()
        db.execute(
            "UPDATE ingest_jobs SET status = 'cancelled', locked_until = NULL, lease_token = '', updated_at = ? WHERE id = ?",
            (timestamp, job_id),
        )
        record_event(db, event_type="ingest_job_cancelled", payload={"job_id": job_id, "job_type": row["job_type"]})
        return {"job": row_payload(db.execute("SELECT * FROM ingest_jobs WHERE id = ?", (job_id,)).fetchone())}


def list_jobs(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(data_root)
    status = str(body.get("status") or "").strip()
    job_type = str(body.get("job_type") or "").strip()
    if status and status not in {"ready", "running", *TERMINAL_STATUSES}:
        raise MemoryValidationError("unsupported job status.")
    if job_type:
        normalize_job_type(job_type)
    limit = normalize_limit(body.get("limit"), default=50, minimum=1, maximum=200)
    where = []
    values: list[Any] = []
    if status:
        where.append("status = ?")
        values.append(status)
    if job_type:
        where.append("job_type = ?")
        values.append(job_type)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    with connect(data_root) as db:
        rows = db.execute(
            f"SELECT * FROM ingest_jobs {clause} ORDER BY updated_at DESC LIMIT ?",
            (*values, limit),
        )
        return {"jobs": [row_payload(row) or {} for row in rows]}


def next_ready_job(db: sqlite3.Connection, *, job_types: list[str], timestamp: str) -> sqlite3.Row | None:
    type_clause = ""
    values: list[Any] = [timestamp, timestamp]
    if job_types:
        placeholders = ",".join("?" for _item in job_types)
        type_clause = f"AND job_type IN ({placeholders})"
        values.extend(job_types)
    return db.execute(
        f"""
        SELECT *
        FROM ingest_jobs
        WHERE attempt_count < max_attempts
          AND (
            (status = 'ready' AND available_at <= ?)
            OR (status = 'running' AND locked_until IS NOT NULL AND locked_until <= ?)
          )
          {type_clause}
        ORDER BY available_at, created_at
        LIMIT 1
        """,
        tuple(values),
    ).fetchone()


def running_job_for_lease(db: sqlite3.Connection, job_id: str, lease_token: str) -> sqlite3.Row:
    row = db.execute(
        "SELECT * FROM ingest_jobs WHERE id = ? AND status = 'running' AND lease_token = ?",
        (job_id, lease_token),
    ).fetchone()
    if row is None:
        raise MemoryValidationError("running job lease was not found.")
    return row


def require_job_lease(body: dict[str, Any]) -> tuple[str, str]:
    job_id = str(body.get("job_id") or body.get("id") or "").strip()
    lease_token = str(body.get("lease_token") or "").strip()
    if not job_id:
        raise MemoryValidationError("job_id is required.")
    if not lease_token:
        raise MemoryValidationError("lease_token is required.")
    return job_id, lease_token


def retry_backoff_seconds(attempt_count: int) -> int:
    return min(3600, max(30, 30 * (2 ** max(0, attempt_count - 1))))


def normalize_job_type(job_type: str) -> str:
    normalized = str(job_type or "").strip()
    if normalized not in JOB_TYPES:
        raise MemoryValidationError("job_type must be ingest_source, compile_node, lint_node, mark_stale, or requires_storage_reindex.")
    return normalized


def normalize_job_types(raw_job_types: object) -> list[str]:
    if raw_job_types is None or raw_job_types == "":
        return []
    if not isinstance(raw_job_types, list):
        raise MemoryValidationError("job_types must be a list.")
    normalized: list[str] = []
    for raw_type in raw_job_types:
        job_type = normalize_job_type(str(raw_type or ""))
        if job_type not in normalized:
            normalized.append(job_type)
    return normalized


def normalize_timestamp(value: str, *, default: str) -> str:
    if not value:
        return default
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MemoryValidationError("available_at must be an ISO timestamp.") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()
