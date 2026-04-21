"""CRM record write and read operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from database import (
    connect,
    ensure_schema,
    entity_table,
    json_text,
    new_id,
    normalize_activity_type,
    normalize_entity_type,
    normalize_relationship_kind,
    now_timestamp,
    record_event,
    refresh_fts,
    row_payload,
)
from errors import CrmValidationError


def require_text(body: dict[str, Any], key: str) -> str:
    value = " ".join(str(body.get(key) or "").split()).strip()
    if not value:
        raise CrmValidationError(f"{key} is required.")
    return value


def optional_text(body: dict[str, Any], key: str) -> str:
    return " ".join(str(body.get(key) or "").split()).strip()


def create_account(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(data_root)
    timestamp = now_timestamp()
    account = {
        "id": str(body.get("account_id") or body.get("id") or new_id("account")),
        "name": require_text(body, "name")[:240],
        "domain": optional_text(body, "domain")[:240],
        "industry": optional_text(body, "industry")[:160],
        "status": optional_text(body, "status") or "prospect",
        "owner_id": optional_text(body, "owner_id"),
        "summary": str(body.get("summary") or "").strip(),
        "metadata_json": json_text(body.get("metadata")),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO accounts(id, name, domain, industry, status, owner_id, summary, metadata_json, created_at, updated_at)
            VALUES (:id, :name, :domain, :industry, :status, :owner_id, :summary, :metadata_json, :created_at, :updated_at)
            """,
            account,
        )
        refresh_fts(db, entity_type="account", entity_id=account["id"], title=account["name"], body=" ".join([account["domain"], account["industry"], account["summary"]]))
        record_event(db, event_type="account_created", entity_type="account", entity_id=account["id"], payload={"name": account["name"]})
        return get_entity_with_context(db, "account", account["id"])


def create_contact(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(data_root)
    timestamp = now_timestamp()
    first_name = optional_text(body, "first_name")
    last_name = optional_text(body, "last_name")
    display_name = optional_text(body, "display_name") or " ".join(part for part in (first_name, last_name) if part).strip()
    if not display_name:
        raise CrmValidationError("display_name or first_name/last_name is required.")
    contact = {
        "id": str(body.get("contact_id") or body.get("id") or new_id("contact")),
        "account_id": optional_text(body, "account_id"),
        "first_name": first_name[:120],
        "last_name": last_name[:120],
        "display_name": display_name[:240],
        "email": optional_text(body, "email")[:240],
        "phone": optional_text(body, "phone")[:80],
        "role": optional_text(body, "role")[:160],
        "owner_id": optional_text(body, "owner_id"),
        "summary": str(body.get("summary") or "").strip(),
        "metadata_json": json_text(body.get("metadata")),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO contacts(id, account_id, first_name, last_name, display_name, email, phone, role,
              owner_id, summary, metadata_json, created_at, updated_at)
            VALUES (:id, :account_id, :first_name, :last_name, :display_name, :email, :phone, :role,
              :owner_id, :summary, :metadata_json, :created_at, :updated_at)
            """,
            contact,
        )
        refresh_fts(db, entity_type="contact", entity_id=contact["id"], title=contact["display_name"], body=" ".join([contact["email"], contact["phone"], contact["role"], contact["summary"]]))
        record_event(db, event_type="contact_created", entity_type="contact", entity_id=contact["id"], payload={"display_name": contact["display_name"]})
        return get_entity_with_context(db, "contact", contact["id"])


def create_deal(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(data_root)
    timestamp = now_timestamp()
    deal = {
        "id": str(body.get("deal_id") or body.get("id") or new_id("deal")),
        "account_id": optional_text(body, "account_id"),
        "name": require_text(body, "name")[:240],
        "stage": optional_text(body, "stage") or "lead",
        "value": float(body.get("value") or 0),
        "currency": optional_text(body, "currency") or "EUR",
        "probability": float(body.get("probability") or 0),
        "close_date": optional_text(body, "close_date"),
        "owner_id": optional_text(body, "owner_id"),
        "summary": str(body.get("summary") or "").strip(),
        "metadata_json": json_text(body.get("metadata")),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO deals(id, account_id, name, stage, value, currency, probability, close_date,
              owner_id, summary, metadata_json, created_at, updated_at)
            VALUES (:id, :account_id, :name, :stage, :value, :currency, :probability, :close_date,
              :owner_id, :summary, :metadata_json, :created_at, :updated_at)
            """,
            deal,
        )
        refresh_fts(db, entity_type="deal", entity_id=deal["id"], title=deal["name"], body=" ".join([deal["stage"], deal["currency"], deal["close_date"], deal["summary"]]))
        record_event(db, event_type="deal_created", entity_type="deal", entity_id=deal["id"], payload={"name": deal["name"]})
        return get_entity_with_context(db, "deal", deal["id"])


def add_activity(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(data_root)
    timestamp = now_timestamp()
    activity = {
        "id": str(body.get("activity_id") or body.get("id") or new_id("activity")),
        "activity_type": normalize_activity_type(str(body.get("activity_type") or body.get("type") or "note")),
        "subject": require_text(body, "subject")[:240],
        "body": str(body.get("body") or "").strip(),
        "account_id": optional_text(body, "account_id"),
        "contact_id": optional_text(body, "contact_id"),
        "deal_id": optional_text(body, "deal_id"),
        "occurred_at": optional_text(body, "occurred_at") or timestamp,
        "owner_id": optional_text(body, "owner_id"),
        "metadata_json": json_text(body.get("metadata")),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO activities(id, activity_type, subject, body, account_id, contact_id, deal_id,
              occurred_at, owner_id, metadata_json, created_at, updated_at)
            VALUES (:id, :activity_type, :subject, :body, :account_id, :contact_id, :deal_id,
              :occurred_at, :owner_id, :metadata_json, :created_at, :updated_at)
            """,
            activity,
        )
        refresh_fts(db, entity_type="activity", entity_id=activity["id"], title=activity["subject"], body=activity["body"])
        record_event(db, event_type="activity_created", entity_type="activity", entity_id=activity["id"], payload={"subject": activity["subject"]})
        return get_entity_with_context(db, "activity", activity["id"])


def link_entities(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    ensure_schema(data_root)
    source_type = normalize_entity_type(str(body.get("source_type") or ""))
    target_type = normalize_entity_type(str(body.get("target_type") or ""))
    source_id = optional_text(body, "source_id")
    target_id = optional_text(body, "target_id")
    if not source_id or not target_id:
        raise CrmValidationError("source_id and target_id are required.")
    timestamp = now_timestamp()
    relationship = {
        "id": str(body.get("relationship_id") or body.get("id") or new_id("rel")),
        "source_type": source_type,
        "source_id": source_id,
        "target_type": target_type,
        "target_id": target_id,
        "kind": normalize_relationship_kind(str(body.get("kind") or "related_to")),
        "strength": float(body.get("strength") or 0.5),
        "reason": str(body.get("reason") or "").strip(),
        "metadata_json": json_text(body.get("metadata")),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    with connect(data_root) as db:
        for entity_type, entity_id in ((source_type, source_id), (target_type, target_id)):
            if get_entity(db, entity_type, entity_id) is None:
                raise CrmValidationError(f"{entity_type} `{entity_id}` not found.")
        db.execute(
            """
            INSERT INTO relationships(id, source_type, source_id, target_type, target_id, kind, strength,
              reason, metadata_json, created_at, updated_at)
            VALUES (:id, :source_type, :source_id, :target_type, :target_id, :kind, :strength,
              :reason, :metadata_json, :created_at, :updated_at)
            """,
            relationship,
        )
        record_event(db, event_type="relationship_created", entity_type=source_type, entity_id=source_id, payload=relationship)
        return row_payload(db.execute("SELECT * FROM relationships WHERE id = ?", (relationship["id"],)).fetchone()) or {}


def get_entity(db, entity_type: str, entity_id: str) -> dict[str, Any] | None:
    table = entity_table(entity_type)
    row = db.execute(f"SELECT * FROM {table} WHERE id = ? AND deleted_at IS NULL", (entity_id,)).fetchone()
    return row_payload(row)


def get_entity_with_context(db, entity_type: str, entity_id: str) -> dict[str, Any]:
    entity = get_entity(db, entity_type, entity_id)
    if entity is None:
        raise CrmValidationError("entity not found.")
    entity["relationships"] = [
        row_payload(row) or {}
        for row in db.execute(
            """
            SELECT * FROM relationships
            WHERE deleted_at IS NULL AND ((source_type = ? AND source_id = ?) OR (target_type = ? AND target_id = ?))
            ORDER BY strength DESC, updated_at DESC
            """,
            (entity_type, entity_id, entity_type, entity_id),
        )
    ]
    return entity


def inspect_entity(data_root: Path, entity_type: str, entity_id: str) -> dict[str, Any]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        return get_entity_with_context(db, normalize_entity_type(entity_type), str(entity_id or "").strip())
