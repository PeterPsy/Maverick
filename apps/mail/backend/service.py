"""Service layer for the Mail app."""

from __future__ import annotations

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
from store import (
    DEFAULT_BODY_HTML_CHARS,
    DEFAULT_BODY_TEXT_CHARS,
    count_threads,
    disconnect_connection,
    get_connection,
    get_attachment,
    get_message,
    get_thread,
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
    "labels.modify",
    "mail_modify_labels",
    "messages.mark_read",
    "mail_mark_read",
    "set_view_filter",
    "set_custom_view",
    "clear_custom_view",
}

ATTACHMENT_GET_ACTIONS = {"attachments.get", "mail_get_attachment"}
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
        if action in {"folders.list", "mail_list_folders"}:
            return 200, {"items": list_folders(data_root, _optional_string(payload.get("connection_id")))}
        if action in {"labels.list", "mail_list_labels"}:
            return 200, {"items": list_labels(data_root, _optional_string(payload.get("connection_id")))}
        if action in {"threads.list", "mail_list_threads", "list"}:
            connection_id = _payload_connection_id(data_root, payload)
            provider = provider_for_connection(data_root, connection_id)
            provider_payload = _threads_list_provider_payload(data_root, payload, connection_id, provider)
            return 200, {
                "items": provider.list_threads(data_root, provider_payload),
                "limit": _bounded_int(payload.get("max_threads") or payload.get("limit"), 50, 1, 200),
                "offset": _bounded_int(payload.get("offset"), 0, 0, 100_000),
                "total_count": count_threads(data_root, provider_payload),
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
                    query=_optional_string(payload.get("query")),
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
                )
            }
        if action in {"messages.send", "mail_send"}:
            connection_id = _payload_connection_id(data_root, payload)
            _require_connected(data_root, connection_id)
            draft = create_draft(data_root, {**payload, "connection_id": connection_id})
            provider = provider_for_connection(data_root, str(draft["connection_id"]))
            result = provider.send_draft(data_root, str(draft["id"]), confirm=bool(payload.get("confirm")), app_secrets=_app_secrets(payload))
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
                ),
            }
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


def _threads_list_provider_payload(
    data_root: Path,
    payload: dict[str, object],
    connection_id: str | None,
    provider: object,
) -> dict[str, object]:
    if _is_disconnected(data_root, connection_id):
        return {**payload, "_app_secrets": {}}
    if (
        connection_id
        and not _optional_string(payload.get("connection_id"))
        and getattr(provider, "provider_id", "") == "gmail"
        and _app_secrets(payload).get("gmail-refresh-token")
    ):
        return {**payload, "connection_id": connection_id}
    return payload


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
    if explicit:
        return _effective_connection_id(data_root, explicit)
    action = str(payload.get("action") or "")
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
