"""Service layer for the Mail app."""

from __future__ import annotations

import base64
import binascii
import hashlib
from pathlib import Path

from connections import (
    IMAP_PASSWORD_SECRET,
    IMAP_SMTP_PROVIDER,
    MAILBOX_PASSWORD_SECRET,
    SMTP_PASSWORD_SECRET,
    activate_imap_smtp,
    prepare_imap_smtp,
    secret_resource_inventory,
    test_imap_smtp,
    update_imap_smtp,
)
from database import health_payload
from drafts import create_draft, delete_draft, get_draft, update_draft
from oauth import complete_oauth, provider_status, start_oauth
from providers.registry import provider_for_connection
from references import reference_manifest, reference_resolve, reference_search, reference_summary
from storage_attachments import draft_id_for_confirmation_token, save_attachment_to_storage
from store import (
    DEFAULT_BODY_HTML_CHARS,
    DEFAULT_BODY_TEXT_CHARS,
    count_threads,
    delete_disconnected_connection,
    disconnect_connection,
    get_connection,
    get_attachment,
    get_message,
    get_thread,
    list_threads,
    list_connections,
    list_folders,
    list_labels,
    mailbox_counts,
    resolve_connected_connection,
    search_messages,
    status,
)
from view_state import clear_custom_view, load_view_state, set_custom_view, set_view_filter


MUTATING_ACTIONS = {
    "connections.start_oauth",
    "connections.complete_oauth",
    "connections.delete",
    "connections.disconnect",
    "connections.prepare_imap_smtp",
    "connections.update_imap_smtp",
    "connections.test_imap_smtp",
    "connections.activate_imap_smtp",
    "threads.sync",
    "mail_sync",
    "drafts.create",
    "mail_create_draft",
    "drafts.update",
    "mail_update_draft",
    "drafts.delete",
    "drafts.send",
    "mail_send_draft",
    "messages.send",
    "mail_send",
    "attachments.save_all",
    "mail_save_attachments",
    "labels.modify",
    "mail_modify_labels",
    "messages.mark_read",
    "mail_mark_read",
    "set_view_filter",
    "set_custom_view",
    "clear_custom_view",
}

ATTACHMENT_GET_ACTIONS = {"attachments.get", "mail_get_attachment", "attachments.save_all", "mail_save_attachments"}
THREAD_LIST_ACTIONS = {"threads.list", "mail_list_threads", "list"}
INTERACTIVE_SYNC_MAX_THREADS = 25


def handle_action(data_root: Path, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    action = str(payload.get("action") or "threads.list")
    try:
        if action in {"status", "health.check"}:
            return 200, {**status(data_root), **health_payload(data_root)}
        if action == "connections.list":
            connections = list_connections(data_root)
            return 200, {"items": connections, **provider_status(payload.get("_app_secrets"), connections)}
        if action == "connections.start_oauth":
            result = start_oauth(data_root, payload)
            return (200 if result.get("status") != "not_configured" else 409), result
        if action == "connections.complete_oauth":
            result = complete_oauth(data_root, payload)
            return (200 if result.get("status") not in {"needs_secret_grant", "token_storage_required"} else 409), result
        if action == "connections.prepare_imap_smtp":
            return 201, prepare_imap_smtp(data_root, payload)
        if action == "connections.update_imap_smtp":
            return 200, update_imap_smtp(data_root, payload)
        if action == "connections.test_imap_smtp":
            result = test_imap_smtp(data_root, payload)
            return (200 if result.get("status") == "ready" else 409), result
        if action == "connections.activate_imap_smtp":
            result = activate_imap_smtp(data_root, payload)
            return (200 if result.get("status") == "connected" else 409), result
        if action == "connections.disconnect":
            return 200, {
                "disconnect": disconnect_connection(
                    data_root,
                    _required_string(payload.get("connection_id") or payload.get("id"), "connection_id"),
                    reason=str(payload.get("reason") or "").strip(),
                )
            }
        if action == "connections.delete":
            return 200, {
                "delete": delete_disconnected_connection(
                    data_root,
                    _required_string(payload.get("connection_id") or payload.get("id"), "connection_id"),
                )
            }
        if action in {"folders.list", "mail_list_folders"}:
            return 200, {"items": list_folders(data_root, _optional_string(payload.get("connection_id")))}
        if action in {"labels.list", "mail_list_labels"}:
            return 200, {"items": list_labels(data_root, _optional_string(payload.get("connection_id")))}
        if action in THREAD_LIST_ACTIONS:
            cache_total_count = count_threads(data_root, payload)
            return 200, {
                "items": list_threads(data_root, payload),
                "limit": _bounded_int(payload.get("max_threads") or payload.get("limit"), 50, 1, 200),
                "offset": _bounded_int(payload.get("offset"), 0, 0, 100_000),
                "total_count": cache_total_count,
            }
        if action in {"mailboxes.counts", "mail_mailbox_counts"}:
            return 200, {"counts": mailbox_counts(data_root)}
        if action in {"threads.get", "mail_get_thread", "get"}:
            thread_id = _required_string(payload.get("thread_id") or payload.get("id"), "thread_id")
            thread = get_thread(data_root, thread_id)
            connection_id = str(thread["connection_id"])
            provider = provider_for_connection(data_root, connection_id)
            max_body_chars, max_body_html_chars = _body_response_limits(payload)
            return 200, {
                "thread": provider.get_thread(
                    data_root,
                    thread_id,
                    max_body_chars,
                    max_body_html_chars=max_body_html_chars,
                    app_secrets={} if _is_disconnected(data_root, connection_id) else _app_secrets(payload),
                )
            }
        if action in {"threads.sync", "mail_sync"}:
            connection_id = _payload_connection_id(data_root, payload)
            _require_connected(data_root, connection_id)
            provider = provider_for_connection(data_root, connection_id)
            return 200, {
                "sync": provider.sync_incremental(
                    data_root,
                    connection_id,
                    app_secrets=_app_secrets(payload),
                    max_threads=_bounded_int(payload.get("max_threads") or payload.get("limit"), INTERACTIVE_SYNC_MAX_THREADS, 1, 2000),
                    query=_provider_sync_query(provider, payload),
                    page_token=_optional_string(payload.get("page_token")),
                    continue_cursor=bool(payload.get("continue_cursor")),
                )
            }
        if action in {"messages.get", "mail_get_message"}:
            max_body_chars, max_body_html_chars = _body_response_limits(payload)
            return 200, {
                "message": get_message(
                    data_root,
                    _required_string(payload.get("message_id") or payload.get("id"), "message_id"),
                    max_body_chars,
                    max_body_html_chars=max_body_html_chars,
                )
            }
        if action in {"messages.search", "mail_search_messages", "search"}:
            return 200, {
                "items": search_messages(
                    data_root,
                    str(payload.get("query") or ""),
                    _bounded_int(payload.get("max_messages") or payload.get("limit"), 25, 1, 100),
                )
            }
        if action in {"drafts.create", "mail_create_draft"}:
            return 201, {"draft": create_draft(data_root, _with_effective_connection_payload(data_root, payload))}
        if action in {"drafts.update", "mail_update_draft"}:
            return 200, {"draft": update_draft(data_root, _required_string(payload.get("draft_id") or payload.get("id"), "draft_id"), payload)}
        if action == "drafts.get":
            return 200, {"draft": get_draft(data_root, _required_string(payload.get("draft_id") or payload.get("id"), "draft_id"))}
        if action in {"drafts.delete"}:
            return 200, delete_draft(data_root, _required_string(payload.get("draft_id") or payload.get("id"), "draft_id"))
        if action in {"drafts.send", "mail_send_draft"}:
            draft_id = _required_string(payload.get("draft_id") or payload.get("id"), "draft_id")
            draft = get_draft(data_root, draft_id)
            _require_connected(data_root, str(draft["connection_id"]))
            provider = provider_for_connection(data_root, str(draft["connection_id"]))
            return 200, {
                "result": provider.send_draft(
                    data_root,
                    draft_id,
                    confirm=bool(payload.get("confirm")),
                    app_secrets=_app_secrets(payload),
                    uploaded_storage_root=_optional_path(payload.get("_uploaded_storage_root")),
                    generated_storage_root=_optional_path(payload.get("_generated_storage_root")),
                    confirmation_token=payload.get("confirmation_token"),
                )
            }
        if action in {"messages.send", "mail_send"}:
            if bool(payload.get("confirm")):
                if not str(payload.get("confirmation_token") or "").strip():
                    _preflight_mail_send_confirmation(data_root, payload)
                draft_id = draft_id_for_confirmation_token(data_root, payload.get("confirmation_token"))
                draft = get_draft(data_root, draft_id)
                connection_id = str(draft["connection_id"])
                requested_connection_id = _optional_string(payload.get("connection_id"))
                if requested_connection_id and requested_connection_id != connection_id:
                    raise ValueError("confirmation_token belongs to a different mail connection")
                _require_connected(data_root, connection_id)
                provider = provider_for_connection(data_root, connection_id)
                result = provider.send_draft(
                    data_root,
                    str(draft["id"]),
                    confirm=True,
                    app_secrets=_app_secrets(payload),
                    uploaded_storage_root=_optional_path(payload.get("_uploaded_storage_root")),
                    generated_storage_root=_optional_path(payload.get("_generated_storage_root")),
                    confirmation_token=payload.get("confirmation_token"),
                )
                return 200, {"draft": draft, "result": result}
            connection_id = _payload_connection_id(data_root, payload)
            _require_connected(data_root, connection_id)
            draft = create_draft(data_root, {**payload, "connection_id": connection_id})
            provider = provider_for_connection(data_root, str(draft["connection_id"]))
            result = provider.send_draft(
                data_root,
                str(draft["id"]),
                confirm=False,
                app_secrets=_app_secrets(payload),
                uploaded_storage_root=_optional_path(payload.get("_uploaded_storage_root")),
                generated_storage_root=_optional_path(payload.get("_generated_storage_root")),
            )
            return 200, {"draft": draft, "result": result}
        if action in {"labels.modify", "mail_modify_labels"}:
            thread_id = _required_string(payload.get("thread_id") or payload.get("id"), "thread_id")
            connection_id = str(get_thread(data_root, thread_id)["connection_id"])
            _require_connected(data_root, connection_id)
            provider = provider_for_connection(data_root, connection_id)
            return 200, {
                "thread": provider.modify_labels(
                    data_root,
                    thread_id,
                    add=payload.get("add"),
                    remove=payload.get("remove"),
                    app_secrets=_app_secrets(payload),
                )
            }
        if action in {"messages.mark_read", "mail_mark_read"}:
            thread_id = _required_string(payload.get("thread_id") or payload.get("id"), "thread_id")
            connection_id = str(get_thread(data_root, thread_id)["connection_id"])
            _require_connected(data_root, connection_id)
            provider = provider_for_connection(data_root, connection_id)
            return 200, {
                "thread": provider.mark_read(
                    data_root,
                    thread_id,
                    read=bool(payload.get("read", True)),
                    app_secrets=_app_secrets(payload),
                )
            }
        if action in {"attachments.get", "mail_get_attachment"}:
            attachment = get_attachment(data_root, _required_string(payload.get("attachment_id") or payload.get("id"), "attachment_id"))
            thread = get_thread(data_root, str(attachment["thread_id"]))
            connection_id = str(thread["connection_id"])
            if _is_disconnected(data_root, connection_id) and not bool(payload.get("metadata_only", True)):
                raise ValueError(f"Connection `{connection_id}` is disconnected")
            provider = provider_for_connection(data_root, connection_id)
            return 200, {
                "attachment": attachment,
                "fetch": provider.fetch_attachment(
                    data_root,
                    str(attachment["id"]),
                    app_secrets=_app_secrets(payload),
                    metadata_only=bool(payload.get("metadata_only", True)),
                    max_bytes=_optional_bounded_int(payload.get("max_bytes"), 1, 10_000_000),
                    save_to_storage=bool(payload.get("save_to_storage")),
                    generated_storage_root=_optional_path(payload.get("_generated_storage_root")),
                    storage_target_folder=payload.get("target_folder"),
                    storage_mode=payload.get("mode") or "versioned",
                ),
            }
        if action in {"attachments.save_all", "mail_save_attachments"}:
            return 200, _save_thread_attachments(data_root, payload)
        if action in {"reference_manifest", "mail_reference_manifest"}:
            return 200, reference_manifest()
        if action in {"reference_search", "mail_reference_search"}:
            return 200, {"items": reference_search(data_root, str(payload.get("query") or ""), _bounded_int(payload.get("limit"), 20, 1, 50))}
        if action in {"reference_resolve", "mail_reference_resolve"}:
            return 200, {"item": reference_resolve(data_root, _entity_type(payload), _entity_id(payload))}
        if action in {"reference_summarize", "mail_reference_summarize"}:
            return 200, {"summary": reference_summary(data_root, _entity_type(payload), _entity_id(payload), _bounded_int(payload.get("max_chars"), 1200, 200, 4000))}
        if action == "view_filter":
            return 200, {"state": load_view_state(data_root)}
        if action == "set_view_filter":
            return 200, {"state": set_view_filter(data_root, query=payload.get("query"), mailbox=payload.get("mailbox"), preserve_custom=bool(payload.get("preserve_custom")))}
        if action == "set_custom_view":
            return 200, {"state": set_custom_view(data_root, title=payload.get("title"), refs=payload.get("refs"))}
        if action == "clear_custom_view":
            return 200, {"state": clear_custom_view(data_root)}
    except ValueError as error:
        return 400, {"error": "validation_error", "detail": str(error)}
    return 400, {"error": "unsupported_action", "detail": f"Unsupported action `{action}`."}


def resolve_secret_resource(data_root: Path, payload: dict[str, object]) -> dict[str, object]:
    """Resolve whether an invocation needs a per-connection provider secret grant."""
    try:
        if _is_cache_only_thread_list_action(payload):
            return {"requires_secrets": False}
        connection_id = _secret_resource_connection_id(data_root, payload)
        if not connection_id:
            return {"requires_secrets": False}
        connection = get_connection(data_root, connection_id)
        if connection.get("status") == "disconnected":
            return {"requires_secrets": False, "resource_type": "mail_connection", "resource_id": connection_id, "status": "disconnected"}
        provider = str(connection.get("provider") or "")
        selector_names = _selector_logical_names(payload)
        if provider == "gmail":
            needs = not selector_names or any(name.startswith("gmail-") for name in selector_names)
            return {"requires_secrets": needs, "resource_type": "mail_connection", "resource_id": connection_id, "provider": provider}
        if provider == IMAP_SMTP_PROVIDER:
            imap_names = {MAILBOX_PASSWORD_SECRET, IMAP_PASSWORD_SECRET, SMTP_PASSWORD_SECRET}
            needs = not selector_names or bool(imap_names.intersection(selector_names))
            return {"requires_secrets": needs, "resource_type": "mail_connection", "resource_id": connection_id, "provider": provider}
        return {"requires_secrets": False, "resource_type": "mail_connection", "resource_id": connection_id, "provider": provider}
    except ValueError as error:
        return {"requires_secrets": False, "error": "validation_error", "detail": str(error)}


def resolve_secret_resource_inventory(data_root: Path) -> dict[str, object]:
    return secret_resource_inventory(data_root)


def app_events_for_action(action: str, result: dict[str, object] | None = None) -> list[dict[str, str]]:
    if action in ATTACHMENT_GET_ACTIONS:
        if action in {"attachments.save_all", "mail_save_attachments"}:
            saved = result.get("saved") if isinstance(result, dict) else None
            return [_data_changed_event("threads")] if saved else []
        if _attachment_saved_to_storage(result):
            return [_data_changed_event("threads")]
        return []
    if action not in MUTATING_ACTIONS:
        return []
    if action in {"set_view_filter", "set_custom_view", "clear_custom_view"}:
        resource = "view-state"
    elif action.startswith("drafts") or action.startswith("mail_") and "draft" in action:
        resource = "drafts"
    elif "connection" in action:
        resource = "connections"
    else:
        resource = "threads"
    return [_data_changed_event(resource)]


def _save_thread_attachments(data_root: Path, payload: dict[str, object]) -> dict[str, object]:
    thread_id = _required_string(payload.get("thread_id") or payload.get("id"), "thread_id")
    thread = get_thread(data_root, thread_id)
    connection_id = str(thread["connection_id"])
    _require_connected(data_root, connection_id)
    provider = provider_for_connection(data_root, connection_id)
    max_bytes = _optional_bounded_int(payload.get("max_bytes"), 1, 10_000_000) or 10_000_000
    dedupe = bool(payload.get("dedupe", True))
    target_folder = payload.get("target_folder") or "storage/generated/mail/attachments"
    mode = payload.get("mode") or "versioned"
    saved: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    seen_hashes: set[str] = set()
    generated_storage_root = _optional_path(payload.get("_generated_storage_root"))
    for message in thread.get("messages", []):
        if not isinstance(message, dict):
            continue
        for attachment in message.get("attachments", []):
            if not isinstance(attachment, dict):
                continue
            if not _attachment_filter_matches(attachment, payload):
                skipped.append({"attachment_id": attachment.get("id"), "reason": "filtered"})
                continue
            filename = str(attachment.get("filename") or "")
            size_bytes = int(attachment.get("size_bytes") or 0)
            fetch = provider.fetch_attachment(
                data_root,
                str(attachment["id"]),
                app_secrets=_app_secrets(payload),
                metadata_only=False,
                max_bytes=max_bytes,
                save_to_storage=True,
                generated_storage_root=generated_storage_root,
                storage_target_folder=target_folder,
                storage_mode=mode,
                skip_sha256s=seen_hashes if dedupe else None,
            )
            if fetch.get("status") == "duplicate_sha256":
                sha256 = str(fetch.get("sha256") or "")
                skipped.append(
                    {"attachment_id": attachment.get("id"), "filename": filename, "reason": "duplicate_sha256", "sha256": sha256}
                )
                continue
            if fetch.get("status") == "saved":
                storage_ref = fetch.get("storage_ref") if isinstance(fetch.get("storage_ref"), dict) else {}
                sha256 = str(storage_ref.get("sha256") or fetch.get("sha256") or "")
                if sha256:
                    seen_hashes.add(sha256)
                saved.append(
                    {
                        "attachment_id": attachment.get("id"),
                        "message_id": message.get("id"),
                        "thread_id": thread_id,
                        "filename": filename,
                        "content_type": attachment.get("content_type") or "",
                        "size_bytes": storage_ref.get("size_bytes", fetch.get("size_bytes", size_bytes)),
                        "sha256": sha256,
                        "workspace_relative_path": storage_ref.get("workspace_relative_path"),
                        "source": {
                            "message_id": message.get("id"),
                            "sent_at": message.get("sent_at"),
                            "sender": message.get("sender"),
                        },
                    }
                )
                continue
            if fetch.get("status") != "fetched":
                skipped.append(
                    {
                        "attachment_id": attachment.get("id"),
                        "filename": filename,
                        "reason": fetch.get("status"),
                        "detail": fetch.get("detail"),
                    }
                )
                continue
            try:
                attachment_bytes = _attachment_bytes_from_fetch(fetch)
            except ValueError as error:
                skipped.append(
                    {"attachment_id": attachment.get("id"), "filename": filename, "reason": "invalid_payload", "detail": str(error)}
                )
                continue
            sha256 = hashlib.sha256(attachment_bytes).hexdigest()
            if dedupe and sha256 and sha256 in seen_hashes:
                skipped.append(
                    {"attachment_id": attachment.get("id"), "filename": filename, "reason": "duplicate_sha256", "sha256": sha256}
                )
                continue
            seen_hashes.add(sha256)
            storage_ref = save_attachment_to_storage(
                data_root,
                attachment_id=str(attachment["id"]),
                filename=filename,
                content_type=str(attachment.get("content_type") or "application/octet-stream"),
                attachment_bytes=attachment_bytes,
                generated_storage_root=generated_storage_root,
                target_folder=target_folder,
                mode=mode,
            )
            saved.append(
                {
                    "attachment_id": attachment.get("id"),
                    "message_id": message.get("id"),
                    "thread_id": thread_id,
                    "filename": filename,
                    "content_type": attachment.get("content_type") or "",
                    "size_bytes": storage_ref.get("size_bytes", fetch.get("size_bytes", size_bytes)),
                    "sha256": sha256,
                    "workspace_relative_path": storage_ref.get("workspace_relative_path"),
                    "source": {
                        "message_id": message.get("id"),
                        "sent_at": message.get("sent_at"),
                        "sender": message.get("sender"),
                    },
                }
            )
    return {
        "status": "saved",
        "thread_id": thread_id,
        "target_folder": target_folder,
        "dedupe": dedupe,
        "saved": saved,
        "skipped": skipped,
        "saved_count": len(saved),
        "skipped_count": len(skipped),
    }


def _attachment_bytes_from_fetch(fetch: dict[str, object]) -> bytes:
    data_base64url = str(fetch.get("data_base64url") or "").strip()
    if not data_base64url:
        if int(fetch.get("size_bytes") or 0) == 0:
            return b""
        raise ValueError("Provider did not return attachment bytes.")
    try:
        return base64.urlsafe_b64decode(data_base64url + ("=" * (-len(data_base64url) % 4)))
    except (binascii.Error, ValueError) as error:
        raise ValueError("Provider returned invalid attachment bytes.") from error


def _attachment_filter_matches(attachment: dict[str, object], payload: dict[str, object]) -> bool:
    filename = str(attachment.get("filename") or "")
    content_type = str(attachment.get("content_type") or "")
    size_bytes = int(attachment.get("size_bytes") or 0)
    name_contains = _optional_string(payload.get("filename_contains"))
    if name_contains and name_contains.casefold() not in filename.casefold():
        return False
    extensions = _string_filter_set(payload.get("extensions") or payload.get("extension"))
    if extensions:
        suffix = Path(filename).suffix.lower().lstrip(".")
        if suffix not in extensions:
            return False
    content_types = _string_filter_set(payload.get("content_types") or payload.get("content_type"))
    if content_types and content_type.casefold() not in content_types:
        return False
    max_size = _optional_bounded_int(payload.get("max_size_bytes"), 1, 10_000_000_000)
    if max_size is not None and size_bytes > max_size:
        return False
    return True


def _string_filter_set(value: object) -> set[str]:
    if value in (None, ""):
        return set()
    values = value if isinstance(value, list) else [value]
    return {str(item).strip().lower().lstrip(".") for item in values if str(item).strip()}


def _data_changed_event(resource: str) -> dict[str, str]:
    return {"type": "maverick.app.data-changed", "owner_app_id": "mail", "resource": resource}


def _attachment_saved_to_storage(result: dict[str, object] | None) -> bool:
    if not isinstance(result, dict):
        return False
    fetch = result.get("fetch")
    return isinstance(fetch, dict) and fetch.get("status") == "saved"


def _entity_type(payload: dict[str, object]) -> str:
    return _required_string(payload.get("entity_type"), "entity_type")


def _entity_id(payload: dict[str, object]) -> str:
    return _required_string(payload.get("entity_id") or payload.get("id"), "entity_id")


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


def _optional_bounded_int(value: object, minimum: int, maximum: int) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < minimum:
        return None
    return min(maximum, parsed)


def _body_response_limits(payload: dict[str, object]) -> tuple[int, int]:
    max_body_chars = _bounded_int(payload.get("max_body_chars"), DEFAULT_BODY_TEXT_CHARS, 200, 50_000)
    max_body_html_chars = _bounded_int(payload.get("max_body_html_chars"), max_body_chars, 200, DEFAULT_BODY_HTML_CHARS)
    return max_body_chars, max_body_html_chars


def _optional_path(value: object) -> Path | None:
    text = str(value or "").strip()
    return Path(text) if text else None


def _payload_connection_id(data_root: Path, payload: dict[str, object]) -> str | None:
    explicit = _optional_string(payload.get("connection_id"))
    if explicit:
        return _effective_connection_id(data_root, explicit)
    connections = list_connections(data_root)
    if not connections:
        return None
    connected = [connection for connection in connections if connection.get("status") == "connected"]
    selected = connected[0] if connected else connections[0]
    return _effective_connection_id(data_root, str(selected["id"]))


def _preflight_mail_send_confirmation(data_root: Path, payload: dict[str, object]) -> None:
    connection_id = _payload_connection_id(data_root, payload)
    _require_connected(data_root, connection_id)
    has_explicit_recipient = any(_non_empty_items(payload.get(key)) for key in ("to", "cc", "bcc"))
    if not has_explicit_recipient and not _optional_string(payload.get("thread_id")):
        raise ValueError("At least one recipient in to, cc, or bcc is required")


def _non_empty_items(value: object) -> bool:
    if isinstance(value, list):
        return bool(value)
    return bool(str(value or "").strip())


def _provider_sync_query(provider: object, payload: dict[str, object]) -> str | None:
    query = _optional_string(payload.get("query"))
    if query:
        sync_query_for_payload = getattr(provider, "sync_query_for_payload", None)
        if callable(sync_query_for_payload):
            return sync_query_for_payload(payload, default_recent=False)
        return query
    if not _payload_has_mailbox_filter(payload):
        return None
    sync_query_for_payload = getattr(provider, "sync_query_for_payload", None)
    if callable(sync_query_for_payload):
        return sync_query_for_payload(payload, default_recent=False)
    return None


def _payload_has_mailbox_filter(payload: dict[str, object]) -> bool:
    return bool(_optional_string(payload.get("mailbox") or payload.get("label") or payload.get("mailbox_scopes")))


def _is_cache_only_thread_list_action(payload: dict[str, object]) -> bool:
    action = _optional_string(payload.get("action"))
    return bool(action and action in THREAD_LIST_ACTIONS)


def _is_disconnected(data_root: Path, connection_id: str | None) -> bool:
    if not connection_id:
        return False
    return resolve_connected_connection(data_root, connection_id).get("status") == "disconnected"


def _require_connected(data_root: Path, connection_id: str | None) -> None:
    if not connection_id:
        raise ValueError("connection_id is required")
    status = str(resolve_connected_connection(data_root, connection_id).get("status") or "")
    if status != "connected":
        raise ValueError(f"Connection `{connection_id}` is `{status or 'unknown'}`; test and activate it before mail operations.")


def _secret_resource_connection_id(data_root: Path, payload: dict[str, object]) -> str | None:
    explicit = _optional_string(payload.get("connection_id"))
    action = str(payload.get("action") or "")
    if action in {"messages.send", "mail_send"} and bool(payload.get("confirm")):
        confirmation_token = _optional_string(payload.get("confirmation_token"))
        if confirmation_token:
            draft_id = draft_id_for_confirmation_token(data_root, confirmation_token)
            token_connection_id = _effective_connection_id(data_root, str(get_draft(data_root, draft_id)["connection_id"]))
            if explicit and _effective_connection_id(data_root, explicit) != token_connection_id:
                raise ValueError("confirmation_token belongs to a different mail connection")
            return token_connection_id
    if explicit:
        return _effective_connection_id(data_root, explicit)
    fallback_id = _optional_string(payload.get("id"))
    thread_id = _optional_string(payload.get("thread_id")) or (
        fallback_id
        if action in {
            "threads.get",
            "mail_get_thread",
            "get",
            "labels.modify",
            "mail_modify_labels",
            "messages.mark_read",
            "mail_mark_read",
            "messages.send",
            "mail_send",
            "attachments.save_all",
            "mail_save_attachments",
        }
        else None
    )
    if thread_id:
        return _effective_connection_id(data_root, str(get_thread(data_root, thread_id)["connection_id"]))
    draft_id = _optional_string(payload.get("draft_id")) or (fallback_id if action in {"drafts.send", "mail_send_draft", "drafts.get", "drafts.update", "mail_update_draft"} else None)
    if draft_id:
        return _effective_connection_id(data_root, str(get_draft(data_root, draft_id)["connection_id"]))
    attachment_id = _optional_string(payload.get("attachment_id")) or (fallback_id if action in {"attachments.get", "mail_get_attachment"} else None)
    if attachment_id:
        attachment = get_attachment(data_root, attachment_id)
        return _effective_connection_id(data_root, str(get_thread(data_root, str(attachment["thread_id"]))["connection_id"]))
    message_id = _optional_string(payload.get("message_id")) or (fallback_id if action in {"messages.get", "mail_get_message"} else None)
    if message_id:
        message = get_message(data_root, message_id)
        return _effective_connection_id(data_root, str(get_thread(data_root, str(message["thread_id"]))["connection_id"]))
    return _payload_connection_id(data_root, payload)


def _effective_connection_id(data_root: Path, connection_id: str) -> str:
    return str(resolve_connected_connection(data_root, connection_id).get("id") or connection_id)


def _with_effective_connection_payload(data_root: Path, payload: dict[str, object]) -> dict[str, object]:
    connection_id = _optional_string(payload.get("connection_id"))
    if not connection_id:
        return payload
    return {**payload, "connection_id": _effective_connection_id(data_root, connection_id)}


def _app_secrets(payload: dict[str, object]) -> dict[str, object]:
    value = payload.get("_app_secrets")
    return value if isinstance(value, dict) else {}


def _selector_logical_names(payload: dict[str, object]) -> set[str]:
    selector = payload.get("_app_secret_selector")
    if not isinstance(selector, dict):
        return set()
    names = selector.get("logical_names")
    if not isinstance(names, list):
        return set()
    return {str(name) for name in names}
