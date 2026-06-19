"""IMAP/SMTP provider for password-backed private mailboxes."""

from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate, getaddresses, parsedate_to_datetime
import hashlib
import imaplib
import json
from pathlib import Path
import re
import smtplib
from uuid import uuid4

from connections import IMAP_PASSWORD_SECRET, MAILBOX_PASSWORD_SECRET, SMTP_PASSWORD_SECRET
from database import connect, ensure_schema, now_timestamp
from drafts import get_draft
from email_rendering import render_email_body
from store import audit, get_attachment, get_thread, list_threads
from storage_attachments import (
    attach_workspace_attachments,
    draft_confirmation_preview,
    draft_with_current_attachments,
    require_confirmation_token,
    save_attachment_to_storage,
)

from .base import ProviderCapability


ImapFactory = Callable[[dict[str, object]], object]
SmtpFactory = Callable[[dict[str, object]], object]


class ImapSmtpProvider:
    provider_id = "imap_smtp"

    def __init__(self, imap_factory: ImapFactory | None = None, smtp_factory: SmtpFactory | None = None) -> None:
        self._imap_factory = imap_factory or _open_imap
        self._smtp_factory = smtp_factory or _open_smtp

    def capabilities(self) -> list[ProviderCapability]:
        return [
            ProviderCapability("imap_sync", True, "Syncs mailbox folders over IMAP with UID cursors."),
            ProviderCapability("smtp_send", True, "Sends drafts over authenticated SMTP."),
            ProviderCapability("vault_password", True, "Consumes mailbox-password through resource-scoped Core Secrets grants."),
        ]

    def list_threads(self, data_root: Path, payload: dict[str, object]) -> list[dict[str, object]]:
        return list_threads(data_root, payload)

    def get_thread(
        self,
        data_root: Path,
        thread_id: str,
        max_body_chars: int = 8000,
        max_body_html_chars: int | None = None,
        app_secrets: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return get_thread(data_root, thread_id, max_body_chars=max_body_chars, max_body_html_chars=max_body_html_chars)

    def test_connection(self, data_root: Path, connection_id: str, app_secrets: dict[str, object] | None = None) -> dict[str, object]:
        ensure_schema(data_root)
        settings = _connection_settings(data_root, connection_id)
        imap_password = _imap_password(app_secrets)
        smtp_password = _smtp_password(app_secrets)
        folders: list[dict[str, str]] = []
        try:
            with self._imap(settings) as client:
                _imap_login(client, str(settings["username"]), imap_password)
                folders = _list_folders(client)
        except Exception:
            return {
                "ok": False,
                "imap": "failed",
                "smtp": "not_tested",
                "detail": "IMAP authentication or connection failed.",
                "folders": [],
            }
        try:
            with self._smtp(settings) as client:
                client.login(str(settings["username"]), smtp_password)
        except Exception:
            return {
                "ok": False,
                "imap": "ok",
                "smtp": "failed",
                "detail": "SMTP authentication or connection failed.",
                "folders": folders[:25],
            }
        return {"ok": True, "imap": "ok", "smtp": "ok", "folders": folders[:25]}

    def sync_incremental(
        self,
        data_root: Path,
        connection_id: str | None = None,
        app_secrets: dict[str, object] | None = None,
        max_threads: int = 100,
        query: str | None = None,
        page_token: str | None = None,
        continue_cursor: bool = False,
        persist_cursor: bool = True,
    ) -> dict[str, object]:
        ensure_schema(data_root)
        connection_id = _required_string(connection_id, "connection_id")
        settings = _connection_settings(data_root, connection_id)
        password = _imap_password(app_secrets)
        cursor = _load_cursor(data_root, connection_id)
        synced = 0
        max_total = _bounded_int(max_threads, 100, 1, 2000)
        folder_rows: list[dict[str, str]] = []
        folder_cursors = cursor.get("folders") if continue_cursor and isinstance(cursor.get("folders"), dict) else {}
        with self._imap(settings) as client:
            _imap_login(client, str(settings["username"]), password)
            folders = _list_folders(client)
            folder_rows = folders
            _cache_folders(data_root, connection_id, folders)
            for folder in folders:
                if synced >= max_total:
                    break
                folder_name = folder["name"]
                typ, _ = client.select(f'"{folder_name}"', readonly=True)
                if str(typ).upper() != "OK":
                    continue
                uidvalidity = _uidvalidity(client)
                previous = folder_cursors.get(folder_name) if isinstance(folder_cursors, dict) else {}
                last_uid = int(previous.get("last_uid") or 0) if isinstance(previous, dict) and previous.get("uidvalidity") == uidvalidity else 0
                search_args = ("UID", f"{last_uid + 1}:*") if last_uid else ("ALL",)
                typ, data = client.uid("SEARCH", None, *search_args)
                if str(typ).upper() != "OK":
                    continue
                uids = _uid_values(data)
                if query:
                    uids = uids[-max_total:]
                for uid in uids[-(max_total - synced) :]:
                    raw, flags = _fetch_message(client, uid)
                    if raw is None:
                        continue
                    _cache_message(data_root, connection_id, folder, uid, uidvalidity, raw, flags=flags)
                    synced += 1
                    folder_cursors[folder_name] = {"uidvalidity": uidvalidity, "last_uid": max(uid, last_uid)}
        now = now_timestamp()
        cursor["folders"] = folder_cursors
        with connect(data_root) as db:
            db.execute(
                """
                INSERT INTO sync_state(connection_id, last_sync_at, last_error, cursor, last_full_sync_at, last_incremental_sync_at, provider_history_id)
                VALUES (?, ?, ?, ?, COALESCE((SELECT last_full_sync_at FROM sync_state WHERE connection_id = ?), ?), ?, ?)
                ON CONFLICT(connection_id) DO UPDATE SET
                  last_sync_at = excluded.last_sync_at,
                  last_error = '',
                  cursor = excluded.cursor,
                  last_incremental_sync_at = excluded.last_incremental_sync_at,
                  provider_history_id = excluded.provider_history_id
                """,
                (connection_id, now, "", json.dumps(cursor, ensure_ascii=True, sort_keys=True), connection_id, now, now, ""),
            )
        audit(data_root, "imap_smtp.sync", "mail_connection", connection_id, {"synced_messages": synced, "folders": len(folder_rows)})
        return {
            "connection_id": connection_id,
            "synced_at": now,
            "synced_threads": synced,
            "synced_messages": synced,
            "has_more": False,
            "mode": "imap_smtp",
        }

    def send_draft(
        self,
        data_root: Path,
        draft_id: str,
        confirm: bool = False,
        app_secrets: dict[str, object] | None = None,
        uploaded_storage_root: Path | None = None,
        generated_storage_root: Path | None = None,
        confirmation_token: object = None,
    ) -> dict[str, object]:
        draft = get_draft(data_root, draft_id)
        _require_recipients(draft)
        settings = _connection_settings(data_root, str(draft["connection_id"]))
        message, attachments = _draft_message(
            draft,
            sender_email=str(settings["email_address"]),
            sender_name=str(settings.get("display_name") or ""),
            uploaded_storage_root=uploaded_storage_root,
            generated_storage_root=generated_storage_root,
        )
        preview_draft = draft_with_current_attachments(draft, attachments)
        confirmation_preview = draft_confirmation_preview(
            preview_draft,
            sender_email=str(settings["email_address"]),
            sender_name=str(settings.get("display_name") or ""),
            attachments=attachments,
        )
        if not confirm:
            return {
                "dry_run": True,
                "requires_confirmation": True,
                "draft": preview_draft,
                "confirmation_preview": confirmation_preview,
            }
        require_confirmation_token(preview=confirmation_preview, confirmation_token=confirmation_token)
        with self._smtp(settings) as client:
            client.login(str(settings["username"]), _smtp_password(app_secrets))
            client.send_message(message)
        _append_sent_copy(settings, self._imap_factory, _imap_password(app_secrets), message)
        now = now_timestamp()
        with connect(data_root) as db:
            db.execute("UPDATE drafts SET status = 'sent', dirty = 0, sent_at = ?, updated_at = ? WHERE id = ?", (now, now, draft_id))
        _cache_message(
            data_root,
            str(draft["connection_id"]),
            {"name": str(settings.get("sent_folder") or "Sent"), "canonical": "sent", "type": "sent"},
            _synthetic_uid(),
            "",
            message.as_bytes(),
            flags={"\\Seen"},
        )
        audit(data_root, "imap_smtp.draft.send", "mail_draft", draft_id, {"provider": "smtp"})
        return {
            "sent": True,
            "provider_message_id": str(message["Message-ID"] or ""),
            "thread_id": str(draft.get("thread_id") or ""),
            "attachments": attachments,
        }

    def mark_read(
        self,
        data_root: Path,
        thread_id: str,
        read: bool = True,
        app_secrets: dict[str, object] | None = None,
    ) -> dict[str, object]:
        thread = get_thread(data_root, thread_id, max_body_chars=200)
        settings = _connection_settings(data_root, str(thread["connection_id"]))
        password = _imap_password(app_secrets)
        with self._imap(settings) as client:
            _imap_login(client, str(settings["username"]), password)
            for message in thread.get("messages", []):
                folder, uid = _message_location(message)
                if folder and uid:
                    client.select(f'"{folder}"', readonly=False)
                    client.uid("STORE", str(uid), "+FLAGS.SILENT" if read else "-FLAGS.SILENT", r"(\Seen)")
        with connect(data_root) as db:
            db.execute("UPDATE threads SET unread = ?, updated_at = ? WHERE id = ?", (0 if read else 1, now_timestamp(), thread_id))
        audit(data_root, "imap_smtp.mark_read", "email_thread", thread_id, {"read": read})
        return get_thread(data_root, thread_id)

    def modify_labels(
        self,
        data_root: Path,
        thread_id: str,
        add: object = None,
        remove: object = None,
        app_secrets: dict[str, object] | None = None,
    ) -> dict[str, object]:
        thread = get_thread(data_root, thread_id, max_body_chars=200)
        add_values = set(_string_list(add))
        remove_values = set(_string_list(remove))
        if "trash" not in add_values:
            raise ValueError("IMAP/SMTP label changes are limited to moving messages to trash; archive and custom labels are not supported.")
        settings = _connection_settings(data_root, str(thread["connection_id"]))
        password = _imap_password(app_secrets)
        with self._imap(settings) as client:
            _imap_login(client, str(settings["username"]), password)
            folders = _list_folders(client)
            target_folder = _folder_by_canonical(folders, "trash")
            if not target_folder:
                raise ValueError("IMAP trash folder was not found for this mailbox")
            for message in thread.get("messages", []):
                folder, uid = _message_location(message)
                if folder and uid:
                    _move_message(client, folder, uid, target_folder["name"])
        labels = set(str(item).lower() for item in thread.get("labels", []))
        labels.update(add_values)
        labels.difference_update(remove_values)
        with connect(data_root) as db:
            db.execute(
                "UPDATE threads SET labels_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(sorted(labels), ensure_ascii=True), now_timestamp(), thread_id),
            )
        audit(data_root, "imap_smtp.labels.modify", "email_thread", thread_id, {"add": sorted(add_values), "remove": sorted(remove_values), "provider_action": "move_to_trash"})
        return get_thread(data_root, thread_id)

    def fetch_attachment(
        self,
        data_root: Path,
        attachment_id: str,
        app_secrets: dict[str, object] | None = None,
        metadata_only: bool = True,
        max_bytes: int | None = None,
        save_to_storage: bool = False,
        generated_storage_root: Path | None = None,
        storage_target_folder: object = None,
        storage_mode: object = "versioned",
        skip_sha256s: set[str] | None = None,
    ) -> dict[str, object]:
        attachment = get_attachment(data_root, attachment_id)
        metadata = {
            "attachment_id": attachment_id,
            "status": "metadata_only",
            "filename": attachment["filename"],
            "content_type": attachment.get("content_type") or "",
            "size_bytes": int(attachment.get("size_bytes") or 0),
            "storage_state": attachment.get("storage_state") or "metadata_only",
            "storage_ref": attachment.get("storage_ref") or {},
        }
        if metadata_only:
            return metadata
        if max_bytes is None:
            return {**metadata, "status": "limit_required", "detail": "Attachment bytes require an explicit max_bytes limit."}
        folder, uid, part_index = _attachment_location(str(attachment.get("provider_attachment_id") or ""))
        if not folder or not uid:
            return {**metadata, "status": "invalid_payload", "detail": "Attachment location metadata is unavailable."}
        thread = get_thread(data_root, str(attachment["thread_id"]), max_body_chars=200)
        settings = _connection_settings(data_root, str(thread["connection_id"]))
        with self._imap(settings) as client:
            _imap_login(client, str(settings["username"]), _imap_password(app_secrets))
            client.select(f'"{folder}"', readonly=True)
            raw = _fetch_message_bytes(client, uid)
        if raw is None:
            return {**metadata, "status": "invalid_payload", "detail": "Provider message was not found."}
        message = BytesParser(policy=policy.default).parsebytes(raw)
        payload = _attachment_bytes(message, part_index)
        if payload is None:
            return {**metadata, "status": "invalid_payload", "detail": "Provider attachment was not found."}
        if len(payload) > max_bytes:
            return {**metadata, "status": "too_large", "size_bytes": len(payload), "max_bytes": max_bytes}
        sha256 = hashlib.sha256(payload).hexdigest()
        if save_to_storage and skip_sha256s and sha256 in skip_sha256s:
            return {**metadata, "status": "duplicate_sha256", "size_bytes": len(payload), "sha256": sha256}
        data_base64url = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
        if save_to_storage:
            storage_ref = _save_attachment(
                data_root,
                attachment_id,
                str(attachment["filename"]),
                str(attachment.get("content_type") or "application/octet-stream"),
                payload,
                generated_storage_root,
                target_folder=storage_target_folder,
                mode=storage_mode,
            )
            return {
                **metadata,
                "status": "saved",
                "size_bytes": len(payload),
                "sha256": sha256,
                "storage_state": "saved",
                "storage_ref": storage_ref,
            }
        return {**metadata, "status": "fetched", "size_bytes": len(payload), "data_base64url": data_base64url}

    def _imap(self, settings: dict[str, object]):
        return _ClientContext(self._imap_factory(settings))

    def _smtp(self, settings: dict[str, object]):
        return _ClientContext(self._smtp_factory(settings))


class _ClientContext:
    def __init__(self, client: object) -> None:
        self.client = client

    def __enter__(self):
        return self.client

    def __exit__(self, exc_type, exc, tb) -> None:
        for method_name in ("quit", "logout", "close"):
            method = getattr(self.client, method_name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass
                return


def _open_imap(settings: dict[str, object]):
    host = str(settings["imap_host"])
    port = int(settings["imap_port"])
    security = str(settings.get("imap_security") or "ssl")
    if security == "ssl":
        return imaplib.IMAP4_SSL(host, port, timeout=30)
    client = imaplib.IMAP4(host, port, timeout=30)
    if security == "starttls":
        client.starttls()
    return client


def _open_smtp(settings: dict[str, object]):
    host = str(settings["smtp_host"])
    port = int(settings["smtp_port"])
    security = str(settings.get("smtp_security") or "ssl")
    if security == "ssl":
        return smtplib.SMTP_SSL(host, port, timeout=30)
    client = smtplib.SMTP(host, port, timeout=30)
    client.ehlo()
    if security == "starttls":
        client.starttls()
        client.ehlo()
    return client


def _imap_login(client: object, username: str, password: str) -> None:
    typ, _ = client.login(username, password)
    if str(typ).upper() != "OK":
        raise ValueError("IMAP authentication failed")


def _connection_settings(data_root: Path, connection_id: str) -> dict[str, object]:
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM connections WHERE id = ?", (connection_id,)).fetchone()
    if row is None:
        raise ValueError(f"Connection `{connection_id}` was not found")
    if row["provider"] != "imap_smtp":
        raise ValueError(f"Connection `{connection_id}` is not an IMAP/SMTP connection")
    try:
        settings = json.loads(str(row["settings_json"] or "{}"))
    except json.JSONDecodeError:
        settings = {}
    if not isinstance(settings, dict):
        settings = {}
    settings.setdefault("email_address", row["email_address"])
    settings.setdefault("display_name", row["display_name"])
    settings.setdefault("username", row["email_address"])
    return settings


def _list_folders(client: object) -> list[dict[str, str]]:
    typ, rows = client.list()
    if str(typ).upper() != "OK":
        return [{"name": "INBOX", "canonical": "inbox", "type": "inbox"}]
    folders: list[dict[str, str]] = []
    for row in rows or []:
        text = row.decode("utf-8", errors="replace") if isinstance(row, bytes) else str(row)
        name = text.rsplit(' "/" ', 1)[-1].strip().strip('"') if ' "/" ' in text else text.rsplit(" ", 1)[-1].strip().strip('"')
        if not name:
            continue
        folders.append({"name": name, "canonical": _folder_canonical(name), "type": _folder_type(name)})
    if not any(item["canonical"] == "inbox" for item in folders):
        folders.insert(0, {"name": "INBOX", "canonical": "inbox", "type": "inbox"})
    return folders


def _cache_folders(data_root: Path, connection_id: str, folders: list[dict[str, str]]) -> None:
    now = now_timestamp()
    with connect(data_root) as db:
        for folder in folders:
            db.execute(
                """
                INSERT INTO folders(id, connection_id, provider_folder_id, name, canonical, folder_type, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(connection_id, canonical) DO UPDATE SET
                  provider_folder_id = excluded.provider_folder_id,
                  name = excluded.name,
                  folder_type = excluded.folder_type,
                  updated_at = excluded.updated_at
                """,
                (
                    f"mail_folder_{_safe_id(connection_id)}_{_safe_id(folder['canonical'])}",
                    connection_id,
                    folder["name"],
                    folder["name"],
                    folder["canonical"],
                    folder["type"],
                    now,
                    now,
                ),
            )


def _fetch_message(client: object, uid: int | str) -> tuple[bytes | None, set[str]]:
    typ, data = client.uid("FETCH", str(uid), "(RFC822 FLAGS)")
    if str(typ).upper() != "OK":
        return None, set()
    flags = _fetch_flags(data)
    for item in data or []:
        if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], bytes):
            return item[1], flags
    return None, flags


def _fetch_message_bytes(client: object, uid: int | str) -> bytes | None:
    raw, _flags = _fetch_message(client, uid)
    return raw


def _fetch_flags(data: object) -> set[str]:
    chunks: list[str] = []
    for item in data or []:
        source = item[0] if isinstance(item, tuple) and item else item
        chunks.append(source.decode("utf-8", errors="ignore") if isinstance(source, bytes) else str(source))
    match = re.search(r"FLAGS\s+\(([^)]*)\)", " ".join(chunks), flags=re.IGNORECASE)
    if not match:
        return set()
    return {value.strip() for value in match.group(1).split() if value.strip()}


def _cache_message(
    data_root: Path,
    connection_id: str,
    folder: dict[str, str],
    uid: int | str,
    uidvalidity: str,
    raw_message: bytes,
    flags: set[str] | None = None,
) -> None:
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    parsed = _parse_message(message, flags=flags)
    provider_message_id = f"{folder['name']}:{uidvalidity}:{uid}"
    thread_key = _thread_key(message, parsed["subject"])
    thread_id = f"email_thread_imap_{_safe_id(connection_id)}_{_safe_id(thread_key)}"
    message_id = f"email_message_imap_{_safe_id(connection_id)}_{_safe_id(provider_message_id)}"
    labels = sorted(set([folder["canonical"], folder["type"], *parsed["labels"]]))
    last_message_at = str(parsed["sent_at"])
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO threads(id, connection_id, provider_thread_id, subject, participants_json, last_message_at, snippet, unread, starred, labels_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              subject = excluded.subject,
              participants_json = excluded.participants_json,
              last_message_at = CASE WHEN excluded.last_message_at > threads.last_message_at THEN excluded.last_message_at ELSE threads.last_message_at END,
              snippet = excluded.snippet,
              unread = excluded.unread,
              starred = CASE WHEN excluded.starred = 1 THEN 1 ELSE threads.starred END,
              labels_json = excluded.labels_json,
              updated_at = excluded.updated_at
            """,
            (
                thread_id,
                connection_id,
                thread_key,
                parsed["subject"],
                json.dumps(parsed["participants"], ensure_ascii=True),
                last_message_at,
                parsed["body_preview"],
                1 if "unread" in parsed["labels"] else 0,
                1 if "starred" in parsed["labels"] else 0,
                json.dumps(labels, ensure_ascii=True),
                now,
            ),
        )
        db.execute(
            """
            INSERT INTO messages(
              id, thread_id, provider_message_id, sender_json, recipients_json, cc_json, bcc_json,
              sent_at, body_text, body_html_sanitized, body_html_original_bounded,
              body_html_gmail_sanitized, body_html_rendered, render_policy_json,
              body_render_mode, body_preview, body_truncated,
              parts_json, inline_assets_json, headers_json, has_attachments
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              sender_json = excluded.sender_json,
              recipients_json = excluded.recipients_json,
              cc_json = excluded.cc_json,
              bcc_json = excluded.bcc_json,
              sent_at = excluded.sent_at,
              body_text = excluded.body_text,
              body_html_sanitized = excluded.body_html_sanitized,
              body_html_original_bounded = excluded.body_html_original_bounded,
              body_html_gmail_sanitized = excluded.body_html_gmail_sanitized,
              body_html_rendered = excluded.body_html_rendered,
              render_policy_json = excluded.render_policy_json,
              body_render_mode = excluded.body_render_mode,
              body_preview = excluded.body_preview,
              body_truncated = excluded.body_truncated,
              parts_json = excluded.parts_json,
              inline_assets_json = excluded.inline_assets_json,
              headers_json = excluded.headers_json,
              has_attachments = excluded.has_attachments
            """,
            (
                message_id,
                thread_id,
                provider_message_id,
                json.dumps(parsed["sender"], ensure_ascii=True),
                json.dumps(parsed["recipients"], ensure_ascii=True),
                json.dumps(parsed["cc"], ensure_ascii=True),
                json.dumps(parsed["bcc"], ensure_ascii=True),
                parsed["sent_at"],
                parsed["body_text"],
                parsed["body_html_sanitized"],
                parsed["body_html_original_bounded"],
                parsed["body_html_gmail_sanitized"],
                parsed["body_html_rendered"],
                json.dumps(parsed["render_policy"], ensure_ascii=True, sort_keys=True),
                parsed["body_render_mode"],
                parsed["body_preview"],
                1 if parsed["body_truncated"] else 0,
                json.dumps(parsed["parts"], ensure_ascii=True),
                json.dumps(parsed["inline_assets"], ensure_ascii=True),
                json.dumps(parsed["headers"], ensure_ascii=True),
                1 if parsed["attachments"] else 0,
            ),
        )
        for attachment in parsed["attachments"]:
            attachment_id = f"mail_attachment_imap_{_safe_id(connection_id)}_{_safe_id(provider_message_id)}_{attachment['part_index']}"
            db.execute(
                """
                INSERT INTO attachments(id, message_id, provider_attachment_id, filename, content_type, size_bytes, storage_state, storage_ref_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'metadata_only', '{}', ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  filename = excluded.filename,
                  content_type = excluded.content_type,
                  size_bytes = excluded.size_bytes,
                  updated_at = excluded.updated_at
                """,
                (
                    attachment_id,
                    message_id,
                    f"{folder['name']}|{uid}|{attachment['part_index']}",
                    attachment["filename"],
                    attachment["content_type"],
                    attachment["size_bytes"],
                    now,
                    now,
                ),
            )


def _parse_message(message: EmailMessage, *, flags: set[str] | None = None) -> dict[str, object]:
    headers = {key.lower(): str(value) for key, value in message.items()}
    plain_chunks: list[str] = []
    html_chunks: list[str] = []
    parts: list[dict[str, object]] = []
    inline_assets: list[dict[str, object]] = []
    attachments: list[dict[str, object]] = []
    for index, part in enumerate(message.walk()):
        content_type = part.get_content_type()
        disposition = str(part.get_content_disposition() or "")
        filename = str(part.get_filename() or "")
        content_id = str(part.get("Content-ID") or "").strip("<>")
        payload = part.get_payload(decode=True) or b""
        if part.is_multipart():
            continue
        if disposition == "attachment" or filename:
            attachments.append(
                {
                    "part_index": index,
                    "filename": filename or f"attachment-{index}",
                    "content_type": content_type,
                    "size_bytes": len(payload),
                }
            )
            continue
        if content_id and content_type.startswith("image/"):
            inline_assets.append(
                {
                    "content_id": content_id,
                    "provider_attachment_id": str(index),
                    "filename": filename,
                    "content_type": content_type,
                    "size_bytes": len(payload),
                }
            )
        if content_type == "text/plain":
            plain_chunks.append(_part_text(part, payload))
        elif content_type == "text/html":
            html_chunks.append(_part_text(part, payload))
        if content_type.startswith("text/") or content_id:
            parts.append(
                {
                    "mime_type": content_type,
                    "filename": filename,
                    "content_id": content_id,
                    "provider_attachment_id": str(index) if content_id else "",
                    "size_bytes": len(payload),
                    "disposition": disposition,
                }
            )
    rendered = render_email_body(plain_chunks, html_chunks)
    labels = []
    flag_values = flags if flags is not None else set(str(message.get("X-Maverick-Flags") or "").split())
    if "\\Seen" not in flag_values:
        labels.append("unread")
    return {
        "subject": str(message.get("Subject") or "(no subject)"),
        "sender": _first_address(str(message.get("From") or "")),
        "recipients": _addresses(str(message.get("To") or "")),
        "cc": _addresses(str(message.get("Cc") or "")),
        "bcc": _addresses(str(message.get("Bcc") or "")),
        "participants": _participants(message),
        "sent_at": _sent_at(str(message.get("Date") or "")),
        "headers": headers,
        "labels": labels,
        "attachments": attachments,
        "body_text": rendered.body_text,
        "body_html_sanitized": rendered.body_html_sanitized,
        "body_html_original_bounded": rendered.body_html_original_bounded,
        "body_html_gmail_sanitized": rendered.body_html_gmail_sanitized,
        "body_html_rendered": rendered.body_html_rendered,
        "render_policy": rendered.render_policy,
        "body_render_mode": rendered.body_render_mode,
        "body_preview": rendered.body_preview,
        "body_truncated": rendered.body_truncated,
        "parts": parts,
        "inline_assets": inline_assets,
    }


def _draft_message(
    draft: dict[str, object],
    *,
    sender_email: str,
    sender_name: str,
    uploaded_storage_root: Path | None = None,
    generated_storage_root: Path | None = None,
) -> tuple[EmailMessage, list[dict[str, object]]]:
    message = EmailMessage()
    message["From"] = f"{sender_name} <{sender_email}>" if sender_name else sender_email
    message["To"] = ", ".join(_format_address(item) for item in draft.get("to", []))
    if draft.get("cc"):
        message["Cc"] = ", ".join(_format_address(item) for item in draft.get("cc", []))
    if draft.get("bcc"):
        message["Bcc"] = ", ".join(_format_address(item) for item in draft.get("bcc", []))
    if draft.get("reply_to"):
        message["Reply-To"] = ", ".join(_format_address(item) for item in draft.get("reply_to", []))
    message["Subject"] = str(draft.get("subject") or "")
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = f"<{uuid4().hex}@maverick.mail>"
    message.set_content(str(draft.get("body_text") or ""))
    body_html = str(draft.get("body_html") or "")
    if body_html:
        message.add_alternative(body_html, subtype="html")
    attachments = attach_workspace_attachments(
        message,
        draft,
        uploaded_root=uploaded_storage_root,
        generated_root=generated_storage_root,
    )
    return message, attachments


def _append_sent_copy(settings: dict[str, object], imap_factory: ImapFactory, password: str, message: EmailMessage) -> None:
    try:
        with _ClientContext(imap_factory(settings)) as client:
            _imap_login(client, str(settings["username"]), password)
            client.append(str(settings.get("sent_folder") or "Sent"), "\\Seen", None, message.as_bytes())
    except Exception:
        return


def _uidvalidity(client: object) -> str:
    try:
        typ, rows = client.response("UIDVALIDITY")
        if str(typ).upper() == "OK" and rows:
            return str(rows[0].decode("ascii") if isinstance(rows[0], bytes) else rows[0])
    except Exception:
        pass
    return ""


def _uid_values(data: object) -> list[int]:
    chunks: list[str] = []
    for item in data or []:
        chunks.append(item.decode("ascii", errors="ignore") if isinstance(item, bytes) else str(item))
    return sorted({int(value) for value in " ".join(chunks).split() if value.isdigit()})


def _load_cursor(data_root: Path, connection_id: str) -> dict[str, object]:
    with connect(data_root) as db:
        row = db.execute("SELECT cursor FROM sync_state WHERE connection_id = ?", (connection_id,)).fetchone()
    if row is None:
        return {"version": 1, "folders": {}}
    try:
        parsed = json.loads(str(row["cursor"] or "{}"))
    except json.JSONDecodeError:
        return {"version": 1, "folders": {}}
    return parsed if isinstance(parsed, dict) else {"version": 1, "folders": {}}


def _imap_password(app_secrets: dict[str, object] | None) -> str:
    secrets = app_secrets if isinstance(app_secrets, dict) else {}
    return _required_secret(secrets, IMAP_PASSWORD_SECRET, fallback=MAILBOX_PASSWORD_SECRET)


def _smtp_password(app_secrets: dict[str, object] | None) -> str:
    secrets = app_secrets if isinstance(app_secrets, dict) else {}
    return _required_secret(secrets, SMTP_PASSWORD_SECRET, fallback=MAILBOX_PASSWORD_SECRET)


def _required_secret(secrets: dict[str, object], logical_name: str, *, fallback: str | None = None) -> str:
    value = secrets.get(logical_name)
    if (value in (None, "")) and fallback:
        value = secrets.get(fallback)
    text = str(value or "")
    if not text:
        names = f"{logical_name}` or `{fallback}" if fallback else logical_name
        raise ValueError(f"Core Secrets did not deliver `{names}`")
    return text


def _require_recipients(draft: dict[str, object]) -> None:
    if not any(item.get("email") for key in ("to", "cc", "bcc") for item in draft.get(key, [])):
        raise ValueError("At least one recipient in to, cc, or bcc is required")


def _message_location(message: object) -> tuple[str, int | None]:
    if not isinstance(message, dict):
        return "", None
    provider_message_id = str(message.get("provider_message_id") or "")
    parts = provider_message_id.split(":")
    if len(parts) < 3:
        return "", None
    try:
        return parts[0], int(parts[-1])
    except ValueError:
        return parts[0], None


def _attachment_location(value: str) -> tuple[str, int | None, int]:
    parts = value.split("|")
    if len(parts) != 3:
        return "", None, -1
    try:
        return parts[0], int(parts[1]), int(parts[2])
    except ValueError:
        return parts[0], None, -1


def _attachment_bytes(message: EmailMessage, part_index: int) -> bytes | None:
    for index, part in enumerate(message.walk()):
        if index == part_index:
            return part.get_payload(decode=True) or b""
    return None


def _save_attachment(
    data_root: Path,
    attachment_id: str,
    filename: str,
    content_type: str,
    payload: bytes,
    generated_storage_root: Path | None,
    *,
    target_folder: object = None,
    mode: object = "versioned",
) -> dict[str, object]:
    return save_attachment_to_storage(
        data_root,
        attachment_id=attachment_id,
        filename=filename,
        content_type=content_type,
        attachment_bytes=payload,
        generated_storage_root=generated_storage_root,
        target_folder=target_folder,
        mode=mode,
    )


def _thread_key(message: EmailMessage, subject: object) -> str:
    for header in ("References", "In-Reply-To", "Message-ID"):
        value = str(message.get(header) or "").strip()
        if value:
            return value.split()[0].strip("<>")
    return _normal_subject(str(subject or "no-subject"))


def _normal_subject(value: str) -> str:
    text = re.sub(r"^\s*(re|fwd?):\s*", "", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip().lower() or "no-subject"


def _part_text(part: EmailMessage, payload: bytes) -> str:
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _sent_at(value: str) -> str:
    if value:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC).isoformat()
        except (TypeError, ValueError):
            pass
    return now_timestamp()


def _participants(message: EmailMessage) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for address in [*_addresses(str(message.get("From") or "")), *_addresses(str(message.get("To") or "")), *_addresses(str(message.get("Cc") or ""))]:
        email = address.get("email", "").lower()
        if email and email not in seen:
            seen.add(email)
            result.append(address)
    return result


def _first_address(value: str) -> dict[str, str]:
    addresses = _addresses(value)
    return addresses[0] if addresses else {}


def _addresses(value: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for name, email in getaddresses([value]):
        if email:
            item = {"email": email}
            if name:
                item["name"] = name
            result.append(item)
    return result


def _format_address(value: object) -> str:
    if isinstance(value, dict):
        email = str(value.get("email") or "")
        name = str(value.get("name") or "")
        return f"{name} <{email}>" if name else email
    return str(value or "")


def _string_list(value: object) -> list[str]:
    values = value if isinstance(value, list) else [value] if value else []
    return [str(item).strip().lower() for item in values if str(item).strip()]


def _folder_by_canonical(folders: list[dict[str, str]], canonical: str) -> dict[str, str] | None:
    return next((folder for folder in folders if folder.get("canonical") == canonical), None)


def _move_message(client: object, source_folder: str, uid: int, target_folder: str) -> None:
    client.select(f'"{source_folder}"', readonly=False)
    typ, _data = client.uid("MOVE", str(uid), f'"{target_folder}"')
    if str(typ).upper() == "OK":
        return
    copy_typ, _copy_data = client.uid("COPY", str(uid), f'"{target_folder}"')
    if str(copy_typ).upper() != "OK":
        raise ValueError("IMAP server rejected the move-to-trash operation")
    client.uid("STORE", str(uid), "+FLAGS.SILENT", r"(\Deleted)")
    expunge = getattr(client, "expunge", None)
    if callable(expunge):
        expunge()


def _folder_canonical(name: str) -> str:
    value = name.strip().lower()
    if value == "inbox":
        return "inbox"
    if "sent" in value:
        return "sent"
    if "draft" in value:
        return "drafts"
    if "trash" in value or "deleted" in value:
        return "trash"
    if "spam" in value or "junk" in value:
        return "spam"
    return _safe_id(value)


def _folder_type(name: str) -> str:
    canonical = _folder_canonical(name)
    return canonical if canonical in {"inbox", "sent", "drafts", "trash", "spam"} else "folder"


def _safe_id(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_") or "item"


def _synthetic_uid() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def _required_string(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))
