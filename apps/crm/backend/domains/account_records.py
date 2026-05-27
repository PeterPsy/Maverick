"""CRM account record mutations."""

from __future__ import annotations

from typing import Any

from store import get_record, metadata, new_id, require_text, upsert_fts, utc_now, write_event


def create_account(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    account_id = require_text(payload, "id") or new_id("acct")
    name = require_text(payload, "name", required=True)
    values = (
        account_id,
        name,
        require_text(payload, "domain"),
        require_text(payload, "industry"),
        require_text(payload, "status", default="prospect") or "prospect",
        require_text(payload, "owner_id"),
        require_text(payload, "summary"),
        metadata(payload),
        now,
        now,
    )
    db.execute(
        """
        INSERT INTO accounts(id, name, domain, industry, status, owner_id, summary, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    upsert_fts(db, "account", account_id, name, " ".join(str(value) for value in values[2:7]))
    write_event(db, "account.created", "account", account_id)
    return get_record(db, "account", account_id)


def update_account(db, payload: dict[str, Any]) -> dict[str, Any]:
    account_id = require_text(payload, "id", required=True)
    current = get_record(db, "account", account_id)
    merged = {**current, **{key: value for key, value in payload.items() if key in {"name", "domain", "industry", "status", "owner_id", "summary", "metadata"}}}
    db.execute(
        """
        UPDATE accounts SET name = ?, domain = ?, industry = ?, status = ?, owner_id = ?, summary = ?, metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            require_text(merged, "name", required=True),
            require_text(merged, "domain"),
            require_text(merged, "industry"),
            require_text(merged, "status", default="prospect"),
            require_text(merged, "owner_id"),
            require_text(merged, "summary"),
            metadata(merged),
            utc_now(),
            account_id,
        ),
    )
    updated = get_record(db, "account", account_id)
    upsert_fts(db, "account", account_id, updated["name"], f"{updated.get('domain', '')} {updated.get('industry', '')} {updated.get('summary', '')}")
    write_event(db, "account.updated", "account", account_id)
    return updated
