"""Draft and send helpers for Mail."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from database import connect, ensure_schema, now_timestamp
from store import audit, get_thread, list_connections


def create_draft(data_root: Path, payload: dict[str, object]) -> dict[str, object]:
    ensure_schema(data_root)
    connection_id = _required_string(payload.get("connection_id") or _default_connection_id(data_root), "connection_id")
    thread_id = _optional_string(payload.get("thread_id"))
    to_recipients, cc_recipients, bcc_recipients = _draft_recipients(data_root, connection_id, thread_id, payload)
    subject = _required_string(payload.get("subject"), "subject")
    body_text = _required_string(payload.get("body_text"), "body_text")
    now = now_timestamp()
    draft_id = f"mail_draft_{uuid4().hex[:16]}"
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO drafts(id, connection_id, thread_id, to_json, cc_json, bcc_json, subject, body_text, status, dirty, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft_id,
                connection_id,
                thread_id,
                _json_list(to_recipients),
                _json_list(cc_recipients),
                _json_list(bcc_recipients),
                subject,
                body_text,
                "draft",
                1,
                now,
                now,
            ),
        )
    audit(data_root, "draft.create", "mail_draft", draft_id, {"subject": subject})
    return get_draft(data_root, draft_id)


def update_draft(data_root: Path, draft_id: str, payload: dict[str, object]) -> dict[str, object]:
    draft = get_draft(data_root, draft_id)
    to_recipients, cc_recipients, bcc_recipients = _draft_recipients(
        data_root,
        str(draft["connection_id"]),
        _optional_string(draft.get("thread_id")),
        {
            "to": payload.get("to", draft["to"]),
            "cc": payload.get("cc", draft["cc"]),
            "bcc": payload.get("bcc", draft["bcc"]),
        },
    )
    values = {
        "to_json": _json_list(to_recipients),
        "cc_json": _json_list(cc_recipients),
        "bcc_json": _json_list(bcc_recipients),
        "subject": _required_string(payload.get("subject", draft["subject"]), "subject"),
        "body_text": _required_string(payload.get("body_text", draft["body_text"]), "body_text"),
        "updated_at": now_timestamp(),
    }
    with connect(data_root) as db:
        db.execute(
            """
            UPDATE drafts
            SET to_json = ?, cc_json = ?, bcc_json = ?, subject = ?, body_text = ?, dirty = 1, updated_at = ?
            WHERE id = ? AND status != 'sent'
            """,
            (values["to_json"], values["cc_json"], values["bcc_json"], values["subject"], values["body_text"], values["updated_at"], draft_id),
        )
    audit(data_root, "draft.update", "mail_draft", draft_id, {"subject": values["subject"]})
    return get_draft(data_root, draft_id)


def get_draft(data_root: Path, draft_id: str) -> dict[str, object]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    if row is None:
        raise ValueError(f"Draft `{draft_id}` was not found")
    return _draft(row)


def delete_draft(data_root: Path, draft_id: str) -> dict[str, object]:
    get_draft(data_root, draft_id)
    with connect(data_root) as db:
        db.execute("DELETE FROM drafts WHERE id = ? AND status != 'sent'", (draft_id,))
    audit(data_root, "draft.delete", "mail_draft", draft_id, {})
    return {"deleted": True, "id": draft_id}


def search_drafts(data_root: Path, query: str, limit: int = 20) -> list[dict[str, object]]:
    ensure_schema(data_root)
    needle = f"%{query.strip()}%"
    with connect(data_root) as db:
        rows = db.execute(
            """
            SELECT * FROM drafts
            WHERE status != 'sent'
              AND (
                subject LIKE ?
                OR body_text LIKE ?
                OR to_json LIKE ?
                OR cc_json LIKE ?
                OR bcc_json LIKE ?
              )
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (needle, needle, needle, needle, needle, _bounded_int(limit, default=20, minimum=1, maximum=50)),
        ).fetchall()
    return [_draft(row) for row in rows]


def send_draft(data_root: Path, draft_id: str, confirm: bool = False) -> dict[str, object]:
    return local_send_draft(data_root, draft_id, confirm=confirm)


def local_send_draft(data_root: Path, draft_id: str, confirm: bool = False) -> dict[str, object]:
    draft = get_draft(data_root, draft_id)
    _require_recipients(draft)
    if not confirm:
        return {"dry_run": True, "requires_confirmation": True, "draft": draft}
    now = now_timestamp()
    thread_id = draft.get("thread_id") or f"email_thread_{uuid4().hex[:16]}"
    message_id = f"email_message_{uuid4().hex[:16]}"
    connection = _connection_for_draft(data_root, str(draft["connection_id"]))
    sender = {
        "name": str(connection.get("display_name") or connection.get("email_address") or "Mail User"),
        "email": str(connection.get("email_address") or ""),
    }
    with connect(data_root) as db:
        if draft.get("thread_id") is None:
            db.execute(
                """
                INSERT INTO threads(id, connection_id, provider_thread_id, subject, participants_json, last_message_at, snippet, unread, starred, labels_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (thread_id, draft["connection_id"], f"local-{thread_id}", draft["subject"], json.dumps([sender, *draft["to"]], ensure_ascii=True), now, draft["body_text"][:180], 0, 0, '["sent"]', now),
            )
        db.execute(
            """
            INSERT INTO messages(id, thread_id, provider_message_id, sender_json, recipients_json, cc_json, bcc_json, sent_at, body_text, headers_json, has_attachments)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (message_id, thread_id, f"local-{message_id}", json.dumps(sender, ensure_ascii=True), json.dumps(draft["to"], ensure_ascii=True), json.dumps(draft["cc"], ensure_ascii=True), json.dumps(draft["bcc"], ensure_ascii=True), now, draft["body_text"], '{"x-maverick-local-send":"true"}', 0),
        )
        db.execute("UPDATE drafts SET status = 'sent', dirty = 0, sent_at = ?, updated_at = ? WHERE id = ?", (now, now, draft_id))
        db.execute("UPDATE threads SET last_message_at = ?, snippet = ?, updated_at = ? WHERE id = ?", (now, draft["body_text"][:180], now, thread_id))
    audit(data_root, "draft.send", "mail_draft", draft_id, {"thread_id": thread_id, "message_id": message_id})
    return {"sent": True, "thread": get_thread(data_root, thread_id), "message_id": message_id}


def _draft(row) -> dict[str, object]:
    item = dict(row)
    item["to"] = _loads_list(item.pop("to_json"))
    item["cc"] = _loads_list(item.pop("cc_json"))
    item["bcc"] = _loads_list(item.pop("bcc_json"))
    item["dirty"] = bool(item["dirty"])
    item["deep_link"] = f"/app/mail?draft={item['id']}"
    return item


def _loads_list(value: object) -> list[object]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_list(value: object) -> str:
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=True)
    if value in (None, ""):
        return "[]"
    return json.dumps([str(value)], ensure_ascii=True)


def _draft_recipients(
    data_root: Path,
    connection_id: str,
    thread_id: str | None,
    payload: dict[str, object],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    to_recipients = _address_list(payload.get("to"))
    cc_recipients = _address_list(payload.get("cc"))
    bcc_recipients = _address_list(payload.get("bcc"))
    if not _has_any_recipient(to_recipients, cc_recipients, bcc_recipients) and thread_id:
        to_recipients = _reply_recipients(data_root, connection_id, thread_id)
    if not _has_any_recipient(to_recipients, cc_recipients, bcc_recipients):
        raise ValueError("At least one recipient in to, cc, or bcc is required")
    return to_recipients, cc_recipients, bcc_recipients


def _reply_recipients(data_root: Path, connection_id: str, thread_id: str) -> list[dict[str, str]]:
    connection = _connection_for_draft(data_root, connection_id)
    own_email = str(connection.get("email_address") or "").strip().lower()
    thread = get_thread(data_root, thread_id, max_body_chars=200)
    recipients: list[dict[str, str]] = []
    seen: set[str] = set()
    for participant in thread.get("participants", []):
        address = _address(participant)
        email = address.get("email", "").lower()
        if not email or email == own_email or email in seen:
            continue
        seen.add(email)
        recipients.append(address)
    return recipients


def _require_recipients(draft: dict[str, object]) -> None:
    if not _has_any_recipient(
        _address_list(draft.get("to")),
        _address_list(draft.get("cc")),
        _address_list(draft.get("bcc")),
    ):
        raise ValueError("At least one recipient in to, cc, or bcc is required")


def _has_any_recipient(*recipient_groups: list[dict[str, str]]) -> bool:
    return any(address.get("email") for group in recipient_groups for address in group)


def _address_list(value: object) -> list[dict[str, str]]:
    if value in (None, ""):
        return []
    values = value if isinstance(value, list) else [value]
    recipients: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in values:
        address = _address(item)
        email = address.get("email", "").lower()
        if not email or email in seen:
            continue
        seen.add(email)
        recipients.append(address)
    return recipients


def _address(value: object) -> dict[str, str]:
    if isinstance(value, dict):
        email = str(value.get("email") or "").strip()
        name = str(value.get("name") or "").strip()
    else:
        email = str(value or "").strip()
        name = ""
    if not email:
        return {}
    address = {"email": email}
    if name:
        address["name"] = name
    return address


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


def _default_connection_id(data_root: Path) -> str:
    connections = list_connections(data_root)
    if not connections:
        raise ValueError("No mail connection is available")
    return str(connections[0]["id"])


def _connection_for_draft(data_root: Path, connection_id: str) -> dict[str, object]:
    for connection in list_connections(data_root):
        if connection.get("id") == connection_id:
            return connection
    raise ValueError(f"Connection `{connection_id}` was not found")
