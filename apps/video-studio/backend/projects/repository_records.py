"""Atomic revision-engine records layered on the foundation repository."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from project_ir.canonical import canonical_dumps, content_digest

from .errors import ProjectError


def record_batch(
    connection: sqlite3.Connection,
    *,
    project_id: str,
    batch_id: str,
    workspace_id: str,
    base_revision_id: str,
    request_digest: str,
    result_revision_id: str,
    result: dict[str, Any],
    timestamp: str,
) -> None:
    connection.execute(
        """
        INSERT INTO project_operation_batches(
          project_id, operation_batch_id, workspace_id, base_revision_id,
          request_digest, result_revision_id, result_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            batch_id,
            workspace_id,
            base_revision_id,
            request_digest,
            result_revision_id,
            canonical_dumps(result),
            timestamp,
        ),
    )


def record_autosave(
    connection: sqlite3.Connection,
    *,
    project_id: str,
    batch_id: str,
    revision_id: str,
    metadata: dict[str, Any],
    timestamp: str,
) -> None:
    connection.execute(
        """
        INSERT INTO project_autosaves(
          autosave_id, project_id, operation_batch_id, revision_id,
          metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            f"autosave-{content_digest([project_id, batch_id])}",
            project_id,
            batch_id,
            revision_id,
            canonical_dumps(metadata),
            timestamp,
        ),
    )


def enqueue_event(
    connection: sqlite3.Connection,
    *,
    project_id: str,
    revision_id: str | None,
    event_type: str,
    resource: str,
    payload: dict[str, Any],
    timestamp: str,
    dedupe_key: str,
) -> str:
    event_id = f"event-{content_digest([project_id, event_type, dedupe_key])}"
    connection.execute(
        """
        INSERT OR IGNORE INTO project_outbox(
          event_id, project_id, revision_id, event_type, resource,
          payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            project_id,
            revision_id,
            event_type,
            resource,
            canonical_dumps(payload),
            timestamp,
        ),
    )
    return event_id


def set_archived(
    connection: sqlite3.Connection,
    *,
    project_id: str,
    archived_at: str | None,
    timestamp: str,
) -> bool:
    row = connection.execute(
        "SELECT archived_at FROM projects WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    if row is None:
        raise ProjectError("project_not_found", "Project was not found.", status_code=404)
    was_archived = row[0] is not None
    should_archive = archived_at is not None
    if was_archived == should_archive:
        return False
    connection.execute(
        "UPDATE projects SET archived_at = ?, updated_at = ? WHERE project_id = ?",
        (archived_at, timestamp, project_id),
    )
    return True


def pending_events(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT event_id, project_id, revision_id, event_type, resource,
               payload_json, created_at
        FROM project_outbox WHERE state = 'pending'
        ORDER BY created_at, event_id
        """
    ).fetchall()
    return [
        {
            "event_id": str(row[0]),
            "project_id": str(row[1]),
            "revision_id": str(row[2]) if row[2] is not None else None,
            "event_type": str(row[3]),
            "resource": str(row[4]),
            "payload": json.loads(str(row[5])),
            "created_at": str(row[6]),
        }
        for row in rows
    ]
