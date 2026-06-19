"""Gmail provider implementation for OAuth-backed Mail connections."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from database import connect, ensure_schema, now_timestamp
from email_rendering import render_email_body
from drafts import get_draft
from store import audit, get_attachment, get_thread, list_threads
from storage_attachments import (
    attach_workspace_attachments,
    draft_confirmation_preview,
    draft_with_current_attachments,
    require_confirmation_token,
    save_attachment_to_storage,
)

from .base import ProviderCapability


GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]
GMAIL_REFRESH_TOKEN_SECRET = "gmail-refresh-token"
GMAIL_CLIENT_ID_SECRET = "gmail-oauth-client-id"
GMAIL_CLIENT_SECRET_SECRET = "gmail-oauth-client-secret"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GMAIL_API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_THREAD_PAGE_SIZE = 100

HttpTransport = Callable[[Request], dict[str, object]]


class GmailProvider:
    provider_id = "gmail"
    authorization_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"

    def __init__(self, transport: HttpTransport | None = None) -> None:
        self._transport = transport or _urlopen_json

    def capabilities(self) -> list[ProviderCapability]:
        return [
            ProviderCapability("oauth_authorization_url", True, "Builds a Google authorization URL when a client id is granted."),
            ProviderCapability("oauth_code_exchange", True, "Exchanges OAuth codes and stores refresh tokens through Core Secrets."),
            ProviderCapability("gmail_api_sync", True, "Uses Gmail REST APIs with per-connection refresh-token grants."),
        ]

    def authorization_url(self, *, client_id: str, redirect_uri: str, state: str) -> str:
        query = urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(GMAIL_SCOPES),
                "state": state,
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
            }
        )
        return f"{self.authorization_endpoint}?{query}"

    def fetch_profile(self, *, access_token: str) -> dict[str, object]:
        return self._gmail_json("GET", "profile", access_token=access_token)

    def list_threads(self, data_root: Path, payload: dict[str, object]) -> list[dict[str, object]]:
        connection_id = _optional_string(payload.get("connection_id"))
        if connection_id and _as_secret_map(payload).get(GMAIL_REFRESH_TOKEN_SECRET):
            self.sync_incremental(
                data_root,
                connection_id,
                app_secrets=_as_secret_map(payload),
                max_threads=_bounded_int(payload.get("max_threads") or payload.get("limit"), 50, 1, 100),
                query=str(payload.get("sync_query") or "newer_than:30d"),
                persist_cursor=False,
            )
        return list_threads(data_root, payload)

    def get_thread(
        self,
        data_root: Path,
        thread_id: str,
        max_body_chars: int = 8000,
        max_body_html_chars: int | None = None,
        app_secrets: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if app_secrets and app_secrets.get(GMAIL_REFRESH_TOKEN_SECRET):
            thread = get_thread(
                data_root,
                thread_id,
                max_body_chars=max_body_chars,
                max_body_html_chars=max_body_html_chars,
            )
            self._fetch_and_cache_thread(data_root, str(thread["connection_id"]), str(thread["provider_thread_id"]), app_secrets)
        return get_thread(
            data_root,
            thread_id,
            max_body_chars=max_body_chars,
            max_body_html_chars=max_body_html_chars,
        )

    def modify_labels(
        self,
        data_root: Path,
        thread_id: str,
        add: object = None,
        remove: object = None,
        app_secrets: dict[str, object] | None = None,
    ) -> dict[str, object]:
        secrets = _require_app_secrets(app_secrets)
        thread = get_thread(data_root, thread_id)
        resolved_thread_id = str(thread["id"])
        access_token = self._access_token(secrets)
        provider_thread_id = str(thread["provider_thread_id"])
        self._gmail_json(
            "POST",
            f"threads/{provider_thread_id}/modify",
            access_token=access_token,
            payload={"addLabelIds": _gmail_labels(add), "removeLabelIds": _gmail_labels(remove)},
        )
        self._fetch_and_cache_thread(data_root, str(thread["connection_id"]), provider_thread_id, secrets)
        audit(data_root, "gmail.labels.modify", "email_thread", resolved_thread_id, {"add": _string_list(add), "remove": _string_list(remove)})
        return get_thread(data_root, resolved_thread_id)

    def mark_read(
        self,
        data_root: Path,
        thread_id: str,
        read: bool = True,
        app_secrets: dict[str, object] | None = None,
    ) -> dict[str, object]:
        add = [] if read else ["UNREAD"]
        remove = ["UNREAD"] if read else []
        return self.modify_labels(data_root, thread_id, add=add, remove=remove, app_secrets=app_secrets)

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
        connection = _connection(data_root, str(draft["connection_id"]))
        message, attachments = _draft_message(
            draft,
            sender_email=str(connection["email_address"]),
            sender_name=str(connection["display_name"]),
            uploaded_storage_root=uploaded_storage_root,
            generated_storage_root=generated_storage_root,
        )
        preview_draft = draft_with_current_attachments(draft, attachments)
        confirmation_preview = draft_confirmation_preview(
            preview_draft,
            sender_email=str(connection["email_address"]),
            sender_name=str(connection["display_name"]),
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
        secrets = _require_app_secrets(app_secrets)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
        payload: dict[str, object] = {"raw": raw}
        if draft.get("thread_id"):
            thread = get_thread(data_root, str(draft["thread_id"]), max_body_chars=200)
            payload["threadId"] = thread["provider_thread_id"]
        sent = self._gmail_json("POST", "messages/send", access_token=self._access_token(secrets), payload=payload)
        provider_thread_id = str(sent.get("threadId") or "")
        now = now_timestamp()
        with connect(data_root) as db:
            db.execute("UPDATE drafts SET status = 'sent', dirty = 0, sent_at = ?, updated_at = ? WHERE id = ?", (now, now, draft_id))
        if provider_thread_id:
            self._fetch_and_cache_thread(data_root, str(draft["connection_id"]), provider_thread_id, secrets)
        audit(data_root, "gmail.draft.send", "mail_draft", draft_id, {"provider_message_id": str(sent.get("id") or "")})
        local_thread_id = _local_thread_id(str(draft["connection_id"]), provider_thread_id) if provider_thread_id else str(draft.get("thread_id") or "")
        return {"sent": True, "provider_message_id": str(sent.get("id") or ""), "thread_id": local_thread_id, "attachments": attachments}

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
        secrets = _require_app_secrets(app_secrets)
        access_token = self._access_token(secrets)
        max_total = _bounded_int(max_threads, 100, 1, 2000)
        query_text = str(query or "").strip()
        synced = 0
        next_page_token = str(page_token or "").strip()
        if continue_cursor and not next_page_token:
            next_page_token = _sync_cursor(data_root, connection_id)
        response: dict[str, object] = {}
        while synced < max_total:
            page_size = min(GMAIL_THREAD_PAGE_SIZE, max_total - synced)
            params: dict[str, object] = {"maxResults": page_size}
            if query_text:
                params["q"] = query_text
            if next_page_token:
                params["pageToken"] = next_page_token
            response = self._gmail_json("GET", f"threads?{urlencode(params)}", access_token=access_token)
            thread_refs = response.get("threads") if isinstance(response.get("threads"), list) else []
            for item in thread_refs:
                if synced >= max_total:
                    break
                if isinstance(item, dict) and item.get("id"):
                    self._fetch_and_cache_thread(data_root, connection_id, str(item["id"]), secrets)
                    synced += 1
            next_page_token = str(response.get("nextPageToken") or "")
            if not next_page_token:
                break
        now = now_timestamp()
        cursor_to_store = next_page_token if persist_cursor else _sync_cursor(data_root, connection_id)
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
                (
                    connection_id,
                    now,
                    "",
                    cursor_to_store,
                    connection_id,
                    now,
                    now,
                    str(response.get("historyId") or ""),
                ),
            )
        audit(data_root, "gmail.sync", "mail_connection", connection_id, {"synced_threads": synced, "has_more": bool(next_page_token)})
        return {
            "connection_id": connection_id,
            "synced_at": now,
            "synced_threads": synced,
            "has_more": bool(next_page_token),
            "next_page_token": next_page_token,
            "mode": "gmail",
        }

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
        resolved_attachment_id = str(attachment["id"])
        known_size = _bounded_int(attachment.get("size_bytes"), 0, 0, 1_000_000_000)
        metadata = {
            "attachment_id": resolved_attachment_id,
            "status": "metadata_only",
            "filename": attachment["filename"],
            "content_type": attachment["content_type"],
            "size_bytes": known_size,
            "storage_state": attachment.get("storage_state") or "not_saved",
            "storage_ref": attachment.get("storage_ref") or {},
        }
        if metadata_only:
            return metadata
        if max_bytes is None:
            return {**metadata, "status": "limit_required", "detail": "Attachment bytes require an explicit max_bytes limit."}
        if known_size and known_size > max_bytes:
            return {**metadata, "status": "too_large", "max_bytes": max_bytes}
        secrets = _require_app_secrets(app_secrets)
        message = _message(data_root, str(attachment["message_id"]))
        fetched = self._gmail_json(
            "GET",
            f"messages/{message['provider_message_id']}/attachments/{attachment['provider_attachment_id']}",
            access_token=self._access_token(secrets),
        )
        data_base64url = str(fetched.get("data") or "")
        declared_size = _bounded_int(fetched.get("size") or known_size, known_size, 0, 1_000_000_000)
        if declared_size > max_bytes:
            return {**metadata, "status": "too_large", "size_bytes": declared_size, "max_bytes": max_bytes}
        try:
            decoded_size = _base64url_decoded_size(data_base64url)
        except ValueError as error:
            return {**metadata, "status": "invalid_payload", "detail": str(error)}
        if decoded_size > max_bytes:
            return {**metadata, "status": "too_large", "size_bytes": decoded_size, "max_bytes": max_bytes}
        try:
            attachment_bytes = _decode_base64url_bytes(data_base64url)
        except ValueError as error:
            return {**metadata, "status": "invalid_payload", "detail": str(error)}
        fetched_size = len(attachment_bytes)
        if fetched_size > max_bytes:
            return {**metadata, "status": "too_large", "size_bytes": fetched_size, "max_bytes": max_bytes}
        sha256 = hashlib.sha256(attachment_bytes).hexdigest()
        if save_to_storage and skip_sha256s and sha256 in skip_sha256s:
            return {**metadata, "status": "duplicate_sha256", "size_bytes": fetched_size, "sha256": sha256}
        if save_to_storage:
            storage_ref = _save_attachment_to_storage(
                data_root,
                attachment_id=resolved_attachment_id,
                filename=str(attachment["filename"]),
                content_type=str(attachment["content_type"] or "application/octet-stream"),
                attachment_bytes=attachment_bytes,
                generated_storage_root=generated_storage_root,
                target_folder=storage_target_folder,
                mode=storage_mode,
            )
            return {
                **metadata,
                "status": "saved",
                "size_bytes": fetched_size,
                "sha256": sha256,
                "storage_state": "saved",
                "storage_ref": storage_ref,
            }
        return {
            **metadata,
            "status": "fetched",
            "size_bytes": fetched_size,
            "data_base64url": data_base64url,
            "storage_state": "not_saved",
        }

    def _access_token(self, app_secrets: dict[str, object]) -> str:
        body = urlencode(
            {
                "client_id": _required_secret(app_secrets, GMAIL_CLIENT_ID_SECRET),
                "client_secret": _required_secret(app_secrets, GMAIL_CLIENT_SECRET_SECRET),
                "refresh_token": _required_secret(app_secrets, GMAIL_REFRESH_TOKEN_SECRET),
                "grant_type": "refresh_token",
            }
        ).encode("utf-8")
        request = Request(
            GOOGLE_TOKEN_ENDPOINT,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            method="POST",
        )
        response = self._transport(request)
        access_token = str(response.get("access_token") or "").strip()
        if not access_token:
            raise ValueError("Gmail access token refresh did not return an access token")
        return access_token

    def _fetch_and_cache_thread(
        self,
        data_root: Path,
        connection_id: str,
        provider_thread_id: str,
        app_secrets: dict[str, object],
    ) -> None:
        thread = self._gmail_json(
            "GET",
            f"threads/{provider_thread_id}?{urlencode({'format': 'full'})}",
            access_token=self._access_token(app_secrets),
        )
        _cache_thread(data_root, connection_id, thread)

    def _gmail_json(
        self,
        method: str,
        resource: str,
        *,
        access_token: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        url = f"{GMAIL_API_ROOT}/{resource.lstrip('/')}"
        data = None if payload is None else json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        return self._transport(Request(url, data=data, headers=headers, method=method.upper()))


def _urlopen_json(request: Request) -> dict[str, object]:
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _cache_thread(data_root: Path, connection_id: str, thread: dict[str, object]) -> None:
    ensure_schema(data_root)
    provider_thread_id = _required_string(thread.get("id"), "thread.id")
    messages = thread.get("messages") if isinstance(thread.get("messages"), list) else []
    parsed_messages = [_parse_message(item) for item in messages if isinstance(item, dict)]
    if not parsed_messages:
        return
    subject = parsed_messages[-1]["subject"] or "(no subject)"
    participants = _participants(parsed_messages)
    labels = sorted({label.lower() for item in parsed_messages for label in item["labels"]})
    unread = any("UNREAD" in item["labels"] for item in parsed_messages)
    starred = any("STARRED" in item["labels"] for item in parsed_messages)
    last_message_at = max(str(item["sent_at"]) for item in parsed_messages)
    snippet = str(thread.get("snippet") or parsed_messages[-1]["body_text"][:180])
    local_thread_id = _local_thread_id(connection_id, provider_thread_id)
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO threads(id, connection_id, provider_thread_id, subject, participants_json, last_message_at, snippet, unread, starred, labels_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              subject = excluded.subject,
              participants_json = excluded.participants_json,
              last_message_at = excluded.last_message_at,
              snippet = excluded.snippet,
              unread = excluded.unread,
              starred = excluded.starred,
              labels_json = excluded.labels_json,
              updated_at = excluded.updated_at
            """,
            (
                local_thread_id,
                connection_id,
                provider_thread_id,
                subject,
                json.dumps(participants, ensure_ascii=True),
                last_message_at,
                snippet,
                1 if unread else 0,
                1 if starred else 0,
                json.dumps(labels, ensure_ascii=True),
                now,
            ),
        )
        for item in parsed_messages:
            provider_message_id = str(item["provider_message_id"])
            local_message_id = _local_message_id(connection_id, provider_message_id)
            _attach_inline_asset_ids(connection_id, provider_message_id, local_message_id, item["inline_assets"])
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
                    local_message_id,
                    local_thread_id,
                    provider_message_id,
                    json.dumps(item["sender"], ensure_ascii=True),
                    json.dumps(item["recipients"], ensure_ascii=True),
                    json.dumps(item["cc"], ensure_ascii=True),
                    json.dumps(item["bcc"], ensure_ascii=True),
                    item["sent_at"],
                    item["body_text"],
                    item["body_html_sanitized"],
                    item["body_html_original_bounded"],
                    item["body_html_gmail_sanitized"],
                    item["body_html_rendered"],
                    json.dumps(item["render_policy"], ensure_ascii=True, sort_keys=True),
                    item["body_render_mode"],
                    item["body_preview"],
                    1 if item["body_truncated"] else 0,
                    json.dumps(item["parts"], ensure_ascii=True),
                    json.dumps(item["inline_assets"], ensure_ascii=True),
                    json.dumps(item["headers"], ensure_ascii=True),
                    1 if item["attachments"] else 0,
                ),
            )
            for attachment in item["attachments"]:
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
                        _local_attachment_id(connection_id, str(item["provider_message_id"]), str(attachment["provider_attachment_id"])),
                        _local_message_id(connection_id, str(item["provider_message_id"])),
                        attachment["provider_attachment_id"],
                        attachment["filename"],
                        attachment["content_type"],
                        attachment["size_bytes"],
                        now,
                        now,
                    ),
                )


def _parse_message(message: dict[str, object]) -> dict[str, object]:
    payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    headers = _headers(payload)
    body = _message_body(payload)
    return {
        "provider_message_id": str(message.get("id") or ""),
        "subject": headers.get("subject", ""),
        "sender": _first_address(headers.get("from", "")),
        "recipients": _addresses(headers.get("to", "")),
        "cc": _addresses(headers.get("cc", "")),
        "bcc": _addresses(headers.get("bcc", "")),
        "sent_at": _sent_at(headers.get("date"), message.get("internalDate")),
        **body,
        "headers": headers,
        "labels": [str(item) for item in message.get("labelIds", [])] if isinstance(message.get("labelIds"), list) else [],
        "attachments": _attachments(payload),
    }


def _headers(payload: dict[str, object]) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in payload.get("headers", []) if isinstance(payload.get("headers"), list) else []:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip().lower()
            value = str(item.get("value") or "").strip()
            if name:
                values[name] = value
    return values


def _message_body(payload: dict[str, object]) -> dict[str, object]:
    plain_chunks: list[str] = []
    html_chunks: list[str] = []
    parts: list[dict[str, object]] = []
    inline_assets: list[dict[str, object]] = []
    _collect_body_parts(payload, plain_chunks, html_chunks, parts, inline_assets)
    rendered = render_email_body(plain_chunks, html_chunks)
    return {
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


def _collect_body_parts(
    part: dict[str, object],
    plain_chunks: list[str],
    html_chunks: list[str],
    parts: list[dict[str, object]],
    inline_assets: list[dict[str, object]],
) -> None:
    mime_type = str(part.get("mimeType") or "")
    body = part.get("body") if isinstance(part.get("body"), dict) else {}
    data = str(body.get("data") or "")
    filename = str(part.get("filename") or "")
    headers = _headers(part)
    disposition = headers.get("content-disposition", "").lower()
    content_id = headers.get("content-id", "").strip("<>")
    provider_attachment_id = str(body.get("attachmentId") or "")
    is_attachment = bool(filename) or "attachment" in disposition
    if content_id and mime_type.startswith("image/"):
        inline_assets.append(
            {
                "content_id": content_id,
                "provider_attachment_id": provider_attachment_id,
                "filename": filename,
                "content_type": mime_type,
                "size_bytes": int(body.get("size") or 0),
            }
        )
    if data and not is_attachment:
        decoded = _decode_text_part(data, _part_charset(part))
        if mime_type == "text/plain":
            plain_chunks.append(decoded)
        elif mime_type == "text/html":
            html_chunks.append(decoded)
    if mime_type.startswith("text/") or content_id:
        parts.append(
            {
                "mime_type": mime_type,
                "filename": filename,
                "content_id": content_id,
                "provider_attachment_id": provider_attachment_id,
                "size_bytes": int(body.get("size") or 0),
                "disposition": disposition,
            }
        )
    for child in part.get("parts", []) if isinstance(part.get("parts"), list) else []:
        if isinstance(child, dict):
            _collect_body_parts(child, plain_chunks, html_chunks, parts, inline_assets)


def _attachments(payload: dict[str, object]) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    _collect_attachments(payload, found)
    return found


def _collect_attachments(part: dict[str, object], found: list[dict[str, object]]) -> None:
    body = part.get("body") if isinstance(part.get("body"), dict) else {}
    attachment_id = str(body.get("attachmentId") or "")
    filename = str(part.get("filename") or "")
    if attachment_id and filename:
        found.append(
            {
                "provider_attachment_id": attachment_id,
                "filename": filename,
                "content_type": str(part.get("mimeType") or ""),
                "size_bytes": int(body.get("size") or 0),
            }
        )
    for child in part.get("parts", []) if isinstance(part.get("parts"), list) else []:
        if isinstance(child, dict):
            _collect_attachments(child, found)


def _attach_inline_asset_ids(connection_id: str, provider_message_id: str, local_message_id: str, inline_assets: list[dict[str, object]]) -> None:
    for asset in inline_assets:
        provider_attachment_id = str(asset.get("provider_attachment_id") or "")
        if not provider_attachment_id:
            continue
        asset["message_id"] = local_message_id
        asset["attachment_id"] = _local_attachment_id(connection_id, provider_message_id, provider_attachment_id)


def _decode_text_part(value: str, charset: str) -> str:
    raw = base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode("ascii"))
    try:
        return raw.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _part_charset(part: dict[str, object]) -> str:
    content_type = _headers(part).get("content-type") or str(part.get("mimeType") or "")
    match = re.search(r"charset=['\"]?([^;'\"]+)", content_type, flags=re.IGNORECASE)
    return match.group(1).strip() if match else "utf-8"


def _base64url_decoded_size(value: str) -> int:
    if not re.fullmatch(r"[A-Za-z0-9_-]*={0,2}", value):
        raise ValueError("Gmail attachment payload was not valid base64url")
    unpadded = value.rstrip("=")
    if "=" in unpadded or len(unpadded) % 4 == 1:
        raise ValueError("Gmail attachment payload was not valid base64url")
    padding = -len(unpadded) % 4
    return ((len(unpadded) + padding) // 4 * 3) - padding


def _decode_base64url_bytes(value: str) -> bytes:
    try:
        return base64.b64decode(_padded_base64url(value), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("Gmail attachment payload was not valid base64url") from error


def _sent_at(date_header: str | None, internal_date: object) -> str:
    if date_header:
        try:
            parsed = parsedate_to_datetime(date_header)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC).isoformat()
        except (TypeError, ValueError):
            pass
    try:
        millis = int(str(internal_date or "0"))
    except ValueError:
        millis = 0
    if millis:
        return datetime.fromtimestamp(millis / 1000, tz=UTC).isoformat()
    return now_timestamp()


def _participants(messages: list[dict[str, object]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    participants: list[dict[str, str]] = []
    for item in messages:
        addresses = [item["sender"], *item["recipients"], *item["cc"]]
        for address in addresses:
            if not isinstance(address, dict):
                continue
            email = str(address.get("email") or "").lower()
            if email and email not in seen:
                seen.add(email)
                participants.append({"email": email, "name": str(address.get("name") or "")})
    return participants


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


def _format_address(value: object) -> str:
    if isinstance(value, dict):
        email = str(value.get("email") or "")
        name = str(value.get("name") or "")
        return f"{name} <{email}>" if name else email
    return str(value or "")


def _connection(data_root: Path, connection_id: str) -> dict[str, object]:
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM connections WHERE id = ?", (connection_id,)).fetchone()
    if row is None:
        raise ValueError(f"Connection `{connection_id}` was not found")
    return dict(row)


def _sync_cursor(data_root: Path, connection_id: str) -> str:
    with connect(data_root) as db:
        row = db.execute("SELECT cursor FROM sync_state WHERE connection_id = ?", (connection_id,)).fetchone()
    return str(row["cursor"] or "").strip() if row is not None else ""


def _message(data_root: Path, message_id: str) -> dict[str, object]:
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    if row is None:
        raise ValueError(f"Message `{message_id}` was not found")
    return dict(row)


def _gmail_labels(value: object) -> list[str]:
    return [_gmail_label_id(item) for item in _string_list(value)]


def _gmail_label_id(value: str) -> str:
    normalized = value.strip()
    known = {"inbox": "INBOX", "trash": "TRASH", "sent": "SENT", "draft": "DRAFT", "drafts": "DRAFT", "starred": "STARRED", "unread": "UNREAD"}
    return known.get(normalized.lower(), normalized)


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value in (None, ""):
        return []
    return [str(value).strip()]


def _as_secret_map(payload: dict[str, object]) -> dict[str, object]:
    value = payload.get("_app_secrets")
    return value if isinstance(value, dict) else {}


def _require_app_secrets(value: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Gmail operation requires Core Secrets delivery for this connection")
    return value


def _required_secret(secrets: dict[str, object], logical_name: str) -> str:
    value = str(secrets.get(logical_name) or "").strip()
    if not value:
        raise ValueError(f"Gmail operation requires secret `{logical_name}`")
    return value


def _require_recipients(draft: dict[str, object]) -> None:
    if not any(_string_list(draft.get(field)) for field in ("to", "cc", "bcc")):
        raise ValueError("At least one recipient in to, cc, or bcc is required")


def _required_string(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _optional_string(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _save_attachment_to_storage(
    data_root: Path,
    *,
    attachment_id: str,
    filename: str,
    content_type: str,
    attachment_bytes: bytes,
    generated_storage_root: Path | None,
    target_folder: object = None,
    mode: object = "versioned",
) -> dict[str, object]:
    return save_attachment_to_storage(
        data_root,
        attachment_id=attachment_id,
        filename=filename,
        content_type=content_type,
        attachment_bytes=attachment_bytes,
        generated_storage_root=generated_storage_root,
        target_folder=target_folder,
        mode=mode,
    )


def _attachment_storage_dir(generated_storage_root: Path) -> Path:
    storage_root = generated_storage_root.resolve()
    mail_dir = storage_root / "mail"
    if mail_dir.is_symlink():
        raise ValueError("Attachment Storage path escaped storage/generated/mail/attachments")
    mail_dir.mkdir(parents=True, exist_ok=True)
    target_dir = mail_dir / "attachments"
    if target_dir.is_symlink():
        raise ValueError("Attachment Storage path escaped storage/generated/mail/attachments")
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def _write_unique_attachment(target_dir: Path, attachment_id: str, safe_name: str, content: bytes) -> tuple[Path, bool]:
    base_id = _safe_id(attachment_id)
    base_name = f"{base_id}-{safe_name}"
    for attempt in range(100):
        target_name = base_name if attempt == 0 else _collision_filename(base_id, safe_name)
        target = target_dir / target_name
        _verify_attachment_storage_target(target_dir, target)
        try:
            with target.open("xb") as handle:
                handle.write(content)
            return target, attempt > 0
        except FileExistsError:
            continue
    raise ValueError("Could not allocate a unique Storage path for the attachment")


def _collision_filename(base_id: str, safe_name: str) -> str:
    suffix = Path(safe_name).suffix
    stem = Path(safe_name).stem if suffix else safe_name
    return f"{base_id}-{stem}-{uuid4().hex[:12]}{suffix}"


def _verify_attachment_storage_target(target_dir: Path, target: Path) -> None:
    expected_dir = target_dir
    try:
        resolved_target = target.resolve(strict=False)
        resolved_target.relative_to(expected_dir)
    except ValueError as error:
        raise ValueError("Attachment Storage path escaped storage/generated/mail/attachments") from error
    if target.parent.resolve(strict=True) != expected_dir:
        raise ValueError("Attachment Storage path must be directly under storage/generated/mail/attachments")


def _padded_base64url(value: str) -> bytes:
    return (value + "=" * (-len(value) % 4)).encode("ascii")


def _safe_filename(value: str) -> str:
    basename = value.strip().replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", basename).strip(".-")
    return name or "attachment.bin"


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower() or uuid4().hex


def _local_thread_id(connection_id: str, provider_thread_id: str) -> str:
    return f"email_thread_gmail_{_safe_id(connection_id)}_{_safe_id(provider_thread_id)}"


def _local_message_id(connection_id: str, provider_message_id: str) -> str:
    return f"email_message_gmail_{_safe_id(connection_id)}_{_safe_id(provider_message_id)}"


def _local_attachment_id(connection_id: str, provider_message_id: str, provider_attachment_id: str) -> str:
    return f"mail_attachment_gmail_{_safe_id(connection_id)}_{_safe_id(provider_message_id)}_{_safe_id(provider_attachment_id)}"
