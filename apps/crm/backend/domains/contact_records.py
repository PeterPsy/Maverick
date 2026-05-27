"""CRM contact record mutations."""

from __future__ import annotations

from typing import Any

from domains.record_lifecycle import validate_relationships
from store import get_record, metadata, new_id, require_text, upsert_fts, utc_now, write_event


def create_contact(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    contact_id = require_text(payload, "id") or new_id("cont")
    validate_relationships(db, payload, ("account_id",))
    first_name = require_text(payload, "first_name")
    last_name = require_text(payload, "last_name")
    display_name = require_text(payload, "display_name") or " ".join(part for part in [first_name, last_name] if part) or require_text(payload, "email", required=True)
    values = (
        contact_id,
        require_text(payload, "account_id"),
        first_name,
        last_name,
        display_name,
        require_text(payload, "email"),
        require_text(payload, "phone"),
        require_text(payload, "role"),
        require_text(payload, "owner_id"),
        require_text(payload, "summary"),
        metadata(payload),
        now,
        now,
    )
    db.execute(
        """
        INSERT INTO contacts(id, account_id, first_name, last_name, display_name, email, phone, role, owner_id, summary, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    upsert_fts(db, "contact", contact_id, display_name, " ".join(str(value) for value in values[5:10]))
    write_event(db, "contact.created", "contact", contact_id)
    return get_record(db, "contact", contact_id)


def update_contact(db, payload: dict[str, Any]) -> dict[str, Any]:
    contact_id = require_text(payload, "id", required=True)
    current = get_record(db, "contact", contact_id)
    merged = {**current, **{key: value for key, value in payload.items() if key in {"account_id", "first_name", "last_name", "display_name", "email", "phone", "role", "owner_id", "summary", "metadata"}}}
    validate_relationships(db, merged, ("account_id",))
    display_name = require_text(merged, "display_name") or " ".join(part for part in [require_text(merged, "first_name"), require_text(merged, "last_name")] if part)
    db.execute(
        """
        UPDATE contacts SET account_id = ?, first_name = ?, last_name = ?, display_name = ?, email = ?, phone = ?, role = ?, owner_id = ?, summary = ?, metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            require_text(merged, "account_id"),
            require_text(merged, "first_name"),
            require_text(merged, "last_name"),
            display_name,
            require_text(merged, "email"),
            require_text(merged, "phone"),
            require_text(merged, "role"),
            require_text(merged, "owner_id"),
            require_text(merged, "summary"),
            metadata(merged),
            utc_now(),
            contact_id,
        ),
    )
    updated = get_record(db, "contact", contact_id)
    upsert_fts(db, "contact", contact_id, updated["display_name"], f"{updated.get('email', '')} {updated.get('role', '')} {updated.get('summary', '')}")
    write_event(db, "contact.updated", "contact", contact_id)
    return updated
