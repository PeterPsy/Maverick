"""SQLite store for Mail domain data."""

from __future__ import annotations

import json
from pathlib import Path
import re
from uuid import uuid4

from database import connect, ensure_schema, now_timestamp, seed_mock_data


def status(data_root: Path) -> dict[str, object]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        connection_count = db.execute("SELECT COUNT(*) AS count FROM connections").fetchone()["count"]
        active_connection_count = db.execute("SELECT COUNT(*) AS count FROM connections WHERE status != 'disconnected'").fetchone()["count"]
        unread_count = db.execute("SELECT COUNT(*) AS count FROM threads WHERE unread = 1").fetchone()["count"]
        draft_count = db.execute("SELECT COUNT(*) AS count FROM drafts WHERE status != 'sent'").fetchone()["count"]
    return {
        "app_id": "mail",
        "status": "ready",
        "mode": "not-connected" if active_connection_count == 0 else "provider-cache",
        "connection_count": connection_count,
        "active_connection_count": active_connection_count,
        "unread_count": unread_count,
        "draft_count": draft_count,
    }


def list_connections(data_root: Path) -> list[dict[str, object]]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        rows = db.execute("SELECT * FROM connections ORDER BY updated_at DESC").fetchall()
    return [_connection(row) for row in rows]


def get_connection(data_root: Path, connection_id: str) -> dict[str, object]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM connections WHERE id = ?", (connection_id,)).fetchone()
    if row is None:
        raise ValueError(f"Connection `{connection_id}` was not found")
    return _connection(row)


def bootstrap_mock_connection(data_root: Path) -> dict[str, object]:
    result = seed_mock_data(data_root)
    audit(data_root, "mock.bootstrap", "mail_connection", str(result["connection_id"]), {"created": bool(result["created"])})
    return result


def disconnect_connection(data_root: Path, connection_id: str, *, reason: str = "") -> dict[str, object]:
    ensure_schema(data_root)
    connection_id = connection_id.strip()
    if not connection_id:
        raise ValueError("connection_id is required")
    now = now_timestamp()
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM connections WHERE id = ?", (connection_id,)).fetchone()
        if row is None:
            raise ValueError(f"Connection `{connection_id}` was not found")
        previous_status = str(row["status"])
        db.execute("UPDATE connections SET status = ?, updated_at = ? WHERE id = ?", ("disconnected", now, connection_id))
        credential_rows = db.execute(
            "UPDATE oauth_credentials SET status = ?, updated_at = ? WHERE connection_id = ?",
            ("disconnected", now, connection_id),
        ).rowcount
        cache_counts = _connection_cache_counts(db, connection_id)
    detail = {
        "provider": str(row["provider"]),
        "previous_status": previous_status,
        "new_status": "disconnected",
        "oauth_credentials_disconnected": int(credential_rows),
        "cache_preserved": True,
        "thread_count": cache_counts["thread_count"],
        "message_count": cache_counts["message_count"],
        "attachment_count": cache_counts["attachment_count"],
        "draft_count": cache_counts["draft_count"],
        "core_secret_revocation": "not_supported_by_app_backend",
    }
    if reason:
        detail["reason"] = reason
    audit(data_root, "connections.disconnect", "mail_connection", connection_id, detail)
    return {
        "status": "disconnected",
        "connection": get_connection(data_root, connection_id),
        "previous_status": previous_status,
        "oauth_credentials_disconnected": int(credential_rows),
        "cache": cache_counts,
        "core_secret_revocation": {
            "status": "not_supported_by_app_backend",
            "detail": "Mail records the local disconnect and disables app-owned OAuth credential metadata; Core Secrets revocation must be performed through core secret/grant administration surfaces.",
        },
    }


def list_labels(data_root: Path, connection_id: str | None = None) -> list[dict[str, object]]:
    ensure_schema(data_root)
    sql = "SELECT * FROM labels"
    params: tuple[object, ...] = ()
    if connection_id:
        sql += " WHERE connection_id = ?"
        params = (connection_id,)
    sql += " ORDER BY canonical"
    with connect(data_root) as db:
        rows = db.execute(sql, params).fetchall()
    return [_row(row) for row in rows]


def list_folders(data_root: Path, connection_id: str | None = None) -> list[dict[str, object]]:
    ensure_schema(data_root)
    sql = "SELECT * FROM folders"
    params: tuple[object, ...] = ()
    if connection_id:
        sql += " WHERE connection_id = ?"
        params = (connection_id,)
    sql += " ORDER BY folder_type, name"
    with connect(data_root) as db:
        rows = db.execute(sql, params).fetchall()
    return [_row(row) for row in rows]


def list_threads(data_root: Path, payload: dict[str, object]) -> list[dict[str, object]]:
    ensure_schema(data_root)
    clauses, params = _thread_filter(payload)
    limit = _bounded_int(payload.get("max_threads") or payload.get("limit"), default=50, minimum=1, maximum=200)
    offset = _bounded_int(payload.get("offset"), default=0, minimum=0, maximum=100_000)
    with connect(data_root) as db:
        rows = db.execute(
            f"SELECT * FROM threads WHERE {' AND '.join(clauses)} ORDER BY last_message_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    return [_thread(row) for row in rows]


def count_threads(data_root: Path, payload: dict[str, object]) -> int:
    ensure_schema(data_root)
    clauses, params = _thread_filter(payload)
    with connect(data_root) as db:
        row = db.execute(f"SELECT COUNT(*) AS count FROM threads WHERE {' AND '.join(clauses)}", tuple(params)).fetchone()
    return int(row["count"])


def _thread_filter(payload: dict[str, object]) -> tuple[list[str], list[object]]:
    clauses = ["1 = 1"]
    params: list[object] = []
    connection_id = _optional_string(payload.get("connection_id"))
    label = _optional_string(payload.get("label") or payload.get("mailbox"))
    query = _optional_string(payload.get("query"))
    unread = payload.get("unread")
    if connection_id:
        clauses.append("connection_id = ?")
        params.append(connection_id)
    if label:
        clauses.append("labels_json LIKE ?")
        params.append(f'%"{label}"%')
    if query:
        clauses.append("(subject LIKE ? OR snippet LIKE ?)")
        params.extend([f"%{query}%", f"%{query}%"])
    if isinstance(unread, bool):
        clauses.append("unread = ?")
        params.append(1 if unread else 0)
    return clauses, params


def get_thread(data_root: Path, thread_id: str, max_body_chars: int = 8000) -> dict[str, object]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        thread_row = db.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        if thread_row is None:
            thread_row = _legacy_gmail_thread_row(db, thread_id)
        if thread_row is None:
            raise ValueError(f"Thread `{thread_id}` was not found")
        message_rows = db.execute("SELECT * FROM messages WHERE thread_id = ? ORDER BY sent_at", (thread_row["id"],)).fetchall()
    thread = _thread(thread_row)
    thread["messages"] = [_message(row, max_body_chars=max_body_chars) for row in message_rows]
    return thread


def get_message(data_root: Path, message_id: str, max_body_chars: int = 8000) -> dict[str, object]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        if row is None:
            row = _legacy_gmail_message_row(db, message_id)
    if row is None:
        raise ValueError(f"Message `{message_id}` was not found")
    return _message(row, max_body_chars=max_body_chars)


def search_messages(data_root: Path, query: str, limit: int = 25) -> list[dict[str, object]]:
    ensure_schema(data_root)
    needle = f"%{query.strip()}%"
    with connect(data_root) as db:
        rows = db.execute(
            """
            SELECT messages.*, threads.subject
            FROM messages JOIN threads ON messages.thread_id = threads.id
            WHERE messages.body_text LIKE ? OR threads.subject LIKE ?
            ORDER BY messages.sent_at DESC
            LIMIT ?
            """,
            (needle, needle, _bounded_int(limit, default=25, minimum=1, maximum=100)),
        ).fetchall()
    return [_message(row, max_body_chars=1200) for row in rows]


def modify_labels(data_root: Path, thread_id: str, add: object = None, remove: object = None) -> dict[str, object]:
    thread = get_thread(data_root, thread_id)
    resolved_thread_id = str(thread["id"])
    labels = set(thread["labels"])
    labels.update(_as_string_list(add))
    labels.difference_update(_as_string_list(remove))
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute("UPDATE threads SET labels_json = ?, updated_at = ? WHERE id = ?", (json.dumps(sorted(labels)), now, resolved_thread_id))
    audit(data_root, "labels.modify", "email_thread", resolved_thread_id, {"add": _as_string_list(add), "remove": _as_string_list(remove)})
    return get_thread(data_root, resolved_thread_id)


def mark_read(data_root: Path, thread_id: str, read: bool = True) -> dict[str, object]:
    thread = get_thread(data_root, thread_id)
    resolved_thread_id = str(thread["id"])
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute("UPDATE threads SET unread = ?, updated_at = ? WHERE id = ?", (0 if read else 1, now, resolved_thread_id))
    audit(data_root, "thread.mark_read", "email_thread", resolved_thread_id, {"read": read})
    return get_thread(data_root, resolved_thread_id)


def sync_threads(data_root: Path, connection_id: str | None = None) -> dict[str, object]:
    ensure_schema(data_root)
    try:
        connection_id = connection_id or _default_connection_id(data_root)
    except ValueError:
        return {"connection_id": "", "synced_at": "", "mode": "no_connection", "status": "skipped"}
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute(
            """
            INSERT OR REPLACE INTO sync_state(
                connection_id,
                last_sync_at,
                last_error,
                cursor,
                last_full_sync_at,
                last_incremental_sync_at,
                provider_history_id
            )
            VALUES (?, ?, ?, ?, COALESCE((SELECT last_full_sync_at FROM sync_state WHERE connection_id = ?), ?), ?, ?)
            """,
            (connection_id, now, "", f"manual-{now}", connection_id, now, now, f"manual-history-{now}"),
        )
    audit(data_root, "threads.sync", "mail_connection", connection_id, {"mode": "manual-mock"})
    return {"connection_id": connection_id, "synced_at": now, "mode": "manual-mock"}


def get_attachment(data_root: Path, attachment_id: str) -> dict[str, object]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute(
            """
            SELECT attachments.*, messages.thread_id
            FROM attachments JOIN messages ON attachments.message_id = messages.id
            WHERE attachments.id = ?
            """,
            (attachment_id,),
        ).fetchone()
        if row is None:
            row = _legacy_gmail_attachment_row(db, attachment_id)
    if row is None:
        raise ValueError(f"Attachment `{attachment_id}` was not found")
    item = _row(row)
    item["storage_ref"] = _loads_object(item.pop("storage_ref_json"))
    item["deep_link"] = f"/app/mail?attachment={item['id']}"
    return item


def audit(data_root: Path, action: str, target_type: str, target_id: str, detail: dict[str, object]) -> None:
    ensure_schema(data_root)
    with connect(data_root) as db:
        db.execute(
            "INSERT INTO audit_log(id, action, target_type, target_id, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (f"audit_{uuid4().hex[:16]}", action, target_type, target_id, json.dumps(detail, ensure_ascii=True), now_timestamp()),
        )


def _connection_cache_counts(db, connection_id: str) -> dict[str, int]:
    thread_count = int(db.execute("SELECT COUNT(*) AS count FROM threads WHERE connection_id = ?", (connection_id,)).fetchone()["count"])
    message_count = int(
        db.execute(
            """
            SELECT COUNT(*) AS count
            FROM messages JOIN threads ON messages.thread_id = threads.id
            WHERE threads.connection_id = ?
            """,
            (connection_id,),
        ).fetchone()["count"]
    )
    attachment_count = int(
        db.execute(
            """
            SELECT COUNT(*) AS count
            FROM attachments JOIN messages ON attachments.message_id = messages.id
            JOIN threads ON messages.thread_id = threads.id
            WHERE threads.connection_id = ?
            """,
            (connection_id,),
        ).fetchone()["count"]
    )
    draft_count = int(db.execute("SELECT COUNT(*) AS count FROM drafts WHERE connection_id = ?", (connection_id,)).fetchone()["count"])
    return {
        "thread_count": thread_count,
        "message_count": message_count,
        "attachment_count": attachment_count,
        "draft_count": draft_count,
    }


def _connection(row) -> dict[str, object]:
    item = _row(row)
    item["scopes"] = _loads_list(item.pop("scopes_json"))
    return item


def _thread(row) -> dict[str, object]:
    item = _row(row)
    item["participants"] = _loads_list(item.pop("participants_json"))
    item["labels"] = _loads_list(item.pop("labels_json"))
    item["unread"] = bool(item["unread"])
    item["starred"] = bool(item["starred"])
    item["deep_link"] = f"/app/mail?thread={item['id']}"
    return item


def _message(row, max_body_chars: int) -> dict[str, object]:
    item = _row(row)
    item["sender"] = _loads_object(item.pop("sender_json"))
    item["recipients"] = _loads_list(item.pop("recipients_json"))
    item["cc"] = _loads_list(item.pop("cc_json", "[]"))
    item["bcc"] = _loads_list(item.pop("bcc_json", "[]"))
    item["headers"] = _loads_object(item.pop("headers_json"))
    item["has_attachments"] = bool(item["has_attachments"])
    item["body_text"] = str(item["body_text"])[:max_body_chars]
    item["deep_link"] = f"/app/mail?message={item['id']}"
    return item


def _row(row) -> dict[str, object]:
    return dict(row)


def _loads_list(value: object) -> list[object]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _loads_object(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _as_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value in (None, ""):
        return []
    return [str(value).strip()]


def _optional_string(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _default_connection_id(data_root: Path) -> str:
    connections = list_connections(data_root)
    if not connections:
        raise ValueError("No mail connection is available")
    return str(connections[0]["id"])


def _legacy_gmail_thread_row(db, thread_id: str):
    if not thread_id.startswith("email_thread_gmail_"):
        return None
    legacy_suffix = thread_id.removeprefix("email_thread_gmail_")
    rows = db.execute(
        """
        SELECT threads.*
        FROM threads JOIN connections ON threads.connection_id = connections.id
        WHERE connections.provider = 'gmail'
        """
    ).fetchall()
    matches = [row for row in rows if _safe_id(row["provider_thread_id"]) == legacy_suffix]
    return matches[0] if len(matches) == 1 else None


def _legacy_gmail_message_row(db, message_id: str):
    if not message_id.startswith("email_message_gmail_"):
        return None
    legacy_suffix = message_id.removeprefix("email_message_gmail_")
    rows = db.execute(
        """
        SELECT messages.*
        FROM messages JOIN threads ON messages.thread_id = threads.id
        JOIN connections ON threads.connection_id = connections.id
        WHERE connections.provider = 'gmail'
        """
    ).fetchall()
    matches = [row for row in rows if _safe_id(row["provider_message_id"]) == legacy_suffix]
    return matches[0] if len(matches) == 1 else None


def _legacy_gmail_attachment_row(db, attachment_id: str):
    if not attachment_id.startswith("mail_attachment_gmail_"):
        return None
    rows = db.execute(
        """
        SELECT attachments.*, messages.thread_id, messages.provider_message_id
        FROM attachments JOIN messages ON attachments.message_id = messages.id
        JOIN threads ON messages.thread_id = threads.id
        JOIN connections ON threads.connection_id = connections.id
        WHERE connections.provider = 'gmail'
        """
    ).fetchall()
    matches = [
        row
        for row in rows
        if _legacy_gmail_attachment_id(row["provider_message_id"], row["provider_attachment_id"]) == attachment_id
    ]
    return matches[0] if len(matches) == 1 else None


def _legacy_gmail_attachment_id(provider_message_id: object, provider_attachment_id: object) -> str:
    return f"mail_attachment_gmail_{_safe_id(provider_message_id)}_{_safe_id(provider_attachment_id)}"


def _safe_id(value: object) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", str(value)).strip("_").lower() or ""
