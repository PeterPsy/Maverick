"""CRM activity, task, and note record mutations."""

from __future__ import annotations

from typing import Any

from domains.record_lifecycle import note_title, validate_relationships
from store import get_record, metadata, new_id, require_text, upsert_fts, utc_now, write_event


def log_activity(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    activity_id = require_text(payload, "id") or new_id("act")
    validate_relationships(db, payload, ("account_id", "contact_id", "deal_id"))
    db.execute(
        """
        INSERT INTO activities(id, activity_type, subject, body, account_id, contact_id, deal_id, occurred_at, due_at, completed_at, owner_id, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            activity_id,
            require_text(payload, "activity_type", default="note") or "note",
            require_text(payload, "subject", required=True),
            require_text(payload, "body"),
            require_text(payload, "account_id"),
            require_text(payload, "contact_id"),
            require_text(payload, "deal_id"),
            require_text(payload, "occurred_at", default=now) or now,
            require_text(payload, "due_at"),
            require_text(payload, "completed_at"),
            require_text(payload, "owner_id"),
            metadata(payload),
            now,
            now,
        ),
    )
    record = get_record(db, "activity", activity_id)
    upsert_fts(db, "activity", activity_id, record["subject"], f"{record.get('body', '')} {record.get('activity_type', '')}")
    write_event(db, "activity.logged", "activity", activity_id)
    return record


def update_activity(db, payload: dict[str, Any]) -> dict[str, Any]:
    activity_id = require_text(payload, "id", required=True)
    current = get_record(db, "activity", activity_id)
    merged = {**current, **{key: value for key, value in payload.items() if key in {"activity_type", "subject", "body", "account_id", "contact_id", "deal_id", "occurred_at", "due_at", "completed_at", "owner_id", "metadata"}}}
    validate_relationships(db, merged, ("account_id", "contact_id", "deal_id"))
    db.execute(
        """
        UPDATE activities SET activity_type = ?, subject = ?, body = ?, account_id = ?, contact_id = ?, deal_id = ?,
          occurred_at = ?, due_at = ?, completed_at = ?, owner_id = ?, metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            require_text(merged, "activity_type", default="note") or "note",
            require_text(merged, "subject", required=True),
            require_text(merged, "body"),
            require_text(merged, "account_id"),
            require_text(merged, "contact_id"),
            require_text(merged, "deal_id"),
            require_text(merged, "occurred_at", default=utc_now()) or utc_now(),
            require_text(merged, "due_at"),
            require_text(merged, "completed_at"),
            require_text(merged, "owner_id"),
            metadata(merged),
            utc_now(),
            activity_id,
        ),
    )
    record = get_record(db, "activity", activity_id)
    upsert_fts(db, "activity", activity_id, record["subject"], f"{record.get('body', '')} {record.get('activity_type', '')}")
    write_event(db, "activity.updated", "activity", activity_id)
    return record


def create_task(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    task_id = require_text(payload, "id") or new_id("task")
    validate_relationships(db, payload, ("account_id", "contact_id", "deal_id"))
    db.execute(
        """
        INSERT INTO tasks(id, title, status, priority, due_at, account_id, contact_id, deal_id, owner_id, body, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            require_text(payload, "title", required=True),
            require_text(payload, "status", default="open") or "open",
            require_text(payload, "priority", default="normal") or "normal",
            require_text(payload, "due_at"),
            require_text(payload, "account_id"),
            require_text(payload, "contact_id"),
            require_text(payload, "deal_id"),
            require_text(payload, "owner_id"),
            require_text(payload, "body"),
            metadata(payload),
            now,
            now,
        ),
    )
    record = get_record(db, "task", task_id)
    upsert_fts(db, "task", task_id, record["title"], f"{record.get('body', '')} {record.get('status', '')} {record.get('priority', '')}")
    write_event(db, "task.created", "task", task_id)
    return record


def update_task(db, payload: dict[str, Any]) -> dict[str, Any]:
    task_id = require_text(payload, "id", required=True)
    current = get_record(db, "task", task_id)
    merged = {**current, **{key: value for key, value in payload.items() if key in {"title", "status", "priority", "due_at", "account_id", "contact_id", "deal_id", "owner_id", "body", "metadata"}}}
    validate_relationships(db, merged, ("account_id", "contact_id", "deal_id"))
    db.execute(
        """
        UPDATE tasks SET title = ?, status = ?, priority = ?, due_at = ?, account_id = ?, contact_id = ?, deal_id = ?,
          owner_id = ?, body = ?, metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            require_text(merged, "title", required=True),
            require_text(merged, "status", default="open") or "open",
            require_text(merged, "priority", default="normal") or "normal",
            require_text(merged, "due_at"),
            require_text(merged, "account_id"),
            require_text(merged, "contact_id"),
            require_text(merged, "deal_id"),
            require_text(merged, "owner_id"),
            require_text(merged, "body"),
            metadata(merged),
            utc_now(),
            task_id,
        ),
    )
    record = get_record(db, "task", task_id)
    upsert_fts(db, "task", task_id, record["title"], f"{record.get('body', '')} {record.get('status', '')} {record.get('priority', '')}")
    write_event(db, "task.updated", "task", task_id)
    return record


def create_note(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    note_id = require_text(payload, "id") or new_id("note")
    validate_relationships(db, payload, ("account_id", "contact_id", "deal_id"))
    body = require_text(payload, "body", required=True)
    db.execute(
        """
        INSERT INTO notes(id, body, account_id, contact_id, deal_id, owner_id, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            note_id,
            body,
            require_text(payload, "account_id"),
            require_text(payload, "contact_id"),
            require_text(payload, "deal_id"),
            require_text(payload, "owner_id"),
            metadata(payload),
            now,
            now,
        ),
    )
    record = get_record(db, "note", note_id)
    upsert_fts(db, "note", note_id, note_title(record), body)
    write_event(db, "note.created", "note", note_id)
    return record


def update_note(db, payload: dict[str, Any]) -> dict[str, Any]:
    note_id = require_text(payload, "id", required=True)
    current = get_record(db, "note", note_id)
    merged = {**current, **{key: value for key, value in payload.items() if key in {"body", "account_id", "contact_id", "deal_id", "owner_id", "metadata"}}}
    validate_relationships(db, merged, ("account_id", "contact_id", "deal_id"))
    db.execute(
        """
        UPDATE notes SET body = ?, account_id = ?, contact_id = ?, deal_id = ?, owner_id = ?, metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            require_text(merged, "body", required=True),
            require_text(merged, "account_id"),
            require_text(merged, "contact_id"),
            require_text(merged, "deal_id"),
            require_text(merged, "owner_id"),
            metadata(merged),
            utc_now(),
            note_id,
        ),
    )
    record = get_record(db, "note", note_id)
    upsert_fts(db, "note", note_id, note_title(record), record["body"])
    write_event(db, "note.updated", "note", note_id)
    return record
