"""Persistence operations for Gmail App workspace data."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from database import connect, ensure_schema, health_payload, json_dumps, json_loads
from errors import GmailAppValidationError
from gmail_models import GmailThread, has_excluded_system_label, utc_now
from attachments import normalize_attachments

__all__ = [
    "consume_send_approval",
    "create_send_approval",
    "create_suggestion",
    "ensure_schema",
    "get_thread",
    "get_message",
    "health_payload",
    "list_accounts",
    "list_audit",
    "list_suggestions",
    "list_threads",
    "reference_search_messages",
    "reference_search_threads",
    "mark_thread_read",
    "mark_suggestion_decision",
    "record_audit",
    "record_sent_message",
    "save_thread",
    "upsert_account",
]


def record_audit(data_root: Path, event_type: str, *, actor: str = "system", subject_id: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    event = {"id": f"audit_{uuid4().hex}", "event_type": event_type, "actor": actor, "subject_id": subject_id, "payload": payload or {}, "created_at": utc_now()}
    with connect(data_root) as connection:
        connection.execute(
            "INSERT INTO audit_events(id, event_type, actor, subject_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (event["id"], event_type, actor, subject_id, json_dumps(event["payload"]), event["created_at"]),
        )
    return event


def list_audit(data_root: Path, limit: int = 20) -> list[dict[str, Any]]:
    with connect(data_root) as connection:
        rows = connection.execute("SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 100)),)).fetchall()
    return [
        {"id": row["id"], "event_type": row["event_type"], "actor": row["actor"], "subject_id": row["subject_id"], "payload": json_loads(row["payload_json"]), "created_at": row["created_at"]}
        for row in rows
    ]


def upsert_account(data_root: Path, email: str, *, display_name: str = "", oauth_secret_ref: str = "") -> dict[str, Any]:
    if not email:
        raise GmailAppValidationError("Account email is required.")
    now = utc_now()
    with connect(data_root) as connection:
        existing = connection.execute("SELECT connected_at FROM gmail_accounts WHERE email = ?", (email,)).fetchone()
        connection.execute(
            "INSERT OR REPLACE INTO gmail_accounts(email, display_name, oauth_secret_ref, connected_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (email, display_name, oauth_secret_ref, existing["connected_at"] if existing else now, now),
        )
    record_audit(data_root, "gmail.account_configured", subject_id=email, payload={"email": email, "oauth_secret_ref": bool(oauth_secret_ref)})
    return {"email": email, "display_name": display_name, "connected_at": now, "oauth_secret_ref": bool(oauth_secret_ref)}


def list_accounts(data_root: Path) -> list[dict[str, Any]]:
    with connect(data_root) as connection:
        rows = connection.execute("SELECT email, display_name, oauth_secret_ref, connected_at, updated_at FROM gmail_accounts ORDER BY updated_at DESC").fetchall()
    return [
        {
            "email": row["email"],
            "display_name": row["display_name"],
            "has_oauth_secret_ref": bool(row["oauth_secret_ref"]),
            "connected_at": row["connected_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def save_thread(data_root: Path, thread: GmailThread) -> dict[str, Any]:
    with connect(data_root) as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO threads(id, subject, participants_json, snippet, updated_at, is_unread, labels_json, last_reviewed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT last_reviewed_at FROM threads WHERE id = ?), ''))
            """,
            (thread.id, thread.subject, json_dumps(thread.participants), thread.snippet, thread.updated_at, int(thread.is_unread), json_dumps(thread.labels or []), thread.id),
        )
        for message in thread.messages:
            connection.execute(
                """
                INSERT OR REPLACE INTO messages(id, thread_id, from_email, to_emails_json, subject, snippet, body_text, received_at, is_unread)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (message.id, message.thread_id, message.from_email, json_dumps(message.to_emails), message.subject, message.snippet, message.body_text, message.received_at, int(message.is_unread)),
            )
    return get_thread(data_root, thread.id)


def get_thread(data_root: Path, thread_id: str) -> dict[str, Any]:
    if not thread_id:
        raise GmailAppValidationError("thread_id is required.")
    with connect(data_root) as connection:
        thread = connection.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        if thread is None:
            raise GmailAppValidationError(f"Thread `{thread_id}` was not found.")
        messages = connection.execute("SELECT * FROM messages WHERE thread_id = ? ORDER BY received_at ASC", (thread_id,)).fetchall()
    return {
        "id": thread["id"],
        "subject": thread["subject"],
        "participants": json_loads(thread["participants_json"]),
        "snippet": thread["snippet"],
        "updated_at": thread["updated_at"],
        "is_unread": bool(thread["is_unread"]),
        "labels": json_loads(thread["labels_json"]),
        "from_email": messages[-1]["from_email"] if messages else "",
        "to_emails": json_loads(messages[-1]["to_emails_json"]) if messages else [],
        "messages": [
            {
                "id": row["id"],
                "thread_id": row["thread_id"],
                "from_email": row["from_email"],
                "to_emails": json_loads(row["to_emails_json"]),
                "subject": row["subject"],
                "snippet": row["snippet"],
                "body_text": row["body_text"],
                "received_at": row["received_at"],
                "is_unread": bool(row["is_unread"]),
            }
            for row in messages
        ],
    }


def list_threads(
    data_root: Path,
    query: str = "",
    limit: int = 20,
    *,
    include_system_labels: bool = False,
    required_label: str = "",
    excluded_labels: list[str] | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    with connect(data_root) as connection:
        if query.strip():
            pattern = f"%{query.strip()}%"
            rows = connection.execute(
                """
                SELECT threads.*, latest.from_email AS latest_from_email, latest.to_emails_json AS latest_to_emails_json
                FROM threads
                LEFT JOIN messages AS latest
                  ON latest.id = (
                    SELECT id FROM messages
                    WHERE thread_id = threads.id
                    ORDER BY received_at DESC
                    LIMIT 1
                  )
                WHERE threads.subject LIKE ? OR threads.snippet LIKE ? OR threads.participants_json LIKE ?
                ORDER BY threads.updated_at DESC
                """,
                (pattern, pattern, pattern),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT threads.*, latest.from_email AS latest_from_email, latest.to_emails_json AS latest_to_emails_json
                FROM threads
                LEFT JOIN messages AS latest
                  ON latest.id = (
                    SELECT id FROM messages
                    WHERE thread_id = threads.id
                    ORDER BY received_at DESC
                    LIMIT 1
                  )
                ORDER BY threads.updated_at DESC
                """
            ).fetchall()
    results = []
    excluded = {str(label).upper() for label in excluded_labels or []}
    skipped = 0
    for row in rows:
        labels = json_loads(row["labels_json"])
        normalized_labels = {str(label).upper() for label in labels or []}
        if required_label and required_label.upper() not in normalized_labels:
            continue
        if excluded.intersection(normalized_labels):
            continue
        if not include_system_labels and has_excluded_system_label(labels):
            continue
        if skipped < offset:
            skipped += 1
            continue
        results.append(
            {
                "id": row["id"],
                "subject": row["subject"],
                "participants": json_loads(row["participants_json"]),
                "snippet": row["snippet"],
                "updated_at": row["updated_at"],
                "is_unread": bool(row["is_unread"]),
                "labels": labels,
                "from_email": row["latest_from_email"] or "",
                "to_emails": json_loads(row["latest_to_emails_json"]) if row["latest_to_emails_json"] else [],
            }
        )
        if len(results) >= limit:
            break
    return results


def mark_thread_read(data_root: Path, thread_id: str) -> dict[str, Any]:
    if not thread_id:
        raise GmailAppValidationError("thread_id is required.")
    with connect(data_root) as connection:
        row = connection.execute("SELECT id FROM threads WHERE id = ?", (thread_id,)).fetchone()
        if row is None:
            raise GmailAppValidationError(f"Thread `{thread_id}` was not found.")
        connection.execute("UPDATE threads SET is_unread = 0, last_reviewed_at = ? WHERE id = ?", (utc_now(), thread_id))
        connection.execute("UPDATE messages SET is_unread = 0 WHERE thread_id = ?", (thread_id,))
    record_audit(data_root, "gmail.thread_marked_read", subject_id=thread_id, payload={"cache_local": True})
    return get_thread(data_root, thread_id)


def create_suggestion(data_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    suggestion = {
        "id": payload.get("id") or f"suggestion_{uuid4().hex}",
        "thread_id": str(payload.get("thread_id") or ""),
        "kind": str(payload.get("kind") or "activity"),
        "title": str(payload.get("title") or "").strip(),
        "email": str(payload.get("email") or "").strip().lower(),
        "domain": str(payload.get("domain") or "").strip().lower(),
        "note": str(payload.get("note") or "").strip(),
        "status": str(payload.get("status") or "pending"),
        "created_at": utc_now(),
        "decided_at": "",
    }
    if not suggestion["thread_id"] or not suggestion["title"]:
        raise GmailAppValidationError("Suggestion requires thread_id and title.")
    with connect(data_root) as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO relationship_suggestions(id, thread_id, kind, title, email, domain, note, status, created_at, decided_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(suggestion[key] for key in ("id", "thread_id", "kind", "title", "email", "domain", "note", "status", "created_at", "decided_at")),
        )
    return suggestion


def list_suggestions(data_root: Path, status: str = "pending", limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    with connect(data_root) as connection:
        if status == "all":
            rows = connection.execute("SELECT * FROM relationship_suggestions ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = connection.execute("SELECT * FROM relationship_suggestions WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status, limit)).fetchall()
    return [dict(row) for row in rows]


def mark_suggestion_decision(data_root: Path, suggestion_id: str, decision: str, result: dict[str, Any] | None = None) -> dict[str, Any]:
    now = utc_now()
    with connect(data_root) as connection:
        row = connection.execute("SELECT id FROM relationship_suggestions WHERE id = ?", (suggestion_id,)).fetchone()
        if row is None:
            raise GmailAppValidationError(f"Suggestion `{suggestion_id}` was not found.")
        connection.execute("UPDATE relationship_suggestions SET status = ?, decided_at = ? WHERE id = ?", (decision, now, suggestion_id))
        decision_record = {"id": f"decision_{uuid4().hex}", "suggestion_id": suggestion_id, "decision": decision, "result": result or {}, "created_at": now}
        connection.execute(
            "INSERT INTO suggestion_decisions(id, suggestion_id, decision, result_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (decision_record["id"], suggestion_id, decision, json_dumps(decision_record["result"]), now),
        )
    record_audit(data_root, "gmail.relationship_suggestion_reviewed", subject_id=suggestion_id, payload={"decision": decision, "result": decision_record["result"]})
    return decision_record


def get_message(data_root: Path, message_id: str) -> dict[str, Any]:
    if not message_id:
        raise GmailAppValidationError("message_id is required.")
    with connect(data_root) as connection:
        row = connection.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    if row is None:
        raise GmailAppValidationError(f"Message `{message_id}` was not found.")
    return {
        "id": row["id"],
        "thread_id": row["thread_id"],
        "from_email": row["from_email"],
        "to_emails": json_loads(row["to_emails_json"]),
        "subject": row["subject"],
        "snippet": row["snippet"],
        "body_text": row["body_text"],
        "received_at": row["received_at"],
        "is_unread": bool(row["is_unread"]),
    }


def reference_search_threads(data_root: Path, query: str, limit: int = 10) -> list[dict[str, Any]]:
    return list_threads(data_root, query, limit)


def reference_search_messages(data_root: Path, query: str, limit: int = 10) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    pattern = f"%{query.strip()}%" if query.strip() else "%"
    with connect(data_root) as connection:
        rows = connection.execute(
            """
            SELECT id, thread_id, from_email, to_emails_json, subject, snippet, received_at
            FROM messages
            WHERE subject LIKE ? OR snippet LIKE ? OR from_email LIKE ? OR to_emails_json LIKE ?
            ORDER BY received_at DESC
            LIMIT ?
            """,
            (pattern, pattern, pattern, pattern, limit),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "thread_id": row["thread_id"],
            "from_email": row["from_email"],
            "to_emails": json_loads(row["to_emails_json"]),
            "subject": row["subject"],
            "snippet": row["snippet"],
            "received_at": row["received_at"],
        }
        for row in rows
    ]


def create_send_approval(data_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    to_emails = [str(item).strip().lower() for item in payload.get("to_emails", []) if str(item).strip()]
    subject = str(payload.get("subject") or "").strip()
    body_text = str(payload.get("body_text") or "").strip()
    if not to_emails or not subject or not body_text:
        raise GmailAppValidationError("Send approval requires to_emails, subject, and body_text.")
    now = utc_now()
    attachments = normalize_attachments(data_root, payload)
    approval = {
        "id": f"approval_{uuid4().hex}",
        "status": "approved",
        "to_emails": to_emails,
        "subject": subject,
        "body_text": body_text,
        "thread_id": str(payload.get("thread_id") or ""),
        "attachments": attachments,
        "confirmation_text": str(payload.get("confirmation_text") or "send this email"),
        "created_at": now,
        "approved_at": now,
        "consumed_at": "",
    }
    with connect(data_root) as connection:
        connection.execute(
            """
            INSERT INTO send_approvals(id, status, to_emails_json, subject, body_text, thread_id, attachments_json, confirmation_text, created_at, approved_at, consumed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (approval["id"], approval["status"], json_dumps(to_emails), subject, body_text, approval["thread_id"], json_dumps(attachments), approval["confirmation_text"], now, now, ""),
        )
    record_audit(
        data_root,
        "gmail.send_approved",
        subject_id=approval["id"],
        payload={"to_emails": to_emails, "subject": subject, "attachment_count": len(attachments)},
    )
    return approval


def consume_send_approval(data_root: Path, approval_id: str) -> dict[str, Any]:
    if not approval_id:
        raise GmailAppValidationError("approval_id is required.")
    now = utc_now()
    with connect(data_root) as connection:
        row = connection.execute("SELECT * FROM send_approvals WHERE id = ?", (approval_id,)).fetchone()
        if row is None:
            raise GmailAppValidationError(f"Approval `{approval_id}` was not found.")
        if row["status"] != "approved" or row["consumed_at"]:
            raise GmailAppValidationError("Approval is not available for sending.")
        connection.execute("UPDATE send_approvals SET status = ?, consumed_at = ? WHERE id = ?", ("consumed", now, approval_id))
    return {
        "id": row["id"],
        "to_emails": json_loads(row["to_emails_json"]),
        "subject": row["subject"],
        "body_text": row["body_text"],
        "thread_id": row["thread_id"],
        "attachments": json_loads(row["attachments_json"]) if "attachments_json" in row.keys() else [],
        "consumed_at": now,
    }


def record_sent_message(data_root: Path, approval_id: str, gmail_message_id: str, thread_id: str = "") -> dict[str, Any]:
    sent = {"id": f"sent_{uuid4().hex}", "approval_id": approval_id, "gmail_message_id": gmail_message_id, "thread_id": thread_id, "sent_at": utc_now()}
    with connect(data_root) as connection:
        connection.execute(
            "INSERT INTO sent_messages(id, approval_id, gmail_message_id, thread_id, sent_at) VALUES (?, ?, ?, ?, ?)",
            (sent["id"], approval_id, gmail_message_id, thread_id, sent["sent_at"]),
        )
    record_audit(data_root, "gmail.message_sent", subject_id=approval_id, payload=sent)
    return sent
