"""SQLite store for Mail domain data."""

from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import unquote
from uuid import uuid4

from database import connect, ensure_schema, now_timestamp
from email_rendering import BODY_SOURCE_LIMIT, truncate_sanitized_html


DEFAULT_BODY_TEXT_CHARS = 8_000
DEFAULT_BODY_HTML_CHARS = BODY_SOURCE_LIMIT
MAILBOX_SCOPE_PREFIX = "connection:"
AGGREGATE_MAILBOX_SCOPE_PREFIX = "all:"
MAILBOX_SCOPE_LABELS = {"inbox", "sent", "drafts", "starred", "trash"}


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


def resolve_connected_connection(data_root: Path, connection_id: str) -> dict[str, object]:
    connection = get_connection(data_root, connection_id)
    if connection.get("status") == "connected":
        return connection
    replacement = connected_replacement_for_connection(data_root, connection)
    return replacement or connection


def connected_replacement_for_connection(data_root: Path, connection: dict[str, object]) -> dict[str, object] | None:
    provider = str(connection.get("provider") or "").strip()
    email_key = str(connection.get("email_address") or "").strip().casefold()
    if not provider or not email_key:
        return None
    candidates = [
        item
        for item in list_connections(data_root)
        if item.get("id") != connection.get("id")
        and item.get("status") == "connected"
        and str(item.get("provider") or "") == provider
        and str(item.get("email_address") or "").strip().casefold() == email_key
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)[0]


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


def delete_disconnected_connection(data_root: Path, connection_id: str) -> dict[str, object]:
    ensure_schema(data_root)
    connection_id = connection_id.strip()
    if not connection_id:
        raise ValueError("connection_id is required")
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM connections WHERE id = ?", (connection_id,)).fetchone()
        if row is None:
            raise ValueError(f"Connection `{connection_id}` was not found")
        if str(row["status"]) != "disconnected":
            raise ValueError(f"Connection `{connection_id}` must be disconnected before removal")
        cache_counts = _connection_cache_counts(db, connection_id)
        folder_count = int(db.execute("SELECT COUNT(*) AS count FROM folders WHERE connection_id = ?", (connection_id,)).fetchone()["count"])
        label_count = int(db.execute("SELECT COUNT(*) AS count FROM labels WHERE connection_id = ?", (connection_id,)).fetchone()["count"])
        sync_state_count = int(db.execute("SELECT COUNT(*) AS count FROM sync_state WHERE connection_id = ?", (connection_id,)).fetchone()["count"])
        oauth_credential_count = int(db.execute("SELECT COUNT(*) AS count FROM oauth_credentials WHERE connection_id = ?", (connection_id,)).fetchone()["count"])
        provider_credential_count = int(db.execute("SELECT COUNT(*) AS count FROM provider_credentials WHERE connection_id = ?", (connection_id,)).fetchone()["count"])
        entity_link_count = _delete_entity_links_for_connection(db, connection_id)
        attachment_rows = db.execute(
            """
            DELETE FROM attachments
            WHERE message_id IN (
              SELECT messages.id
              FROM messages JOIN threads ON messages.thread_id = threads.id
              WHERE threads.connection_id = ?
            )
            """,
            (connection_id,),
        ).rowcount
        message_rows = db.execute(
            "DELETE FROM messages WHERE thread_id IN (SELECT id FROM threads WHERE connection_id = ?)",
            (connection_id,),
        ).rowcount
        thread_rows = db.execute("DELETE FROM threads WHERE connection_id = ?", (connection_id,)).rowcount
        db.execute("DELETE FROM send_confirmations WHERE draft_id IN (SELECT id FROM drafts WHERE connection_id = ?)", (connection_id,))
        draft_rows = db.execute("DELETE FROM drafts WHERE connection_id = ?", (connection_id,)).rowcount
        folder_rows = db.execute("DELETE FROM folders WHERE connection_id = ?", (connection_id,)).rowcount
        label_rows = db.execute("DELETE FROM labels WHERE connection_id = ?", (connection_id,)).rowcount
        sync_state_rows = db.execute("DELETE FROM sync_state WHERE connection_id = ?", (connection_id,)).rowcount
        oauth_credential_rows = db.execute("DELETE FROM oauth_credentials WHERE connection_id = ?", (connection_id,)).rowcount
        provider_credential_rows = db.execute("DELETE FROM provider_credentials WHERE connection_id = ?", (connection_id,)).rowcount
        connection_rows = db.execute("DELETE FROM connections WHERE id = ?", (connection_id,)).rowcount
    deleted = {
        "connection_count": int(connection_rows),
        "thread_count": int(thread_rows),
        "message_count": int(message_rows),
        "attachment_count": int(attachment_rows),
        "draft_count": int(draft_rows),
        "folder_count": int(folder_rows),
        "label_count": int(label_rows),
        "sync_state_count": int(sync_state_rows),
        "oauth_credential_count": int(oauth_credential_rows),
        "provider_credential_count": int(provider_credential_rows),
        "entity_link_count": int(entity_link_count),
    }
    expected = {
        **cache_counts,
        "folder_count": folder_count,
        "label_count": label_count,
        "sync_state_count": sync_state_count,
        "oauth_credential_count": oauth_credential_count,
        "provider_credential_count": provider_credential_count,
        "entity_link_count": int(entity_link_count),
    }
    audit(
        data_root,
        "connections.delete",
        "mail_connection",
        connection_id,
        {
            "provider": str(row["provider"]),
            "email_address": str(row["email_address"]),
            "previous_status": str(row["status"]),
            "deleted": deleted,
        },
    )
    return {
        "status": "deleted",
        "connection_id": connection_id,
        "email_address": str(row["email_address"]),
        "display_name": str(row["display_name"]),
        "cache": cache_counts,
        "expected": expected,
        "deleted": deleted,
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


def mailbox_counts(data_root: Path) -> dict[str, dict[str, dict[str, int]]]:
    ensure_schema(data_root)
    mailboxes = ("inbox", "sent", "drafts", "starred", "trash")
    with connect(data_root) as db:
        connection_rows = db.execute("SELECT id FROM connections").fetchall()
        result: dict[str, dict[str, dict[str, int]]] = {}
        for row in connection_rows:
            connection_id = str(row["id"])
            result[connection_id] = {}
            for mailbox in mailboxes:
                pattern = f'%"{mailbox}"%'
                count_row = db.execute(
                    """
                    SELECT
                      COUNT(*) AS total_count,
                      COALESCE(SUM(CASE WHEN unread = 1 THEN 1 ELSE 0 END), 0) AS unread_count
                    FROM threads
                    WHERE connection_id = ? AND labels_json LIKE ?
                    """,
                    (connection_id, pattern),
                ).fetchone()
                result[connection_id][mailbox] = {
                    "total": int(count_row["total_count"]),
                    "unread": int(count_row["unread_count"]),
                }
    return result


def _thread_filter(payload: dict[str, object]) -> tuple[list[str], list[object]]:
    clauses = ["1 = 1"]
    params: list[object] = []
    if "mailbox_scopes" in payload:
        scope_clauses, scope_params = _mailbox_scope_clauses(payload.get("mailbox_scopes"))
        if scope_clauses:
            clauses.append(f"({' OR '.join(scope_clauses)})")
            params.extend(scope_params)
        else:
            clauses.append("0 = 1")
    else:
        connection_id = _optional_string(payload.get("connection_id"))
        label = _optional_string(payload.get("label") or payload.get("mailbox"))
        if connection_id:
            clauses.append("connection_id = ?")
            params.append(connection_id)
        if label:
            clauses.append("labels_json LIKE ?")
            params.append(f'%"{label}"%')
    query = _optional_string(payload.get("query"))
    unread = payload.get("unread")
    if query:
        clauses.append(
            """
            (
              subject LIKE ?
              OR snippet LIKE ?
              OR EXISTS (
                SELECT 1 FROM messages
                WHERE messages.thread_id = threads.id
                  AND (
                    messages.body_text LIKE ?
                    OR messages.body_html_sanitized LIKE ?
                    OR messages.body_html_gmail_sanitized LIKE ?
                    OR messages.body_html_rendered LIKE ?
                    OR messages.sender_json LIKE ?
                    OR messages.recipients_json LIKE ?
                  )
              )
              OR EXISTS (
                SELECT 1 FROM attachments JOIN messages ON attachments.message_id = messages.id
                WHERE messages.thread_id = threads.id AND attachments.filename LIKE ?
              )
            )
            """
        )
        params.extend([f"%{query}%"] * 9)
    if isinstance(unread, bool):
        clauses.append("unread = ?")
        params.append(1 if unread else 0)
    return clauses, params


def _mailbox_scope_clauses(value: object) -> tuple[list[str], list[object]]:
    scopes = _mailbox_scopes(value)
    aggregate_mailboxes = {mailbox for connection_id, mailbox in scopes if connection_id is None}
    clauses: list[str] = []
    params: list[object] = []
    for connection_id, mailbox in scopes:
        if connection_id and mailbox in aggregate_mailboxes:
            continue
        label_pattern = f'%"{mailbox}"%'
        if connection_id:
            clauses.append("(connection_id = ? AND labels_json LIKE ?)")
            params.extend([connection_id, label_pattern])
        else:
            clauses.append("labels_json LIKE ?")
            params.append(label_pattern)
    return clauses, params


def _mailbox_scopes(value: object) -> list[tuple[str | None, str]]:
    raw_scopes: list[object]
    if isinstance(value, list):
        raw_scopes = value
    else:
        raw_scopes = [scope.strip() for scope in str(value or "").split(",") if scope.strip()]
    scopes: list[tuple[str | None, str]] = []
    seen: set[tuple[str | None, str]] = set()
    for raw_scope in raw_scopes:
        scope = _mailbox_scope(raw_scope)
        if scope is None or scope in seen:
            continue
        seen.add(scope)
        scopes.append(scope)
    return scopes


def _mailbox_scope(value: object) -> tuple[str | None, str] | None:
    if isinstance(value, dict):
        mailbox = _optional_string(value.get("mailbox"))
        connection_id = _optional_string(value.get("connection_id"))
        return (connection_id, mailbox) if mailbox in MAILBOX_SCOPE_LABELS else None
    scope_id = _optional_string(value)
    if not scope_id:
        return None
    if scope_id.startswith(AGGREGATE_MAILBOX_SCOPE_PREFIX):
        mailbox = scope_id.removeprefix(AGGREGATE_MAILBOX_SCOPE_PREFIX)
        return (None, mailbox) if mailbox in MAILBOX_SCOPE_LABELS else None
    if not scope_id.startswith(MAILBOX_SCOPE_PREFIX):
        return None
    scoped = scope_id.removeprefix(MAILBOX_SCOPE_PREFIX)
    mailbox_separator = scoped.rfind(":")
    if mailbox_separator <= 0:
        return None
    mailbox = scoped[mailbox_separator + 1 :]
    if mailbox not in MAILBOX_SCOPE_LABELS:
        return None
    connection_id = unquote(scoped[:mailbox_separator]).strip()
    return (connection_id, mailbox) if connection_id else None


def get_thread(
    data_root: Path,
    thread_id: str,
    max_body_chars: int = DEFAULT_BODY_TEXT_CHARS,
    max_body_html_chars: int | None = None,
) -> dict[str, object]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        thread_row = db.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        if thread_row is None:
            thread_row = _legacy_gmail_thread_row(db, thread_id)
        if thread_row is None:
            raise ValueError(f"Thread `{thread_id}` was not found")
        message_rows = db.execute("SELECT * FROM messages WHERE thread_id = ? ORDER BY sent_at", (thread_row["id"],)).fetchall()
        attachments = _attachments_for_messages(db, [str(row["id"]) for row in message_rows])
    thread = _thread(thread_row)
    thread["messages"] = [
        _message(
            row,
            max_body_chars=max_body_chars,
            max_body_html_chars=max_body_html_chars,
            attachments=attachments.get(str(row["id"]), []),
        )
        for row in message_rows
    ]
    return thread


def get_message(
    data_root: Path,
    message_id: str,
    max_body_chars: int = DEFAULT_BODY_TEXT_CHARS,
    max_body_html_chars: int | None = None,
) -> dict[str, object]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        if row is None:
            row = _legacy_gmail_message_row(db, message_id)
        attachments = _attachments_for_messages(db, [str(row["id"])]) if row is not None else {}
    if row is None:
        raise ValueError(f"Message `{message_id}` was not found")
    return _message(
        row,
        max_body_chars=max_body_chars,
        max_body_html_chars=max_body_html_chars,
        attachments=attachments.get(str(row["id"]), []),
    )


def search_messages(data_root: Path, query: str, limit: int = 25) -> list[dict[str, object]]:
    ensure_schema(data_root)
    needle = f"%{query.strip()}%"
    with connect(data_root) as db:
        rows = db.execute(
            """
            SELECT messages.*, threads.subject
            FROM messages JOIN threads ON messages.thread_id = threads.id
            WHERE messages.body_text LIKE ?
              OR messages.body_html_sanitized LIKE ?
              OR messages.body_html_gmail_sanitized LIKE ?
              OR messages.body_html_rendered LIKE ?
              OR messages.sender_json LIKE ?
              OR messages.recipients_json LIKE ?
              OR threads.subject LIKE ?
              OR EXISTS (
                SELECT 1 FROM attachments
                WHERE attachments.message_id = messages.id AND attachments.filename LIKE ?
              )
            ORDER BY messages.sent_at DESC
            LIMIT ?
            """,
            (needle, needle, needle, needle, needle, needle, needle, needle, _bounded_int(limit, default=25, minimum=1, maximum=100)),
        ).fetchall()
        attachments = _attachments_for_messages(db, [str(row["id"]) for row in rows])
    return [_message(row, max_body_chars=1200, attachments=attachments.get(str(row["id"]), [])) for row in rows]


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


def _delete_entity_links_for_connection(db, connection_id: str) -> int:
    return int(
        db.execute(
            """
            DELETE FROM entity_links
            WHERE (source_entity_type = 'mail_connection' AND source_entity_id = ?)
              OR (target_app_id = 'mail' AND target_entity_type = 'mail_connection' AND target_entity_id = ?)
              OR (source_entity_type = 'email_thread' AND source_entity_id IN (
                SELECT id FROM threads WHERE connection_id = ?
              ))
              OR (target_app_id = 'mail' AND target_entity_type = 'email_thread' AND target_entity_id IN (
                SELECT id FROM threads WHERE connection_id = ?
              ))
              OR (source_entity_type = 'email_message' AND source_entity_id IN (
                SELECT messages.id
                FROM messages JOIN threads ON messages.thread_id = threads.id
                WHERE threads.connection_id = ?
              ))
              OR (target_app_id = 'mail' AND target_entity_type = 'email_message' AND target_entity_id IN (
                SELECT messages.id
                FROM messages JOIN threads ON messages.thread_id = threads.id
                WHERE threads.connection_id = ?
              ))
              OR (source_entity_type = 'mail_attachment' AND source_entity_id IN (
                SELECT attachments.id
                FROM attachments JOIN messages ON attachments.message_id = messages.id
                JOIN threads ON messages.thread_id = threads.id
                WHERE threads.connection_id = ?
              ))
              OR (target_app_id = 'mail' AND target_entity_type = 'mail_attachment' AND target_entity_id IN (
                SELECT attachments.id
                FROM attachments JOIN messages ON attachments.message_id = messages.id
                JOIN threads ON messages.thread_id = threads.id
                WHERE threads.connection_id = ?
              ))
              OR (source_entity_type = 'mail_draft' AND source_entity_id IN (
                SELECT id FROM drafts WHERE connection_id = ?
              ))
              OR (target_app_id = 'mail' AND target_entity_type = 'mail_draft' AND target_entity_id IN (
                SELECT id FROM drafts WHERE connection_id = ?
              ))
            """,
            (
                connection_id,
                connection_id,
                connection_id,
                connection_id,
                connection_id,
                connection_id,
                connection_id,
                connection_id,
                connection_id,
                connection_id,
            ),
        ).rowcount
    )


def _connection(row) -> dict[str, object]:
    item = _row(row)
    item["scopes"] = _loads_list(item.pop("scopes_json"))
    item["settings"] = _loads_object(item.pop("settings_json", "{}"))
    return item


def _thread(row) -> dict[str, object]:
    item = _row(row)
    item["participants"] = _loads_list(item.pop("participants_json"))
    item["labels"] = _loads_list(item.pop("labels_json"))
    item["unread"] = bool(item["unread"])
    item["starred"] = bool(item["starred"])
    item["deep_link"] = f"/app/mail?thread={item['id']}"
    return item


def _message(
    row,
    max_body_chars: int,
    max_body_html_chars: int | None = None,
    attachments: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    item = _row(row)
    item["sender"] = _loads_object(item.pop("sender_json"))
    item["recipients"] = _loads_list(item.pop("recipients_json"))
    item["cc"] = _loads_list(item.pop("cc_json", "[]"))
    item["bcc"] = _loads_list(item.pop("bcc_json", "[]"))
    item["headers"] = _loads_object(item.pop("headers_json"))
    item["has_attachments"] = bool(item["has_attachments"])
    body_text = str(item["body_text"])
    original_html = str(item.pop("body_html_original_bounded", "") or "")
    gmail_sanitized_html = str(item.get("body_html_gmail_sanitized") or "")
    rendered_html = str(item.get("body_html_rendered") or "")
    legacy_html = str(item.get("body_html_sanitized") or "")
    if not gmail_sanitized_html:
        gmail_sanitized_html = legacy_html
    if not rendered_html:
        rendered_html = gmail_sanitized_html or legacy_html
    html_limit = max_body_html_chars if max_body_html_chars is not None else max_body_chars
    source_truncated = bool(item.get("body_truncated"))
    text_truncated = len(body_text) > max_body_chars
    rendered_html_truncated = len(rendered_html) > html_limit
    gmail_html_truncated = len(gmail_sanitized_html) > html_limit
    item["body_text"] = body_text[:max_body_chars]
    item["body_html_sanitized"] = truncate_sanitized_html(rendered_html, html_limit)
    item["body_html_gmail_sanitized"] = truncate_sanitized_html(gmail_sanitized_html, html_limit)
    item["body_html_rendered"] = truncate_sanitized_html(rendered_html, html_limit)
    item["body_html_original_available"] = bool(original_html)
    item["body_html_original_size"] = len(original_html)
    item["render_policy"] = _loads_object(item.pop("render_policy_json", "{}"))
    item["body_render_mode"] = str(item.get("body_render_mode") or ("html" if rendered_html else "plain"))
    item["body_preview"] = str(item.get("body_preview") or body_text[:180])
    item["body_source_truncated"] = source_truncated
    item["body_text_truncated"] = text_truncated
    item["body_html_truncated"] = rendered_html_truncated or gmail_html_truncated
    item["body_truncated"] = source_truncated or text_truncated or bool(item["body_html_truncated"])
    item["parts"] = _loads_list(item.pop("parts_json", "[]"))
    item["inline_assets"] = _loads_list(item.pop("inline_assets_json", "[]"))
    item["attachments"] = attachments or []
    item["deep_link"] = f"/app/mail?message={item['id']}"
    return item


def _attachments_for_messages(db, message_ids: list[str]) -> dict[str, list[dict[str, object]]]:
    if not message_ids:
        return {}
    placeholders = ",".join("?" for _ in message_ids)
    rows = db.execute(
        f"SELECT * FROM attachments WHERE message_id IN ({placeholders}) ORDER BY filename, id",
        tuple(message_ids),
    ).fetchall()
    result: dict[str, list[dict[str, object]]] = {message_id: [] for message_id in message_ids}
    for row in rows:
        item = _row(row)
        item["storage_ref"] = _loads_object(item.pop("storage_ref_json"))
        item["deep_link"] = f"/app/mail?attachment={item['id']}"
        result.setdefault(str(item["message_id"]), []).append(item)
    return result


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


def _optional_string(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


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
