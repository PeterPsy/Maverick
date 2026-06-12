"""CRM lead record mutations and conversion."""

from __future__ import annotations

from typing import Any

from domains.account_records import create_account
from domains.contact_records import create_contact
from domains.deal_records import coerce_record_number, create_deal
from domains.record_lifecycle import get_non_deleted_record
from store import delete_fts, get_record, metadata, new_id, require_text, upsert_fts, utc_now, write_event


def create_lead(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    lead_id = require_text(payload, "id") or new_id("lead")
    first_name = require_text(payload, "first_name")
    last_name = require_text(payload, "last_name")
    display_name = require_text(payload, "display_name") or " ".join(part for part in [first_name, last_name] if part) or require_text(payload, "email", required=True)
    values = (
        lead_id,
        first_name,
        last_name,
        display_name,
        require_text(payload, "email"),
        require_text(payload, "phone"),
        require_text(payload, "company"),
        require_text(payload, "domain"),
        require_text(payload, "source"),
        require_text(payload, "status", default="new") or "new",
        require_text(payload, "owner_id"),
        require_text(payload, "summary"),
        metadata(payload),
        now,
        now,
    )
    db.execute(
        """
        INSERT INTO leads(id, first_name, last_name, display_name, email, phone, company, domain, source, status, owner_id, summary, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    record = get_record(db, "lead", lead_id)
    upsert_fts(db, "lead", lead_id, record["display_name"], f"{record.get('email', '')} {record.get('company', '')} {record.get('domain', '')} {record.get('summary', '')}")
    write_event(db, "lead.created", "lead", lead_id)
    return record


def update_lead(db, payload: dict[str, Any]) -> dict[str, Any]:
    lead_id = require_text(payload, "id", required=True)
    current = get_record(db, "lead", lead_id)
    merged = {
        **current,
        **{
            key: value
            for key, value in payload.items()
            if key in {"first_name", "last_name", "display_name", "email", "phone", "company", "domain", "source", "status", "owner_id", "summary", "metadata"}
        },
    }
    display_name = require_text(merged, "display_name") or " ".join(part for part in [require_text(merged, "first_name"), require_text(merged, "last_name")] if part)
    db.execute(
        """
        UPDATE leads SET first_name = ?, last_name = ?, display_name = ?, email = ?, phone = ?, company = ?, domain = ?,
          source = ?, status = ?, owner_id = ?, summary = ?, metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            require_text(merged, "first_name"),
            require_text(merged, "last_name"),
            display_name,
            require_text(merged, "email"),
            require_text(merged, "phone"),
            require_text(merged, "company"),
            require_text(merged, "domain"),
            require_text(merged, "source"),
            require_text(merged, "status", default="new") or "new",
            require_text(merged, "owner_id"),
            require_text(merged, "summary"),
            metadata(merged),
            utc_now(),
            lead_id,
        ),
    )
    record = get_record(db, "lead", lead_id)
    upsert_fts(db, "lead", lead_id, record["display_name"], f"{record.get('email', '')} {record.get('company', '')} {record.get('domain', '')} {record.get('summary', '')}")
    write_event(db, "lead.updated", "lead", lead_id)
    return record


def convert_lead(db, payload: dict[str, Any]) -> dict[str, Any]:
    lead_id = require_text(payload, "id") or require_text(payload, "lead_id", required=True)
    lead = get_record(db, "lead", lead_id)
    if lead.get("converted_at"):
        return {
            "ok": True,
            "lead": lead,
            "account": get_record(db, "account", str(lead["account_id"])) if lead.get("account_id") else None,
            "contact": get_record(db, "contact", str(lead["contact_id"])) if lead.get("contact_id") else None,
            "deal": get_record(db, "deal", str(lead["deal_id"])) if lead.get("deal_id") else None,
        }

    account_id = require_text(payload, "account_id")
    account = get_record(db, "account", account_id) if account_id else create_account(
        db,
        {
            "name": require_text(payload, "account_name") or str(lead.get("company") or lead.get("display_name")),
            "domain": require_text(payload, "domain") or str(lead.get("domain") or ""),
            "status": "prospect",
            "owner_id": require_text(payload, "owner_id") or str(lead.get("owner_id") or ""),
            "summary": str(lead.get("summary") or ""),
            "metadata": {"converted_from_lead_id": lead_id},
        },
    )
    contact_id = require_text(payload, "contact_id")
    contact = get_record(db, "contact", contact_id) if contact_id else create_contact(
        db,
        {
            "account_id": account["id"],
            "first_name": str(lead.get("first_name") or ""),
            "last_name": str(lead.get("last_name") or ""),
            "display_name": str(lead.get("display_name") or ""),
            "email": str(lead.get("email") or ""),
            "phone": str(lead.get("phone") or ""),
            "owner_id": require_text(payload, "owner_id") or str(lead.get("owner_id") or ""),
            "summary": str(lead.get("summary") or ""),
            "metadata": {"converted_from_lead_id": lead_id},
        },
    )
    deal: dict[str, Any] | None = None
    if bool(payload.get("create_deal", True)):
        deal = create_deal(
            db,
            {
                "account_id": account["id"],
                "contact_id": contact["id"],
                "name": require_text(payload, "deal_name") or f"{account['name']} opportunity",
                "stage_id": require_text(payload, "stage_id", default="qualified") or "qualified",
                "value": coerce_record_number(payload, "value", 0),
                "currency": require_text(payload, "currency", default="EUR") or "EUR",
                "close_date": require_text(payload, "close_date"),
                "owner_id": require_text(payload, "owner_id") or str(lead.get("owner_id") or ""),
                "summary": str(lead.get("summary") or ""),
                "metadata": {"converted_from_lead_id": lead_id},
            },
        )
    now = utc_now()
    db.execute(
        """
        UPDATE leads SET status = 'converted', converted_at = ?, account_id = ?, contact_id = ?, deal_id = ?, updated_at = ?
        WHERE id = ?
        """,
        (now, account["id"], contact["id"], deal["id"] if deal else "", now, lead_id),
    )
    delete_fts(db, "lead", lead_id)
    converted = get_non_deleted_record(db, "lead", lead_id)
    write_event(db, "lead.converted", "lead", lead_id, {"account_id": account["id"], "contact_id": contact["id"], "deal_id": deal["id"] if deal else ""})
    return {"ok": True, "lead": converted, "account": account, "contact": contact, "deal": deal}
