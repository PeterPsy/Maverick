"""Reference entity helpers for Mail."""

from __future__ import annotations

from pathlib import Path

from drafts import get_draft, search_drafts
from store import get_attachment, get_message, get_thread, list_connections, list_threads, search_messages


def reference_manifest() -> dict[str, object]:
    return {
        "entity_types": [
            {"entity_type": "mail_connection", "display_name": "Mail Connection", "searchable": True, "resolvable": True, "summarizable": True, "deep_link_supported": True},
            {"entity_type": "email_thread", "display_name": "Email Thread", "searchable": True, "resolvable": True, "summarizable": True, "deep_link_supported": True},
            {"entity_type": "email_message", "display_name": "Email Message", "searchable": True, "resolvable": True, "summarizable": True, "deep_link_supported": True},
            {"entity_type": "mail_attachment", "display_name": "Mail Attachment", "searchable": False, "resolvable": True, "summarizable": True, "deep_link_supported": True},
            {"entity_type": "mail_draft", "display_name": "Mail Draft", "searchable": True, "resolvable": True, "summarizable": True, "deep_link_supported": True},
        ]
    }


def reference_search(data_root: Path, query: str, limit: int = 20) -> list[dict[str, object]]:
    query = query.strip()
    items: list[dict[str, object]] = []
    for thread in list_threads(data_root, {"query": query, "limit": limit}):
        items.append(_reference("email_thread", thread["id"], thread["subject"], thread["snippet"], f"/app/mail?thread={thread['id']}"))
    for message in search_messages(data_root, query, limit=limit):
        items.append(_reference("email_message", message["id"], str(message.get("subject") or "Message"), message["body_text"], f"/app/mail?message={message['id']}"))
    for connection in list_connections(data_root):
        haystack = f"{connection['display_name']} {connection['email_address']}".lower()
        if not query or query.lower() in haystack:
            items.append(_reference("mail_connection", connection["id"], connection["display_name"], connection["email_address"], f"/app/mail?connection={connection['id']}"))
    for draft in search_drafts(data_root, query, limit=limit):
        items.append(_reference("mail_draft", draft["id"], draft["subject"], draft["body_text"], f"/app/mail?draft={draft['id']}"))
    return items[: _bounded_int(limit, default=20, minimum=1, maximum=50)]


def reference_resolve(data_root: Path, entity_type: str, entity_id: str) -> dict[str, object]:
    if entity_type == "email_thread":
        thread = get_thread(data_root, entity_id, max_body_chars=1200)
        return _reference("email_thread", thread["id"], thread["subject"], thread["snippet"], f"/app/mail?thread={thread['id']}", thread)
    if entity_type == "email_message":
        message = get_message(data_root, entity_id, max_body_chars=1200)
        return _reference("email_message", message["id"], str(message.get("subject") or "Message"), message["body_text"], f"/app/mail?message={message['id']}", message)
    if entity_type == "mail_attachment":
        attachment = get_attachment(data_root, entity_id)
        return _reference(
            "mail_attachment",
            attachment["id"],
            attachment["filename"],
            f"{attachment['content_type']} {attachment['size_bytes']} bytes {attachment['storage_state']}",
            f"/app/mail?attachment={attachment['id']}",
            attachment,
        )
    if entity_type == "mail_connection":
        connection = next((item for item in list_connections(data_root) if item["id"] == entity_id), None)
        if connection is None:
            raise ValueError(f"Connection `{entity_id}` was not found")
        return _reference("mail_connection", connection["id"], connection["display_name"], connection["email_address"], f"/app/mail?connection={connection['id']}", connection)
    if entity_type == "mail_draft":
        draft = get_draft(data_root, entity_id)
        return _reference("mail_draft", draft["id"], draft["subject"], draft["body_text"], f"/app/mail?draft={draft['id']}", draft)
    raise ValueError(f"Unsupported entity_type `{entity_type}`")


def reference_summary(data_root: Path, entity_type: str, entity_id: str, max_chars: int = 1200) -> dict[str, object]:
    resolved = reference_resolve(data_root, entity_type, entity_id)
    return {
        "entity_type": resolved["entity_type"],
        "entity_id": resolved["entity_id"],
        "title": resolved["title"],
        "summary": str(resolved["summary"])[: _bounded_int(max_chars, default=1200, minimum=200, maximum=4000)],
        "deep_link": resolved["deep_link"],
    }


def _reference(entity_type: str, entity_id: object, title: object, summary: object, deep_link: str, data: object | None = None) -> dict[str, object]:
    text_id = str(entity_id)
    payload = {"entity_type": entity_type, "entity_id": text_id, "id": text_id, "title": str(title), "summary": str(summary)[:1200], "deep_link": deep_link}
    if data is not None:
        payload["data"] = data
    return payload


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))
