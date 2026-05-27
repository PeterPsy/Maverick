"""CRM record mutation facade."""

from __future__ import annotations

from typing import Any

from errors import ValidationError
from domains.account_records import create_account, update_account
from domains.contact_records import create_contact, update_contact
from domains.deal_records import create_deal, update_deal
from domains.engagement_records import (
    create_note,
    create_task,
    log_activity,
    update_note,
    update_task,
)
from domains.lead_records import convert_lead, create_lead, update_lead


def _update_entity_record(db, entity_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if entity_type == "lead":
        return update_lead(db, payload)
    if entity_type == "account":
        return update_account(db, payload)
    if entity_type == "contact":
        return update_contact(db, payload)
    if entity_type == "deal":
        return update_deal(db, payload)
    if entity_type == "task":
        return update_task(db, payload)
    if entity_type == "note":
        return update_note(db, payload)
    raise ValidationError("Bulk update supports lead, account, contact, deal, task, and note.", details={"entity_type": entity_type})


__all__ = [
    "_update_entity_record",
    "convert_lead",
    "create_account",
    "create_contact",
    "create_deal",
    "create_lead",
    "create_note",
    "create_task",
    "log_activity",
    "update_account",
    "update_contact",
    "update_deal",
    "update_lead",
    "update_note",
    "update_task",
]
