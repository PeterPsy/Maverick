"""CRM service actions shared by backend, CLI, MCP, and hooks."""

from __future__ import annotations

import csv
from io import StringIO
import json
from pathlib import Path
import sqlite3
from typing import Any

from errors import NotFoundError, ValidationError
from store import (
    connect,
    count_tables,
    export_payload,
    get_record,
    initialize,
    list_rows,
    metadata,
    new_id,
    parse_limit,
    require_text,
    row_to_dict,
    table_for_entity,
    upsert_fts,
    utc_now,
    write_event,
)


WRITE_ACTIONS = {
    "crm.create_account",
    "create_account",
    "crm.update_account",
    "update_account",
    "crm.create_contact",
    "create_contact",
    "crm.update_contact",
    "update_contact",
    "crm.create_deal",
    "create_deal",
    "crm.update_deal",
    "update_deal",
    "crm.move_deal",
    "move_deal",
    "crm.log_activity",
    "log_activity",
    "crm.create_task",
    "create_task",
    "crm.update_task",
    "update_task",
    "crm.create_note",
    "create_note",
    "crm.update_note",
    "update_note",
    "crm.import_commit",
    "import_commit",
    "crm.set_view_filter",
    "set_view_filter",
    "crm.set_custom_view",
    "set_custom_view",
    "crm.clear_custom_view",
    "clear_custom_view",
}

ENTITY_TABLES = {
    "account": "accounts",
    "contact": "contacts",
    "deal": "deals",
    "activity": "activities",
    "task": "tasks",
    "note": "notes",
}
TABLE_ENTITY_TYPES = {table: entity_type for entity_type, table in ENTITY_TABLES.items()}
ENTITY_ROUTE_SEGMENTS = {
    "account": "accounts",
    "contact": "contacts",
    "deal": "deals",
    "activity": "activities",
    "task": "tasks",
    "note": "notes",
}
EXPORT_ENTITY_ORDER = ["accounts", "contacts", "deals", "activities", "tasks", "notes"]
VIEW_ENTITY_TYPES = {"all", "account", "contact", "deal", "activity", "task", "note"}


def app_events_for_action(action: str) -> list[dict[str, str]]:
    if action in WRITE_ACTIONS:
        resource = "view-state" if "view" in action or "custom_view" in action else "records"
        return [{"type": "maverick.app.data-changed", "owner_app_id": "crm", "resource": resource}]
    return []


def handle_action(data_root: str | Path, action: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    initialize(data_root)
    try:
        with connect(data_root) as db:
            if action in {"operations.manifest", "crm.manifest"}:
                return 200, operations_manifest()
            if action in {"health", "crm.health"}:
                return 200, {"ok": True, "status": "healthy", "counts": count_tables(db, ["accounts", "contacts", "deals", "activities", "tasks", "notes"])}
            if action in {"bootstrap", "crm.bootstrap"}:
                return 200, bootstrap_payload(db, data_root)
            if action in {"crm.search", "search"}:
                return 200, search(db, payload)
            if action in {"crm.get_record", "get_record"}:
                return 200, {"record": get_record(db, require_text(payload, "entity_type", required=True), require_text(payload, "id", required=True))}
            if action in {"crm.create_account", "create_account"}:
                return 201, {"account": create_account(db, payload)}
            if action in {"crm.update_account", "update_account"}:
                return 200, {"account": update_account(db, payload)}
            if action in {"crm.create_contact", "create_contact"}:
                return 201, {"contact": create_contact(db, payload)}
            if action in {"crm.update_contact", "update_contact"}:
                return 200, {"contact": update_contact(db, payload)}
            if action in {"crm.create_deal", "create_deal"}:
                return 201, {"deal": create_deal(db, payload)}
            if action in {"crm.update_deal", "update_deal"}:
                return 200, {"deal": update_deal(db, payload)}
            if action in {"crm.move_deal", "move_deal"}:
                return 200, {"deal": move_deal(db, payload)}
            if action in {"crm.log_activity", "log_activity"}:
                return 201, {"activity": log_activity(db, payload)}
            if action in {"crm.create_task", "create_task"}:
                return 201, {"task": create_task(db, payload)}
            if action in {"crm.update_task", "update_task"}:
                return 200, {"task": update_task(db, payload)}
            if action in {"crm.create_note", "create_note"}:
                return 201, {"note": create_note(db, payload)}
            if action in {"crm.update_note", "update_note"}:
                return 200, {"note": update_note(db, payload)}
            if action in {"crm.list_next_actions", "list_next_actions"}:
                return 200, {"tasks": list_rows(db, "tasks", limit=parse_limit(payload), query=require_text(payload, "query"))}
            if action in {"crm.summarize_account", "summarize_account"}:
                return 200, summarize_account(db, require_text(payload, "account_id", required=True))
            if action in {"crm.import_preview", "import_preview"}:
                return 200, import_preview(payload)
            if action in {"crm.import_commit", "import_commit"}:
                return 200, import_commit(db, payload)
            if action in {"crm.export", "export"}:
                return 200, {"ok": True, "export": export_payload(db)}
            if action in {"crm_reference_manifest", "references.manifest"}:
                return 200, reference_manifest()
            if action in {"crm_reference_search", "references.search"}:
                return 200, reference_search(db, payload)
            if action in {"crm_reference_resolve", "references.resolve"}:
                return 200, reference_resolve(db, payload)
            if action in {"crm_reference_summarize", "references.summarize"}:
                return 200, reference_summarize(db, payload)
            if action in {"view_filter", "crm.view_filter"}:
                return 200, {"state": read_view_state(data_root)}
            if action in {"set_view_filter", "crm.set_view_filter"}:
                return 200, {"state": write_view_state(data_root, {"mode": "search", "query": require_text(payload, "query"), "entity_type": view_entity_type(payload), "refs": [], "title": "", "updated_at": utc_now()})}
            if action in {"set_custom_view", "crm.set_custom_view"}:
                refs = payload.get("refs") or []
                if not isinstance(refs, list):
                    raise ValidationError("`refs` must be an array.")
                return 200, {"state": write_view_state(data_root, {"mode": "custom", "query": "", "entity_type": "all", "refs": refs, "title": require_text(payload, "title"), "updated_at": utc_now()})}
            if action in {"clear_custom_view", "crm.clear_custom_view"}:
                return 200, {"state": write_view_state(data_root, {"mode": "search", "query": "", "entity_type": "all", "refs": [], "title": "", "updated_at": utc_now()})}
            raise ValidationError(f"Unsupported action `{action}`.")
    except sqlite3.IntegrityError as error:
        raise ValidationError("CRM record violates a uniqueness or integrity constraint.", details={"reason": str(error)}) from error


def operations_manifest() -> dict[str, Any]:
    return {
        "ok": True,
        "app_id": "crm",
        "default_action": "operations.manifest",
        "entities": ["account", "contact", "deal", "activity", "task", "note"],
        "actions": [
            "crm.search",
            "crm.get_record",
            "crm.create_contact",
            "crm.update_contact",
            "crm.create_account",
            "crm.update_account",
            "crm.create_deal",
            "crm.update_deal",
            "crm.move_deal",
            "crm.log_activity",
            "crm.create_task",
            "crm.update_task",
            "crm.create_note",
            "crm.update_note",
            "crm.list_next_actions",
            "crm.summarize_account",
            "crm.import_preview",
            "crm.import_commit",
            "crm.export",
            "crm.health",
            "crm.view_filter",
            "crm.set_view_filter",
            "crm.set_custom_view",
            "crm.clear_custom_view",
            "crm_reference_manifest",
            "crm_reference_search",
            "crm_reference_resolve",
            "crm_reference_summarize",
        ],
    }


def view_entity_type(payload: dict[str, Any]) -> str:
    entity_type = require_text(payload, "entity_type", default="all") or "all"
    if entity_type not in VIEW_ENTITY_TYPES:
        raise ValidationError("Unsupported CRM view entity_type.", details={"entity_type": entity_type})
    return entity_type


def bootstrap_payload(db, data_root: str | Path) -> dict[str, Any]:
    view_state = read_view_state(data_root)
    payload = {
        "ok": True,
        "accounts": list_rows(db, "accounts", limit=100),
        "contacts": list_rows(db, "contacts", limit=100),
        "deals": list_rows(db, "deals", limit=100),
        "tasks": list_rows(db, "tasks", limit=50),
        "notes": list_rows(db, "notes", limit=50),
        "activities": list_rows(db, "activities", limit=50),
        "pipelines": [row_to_dict(row) for row in db.execute("SELECT * FROM pipelines ORDER BY name").fetchall()],
        "pipeline_stages": [row_to_dict(row) for row in db.execute("SELECT * FROM pipeline_stages ORDER BY position").fetchall()],
        "counts": count_tables(db, ["accounts", "contacts", "deals", "activities", "tasks", "notes"]),
        "view_state": view_state,
    }
    _hydrate_custom_view_records(db, payload, view_state)
    return payload


def _hydrate_custom_view_records(db, payload: dict[str, Any], view_state: dict[str, Any]) -> None:
    view_filter = view_state.get("view_filter") if isinstance(view_state, dict) else {}
    if not isinstance(view_filter, dict) or view_filter.get("mode") != "custom":
        return
    refs = view_filter.get("refs") or []
    if not isinstance(refs, list):
        return
    for ref in refs:
        parsed = _parse_view_ref(ref)
        if parsed is None:
            continue
        entity_type, entity_id = parsed
        table = ENTITY_TABLES.get(entity_type)
        if not table:
            continue
        try:
            record = get_record(db, entity_type, entity_id)
        except NotFoundError:
            continue
        existing_ids = {str(item.get("id")) for item in payload.get(table, []) if isinstance(item, dict)}
        if record["id"] not in existing_ids:
            payload.setdefault(table, []).append(record)


def _parse_view_ref(ref: Any) -> tuple[str, str] | None:
    if not isinstance(ref, dict):
        return None
    entity_type = str(ref.get("entity_type") or "").strip()
    raw_id = str(ref.get("entity_id") or ref.get("id") or "").strip()
    if not entity_type or not raw_id:
        return None
    entity_id = raw_id.split(":", 1)[1] if ":" in raw_id else raw_id
    return entity_type, entity_id


def search(db, payload: dict[str, Any]) -> dict[str, Any]:
    query = require_text(payload, "query")
    entity_type = require_text(payload, "entity_type", default="all") or "all"
    limit = parse_limit(payload, 25)
    if not query:
        tables = list(ENTITY_TABLES.values()) if entity_type == "all" else [table_for_entity(entity_type)]
        return {"results": [{"entity_type": TABLE_ENTITY_TYPES[table], "record": item} for table in tables for item in list_rows(db, table, limit=limit)]}
    pattern = f"{query}*"
    where = ""
    params: list[Any] = [pattern]
    if entity_type != "all":
        where = " AND entity_type = ?"
        params.append(entity_type)
    params.append(limit)
    rows = db.execute(
        f"SELECT entity_type, entity_id, title, body FROM crm_fts WHERE crm_fts MATCH ?{where} LIMIT ?",
        params,
    ).fetchall()
    return {"results": [dict(row) for row in rows]}


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


def create_contact(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    contact_id = require_text(payload, "id") or new_id("cont")
    _validate_relationships(db, payload, ("account_id",))
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
    _validate_relationships(db, merged, ("account_id",))
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


def create_deal(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    deal_id = require_text(payload, "id") or new_id("deal")
    _validate_relationships(db, payload, ("account_id", "contact_id"))
    pipeline_id = require_text(payload, "pipeline_id", default="pipeline_default") or "pipeline_default"
    _require_pipeline(db, pipeline_id)
    stage_id = require_text(payload, "stage_id", default=require_text(payload, "stage", default="lead")) or "lead"
    stage = _stage_name(db, stage_id, pipeline_id)
    probability = float(payload.get("probability") or _stage_probability(db, stage_id, pipeline_id))
    value = float(payload.get("value") or 0)
    db.execute(
        """
        INSERT INTO deals(id, account_id, contact_id, pipeline_id, stage_id, name, stage, value, currency, probability, close_date, owner_id, summary, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            deal_id,
            require_text(payload, "account_id"),
            require_text(payload, "contact_id"),
            pipeline_id,
            stage_id,
            require_text(payload, "name", required=True),
            stage,
            value,
            require_text(payload, "currency", default="EUR") or "EUR",
            probability,
            require_text(payload, "close_date"),
            require_text(payload, "owner_id"),
            require_text(payload, "summary"),
            metadata(payload),
            now,
            now,
        ),
    )
    record = get_record(db, "deal", deal_id)
    upsert_fts(db, "deal", deal_id, record["name"], f"{record.get('stage', '')} {record.get('summary', '')}")
    write_event(db, "deal.created", "deal", deal_id)
    return record


def update_deal(db, payload: dict[str, Any]) -> dict[str, Any]:
    deal_id = require_text(payload, "id", required=True)
    current = get_record(db, "deal", deal_id)
    merged = {**current, **{key: value for key, value in payload.items() if key in {"account_id", "contact_id", "pipeline_id", "stage_id", "name", "value", "currency", "probability", "close_date", "owner_id", "summary", "metadata"}}}
    return _write_deal_update(db, deal_id, merged, "deal.updated")


def move_deal(db, payload: dict[str, Any]) -> dict[str, Any]:
    deal_id = require_text(payload, "id", required=True)
    stage_id = require_text(payload, "stage_id", required=True)
    current = get_record(db, "deal", deal_id)
    pipeline_id = require_text(current, "pipeline_id", default="pipeline_default") or "pipeline_default"
    merged = {**current, "stage_id": stage_id, "stage": _stage_name(db, stage_id, pipeline_id), "probability": _stage_probability(db, stage_id, pipeline_id)}
    return _write_deal_update(db, deal_id, merged, "deal.moved")


def _write_deal_update(db, deal_id: str, values: dict[str, Any], event_type: str) -> dict[str, Any]:
    _validate_relationships(db, values, ("account_id", "contact_id"))
    pipeline_id = require_text(values, "pipeline_id", default="pipeline_default") or "pipeline_default"
    _require_pipeline(db, pipeline_id)
    stage_id = require_text(values, "stage_id", default=require_text(values, "stage", default="lead")) or "lead"
    stage = _stage_name(db, stage_id, pipeline_id)
    db.execute(
        """
        UPDATE deals SET account_id = ?, contact_id = ?, pipeline_id = ?, stage_id = ?, name = ?, stage = ?, value = ?, currency = ?,
          probability = ?, close_date = ?, owner_id = ?, summary = ?, metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            require_text(values, "account_id"),
            require_text(values, "contact_id"),
            pipeline_id,
            stage_id,
            require_text(values, "name", required=True),
            stage,
            float(values.get("value") or 0),
            require_text(values, "currency", default="EUR") or "EUR",
            float(values.get("probability") or _stage_probability(db, stage_id, pipeline_id)),
            require_text(values, "close_date"),
            require_text(values, "owner_id"),
            require_text(values, "summary"),
            metadata(values),
            utc_now(),
            deal_id,
        ),
    )
    record = get_record(db, "deal", deal_id)
    upsert_fts(db, "deal", deal_id, record["name"], f"{record.get('stage', '')} {record.get('summary', '')}")
    write_event(db, event_type, "deal", deal_id, {"stage_id": stage_id})
    return record


def log_activity(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    activity_id = require_text(payload, "id") or new_id("act")
    _validate_relationships(db, payload, ("account_id", "contact_id", "deal_id"))
    db.execute(
        """
        INSERT INTO activities(id, activity_type, subject, body, account_id, contact_id, deal_id, occurred_at, due_at, completed_at, owner_id, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            activity_id,
            require_text(payload, "activity_type", default="note") or "note",
            require_text(payload, "subject", required=True),
            require_text(payload, "body"),
            require_text(payload, "account_id"),
            require_text(payload, "contact_id"),
            require_text(payload, "deal_id"),
            require_text(payload, "occurred_at", default=now) or now,
            require_text(payload, "due_at"),
            require_text(payload, "completed_at"),
            require_text(payload, "owner_id"),
            metadata(payload),
            now,
            now,
        ),
    )
    record = get_record(db, "activity", activity_id)
    upsert_fts(db, "activity", activity_id, record["subject"], f"{record.get('body', '')} {record.get('activity_type', '')}")
    write_event(db, "activity.logged", "activity", activity_id)
    return record


def _update_activity(db, payload: dict[str, Any]) -> dict[str, Any]:
    activity_id = require_text(payload, "id", required=True)
    current = get_record(db, "activity", activity_id)
    merged = {**current, **{key: value for key, value in payload.items() if key in {"activity_type", "subject", "body", "account_id", "contact_id", "deal_id", "occurred_at", "due_at", "completed_at", "owner_id", "metadata"}}}
    _validate_relationships(db, merged, ("account_id", "contact_id", "deal_id"))
    db.execute(
        """
        UPDATE activities SET activity_type = ?, subject = ?, body = ?, account_id = ?, contact_id = ?, deal_id = ?,
          occurred_at = ?, due_at = ?, completed_at = ?, owner_id = ?, metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            require_text(merged, "activity_type", default="note") or "note",
            require_text(merged, "subject", required=True),
            require_text(merged, "body"),
            require_text(merged, "account_id"),
            require_text(merged, "contact_id"),
            require_text(merged, "deal_id"),
            require_text(merged, "occurred_at", default=utc_now()) or utc_now(),
            require_text(merged, "due_at"),
            require_text(merged, "completed_at"),
            require_text(merged, "owner_id"),
            metadata(merged),
            utc_now(),
            activity_id,
        ),
    )
    record = get_record(db, "activity", activity_id)
    upsert_fts(db, "activity", activity_id, record["subject"], f"{record.get('body', '')} {record.get('activity_type', '')}")
    write_event(db, "activity.updated", "activity", activity_id)
    return record


def create_task(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    task_id = require_text(payload, "id") or new_id("task")
    _validate_relationships(db, payload, ("account_id", "contact_id", "deal_id"))
    db.execute(
        """
        INSERT INTO tasks(id, title, status, priority, due_at, account_id, contact_id, deal_id, owner_id, body, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            require_text(payload, "title", required=True),
            require_text(payload, "status", default="open") or "open",
            require_text(payload, "priority", default="normal") or "normal",
            require_text(payload, "due_at"),
            require_text(payload, "account_id"),
            require_text(payload, "contact_id"),
            require_text(payload, "deal_id"),
            require_text(payload, "owner_id"),
            require_text(payload, "body"),
            metadata(payload),
            now,
            now,
        ),
    )
    record = get_record(db, "task", task_id)
    upsert_fts(db, "task", task_id, record["title"], f"{record.get('body', '')} {record.get('status', '')} {record.get('priority', '')}")
    write_event(db, "task.created", "task", task_id)
    return record


def update_task(db, payload: dict[str, Any]) -> dict[str, Any]:
    task_id = require_text(payload, "id", required=True)
    current = get_record(db, "task", task_id)
    merged = {**current, **{key: value for key, value in payload.items() if key in {"title", "status", "priority", "due_at", "account_id", "contact_id", "deal_id", "owner_id", "body", "metadata"}}}
    _validate_relationships(db, merged, ("account_id", "contact_id", "deal_id"))
    db.execute(
        """
        UPDATE tasks SET title = ?, status = ?, priority = ?, due_at = ?, account_id = ?, contact_id = ?, deal_id = ?,
          owner_id = ?, body = ?, metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            require_text(merged, "title", required=True),
            require_text(merged, "status", default="open") or "open",
            require_text(merged, "priority", default="normal") or "normal",
            require_text(merged, "due_at"),
            require_text(merged, "account_id"),
            require_text(merged, "contact_id"),
            require_text(merged, "deal_id"),
            require_text(merged, "owner_id"),
            require_text(merged, "body"),
            metadata(merged),
            utc_now(),
            task_id,
        ),
    )
    record = get_record(db, "task", task_id)
    upsert_fts(db, "task", task_id, record["title"], f"{record.get('body', '')} {record.get('status', '')} {record.get('priority', '')}")
    write_event(db, "task.updated", "task", task_id)
    return record


def create_note(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    note_id = require_text(payload, "id") or new_id("note")
    _validate_relationships(db, payload, ("account_id", "contact_id", "deal_id"))
    body = require_text(payload, "body", required=True)
    db.execute(
        """
        INSERT INTO notes(id, body, account_id, contact_id, deal_id, owner_id, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            note_id,
            body,
            require_text(payload, "account_id"),
            require_text(payload, "contact_id"),
            require_text(payload, "deal_id"),
            require_text(payload, "owner_id"),
            metadata(payload),
            now,
            now,
        ),
    )
    record = get_record(db, "note", note_id)
    upsert_fts(db, "note", note_id, _note_title(record), body)
    write_event(db, "note.created", "note", note_id)
    return record


def update_note(db, payload: dict[str, Any]) -> dict[str, Any]:
    note_id = require_text(payload, "id", required=True)
    current = get_record(db, "note", note_id)
    merged = {**current, **{key: value for key, value in payload.items() if key in {"body", "account_id", "contact_id", "deal_id", "owner_id", "metadata"}}}
    _validate_relationships(db, merged, ("account_id", "contact_id", "deal_id"))
    db.execute(
        """
        UPDATE notes SET body = ?, account_id = ?, contact_id = ?, deal_id = ?, owner_id = ?, metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            require_text(merged, "body", required=True),
            require_text(merged, "account_id"),
            require_text(merged, "contact_id"),
            require_text(merged, "deal_id"),
            require_text(merged, "owner_id"),
            metadata(merged),
            utc_now(),
            note_id,
        ),
    )
    record = get_record(db, "note", note_id)
    upsert_fts(db, "note", note_id, _note_title(record), record["body"])
    write_event(db, "note.updated", "note", note_id)
    return record


def summarize_account(db, account_id: str) -> dict[str, Any]:
    account = get_record(db, "account", account_id)
    contacts = [row_to_dict(row) for row in db.execute("SELECT * FROM contacts WHERE account_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 10", (account_id,)).fetchall()]
    deals = [row_to_dict(row) for row in db.execute("SELECT * FROM deals WHERE account_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 10", (account_id,)).fetchall()]
    activities = [row_to_dict(row) for row in db.execute("SELECT * FROM activities WHERE account_id = ? AND deleted_at IS NULL ORDER BY occurred_at DESC LIMIT 10", (account_id,)).fetchall()]
    tasks = [row_to_dict(row) for row in db.execute("SELECT * FROM tasks WHERE account_id = ? AND deleted_at IS NULL ORDER BY due_at ASC, updated_at DESC LIMIT 10", (account_id,)).fetchall()]
    notes = [row_to_dict(row) for row in db.execute("SELECT * FROM notes WHERE account_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 10", (account_id,)).fetchall()]
    return {"account": account, "contacts": contacts, "deals": deals, "activities": activities, "tasks": tasks, "notes": notes}


def import_preview(payload: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_import_payload(payload)
    if _looks_like_export_payload(payload):
        counts = {table: len(payload.get(table) or []) for table in EXPORT_ENTITY_ORDER}
        return {"ok": True, "format": "crm_export", "counts": counts, "row_count": sum(counts.values()), "sample": {table: (payload.get(table) or [])[:3] for table in EXPORT_ENTITY_ORDER}, "warnings": []}
    entity_type = require_text(payload, "entity_type", default="contact") or "contact"
    rows = _read_import_rows(payload)
    return {"ok": True, "entity_type": entity_type, "row_count": len(rows), "sample": rows[:10], "warnings": []}


def import_commit(db, payload: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_import_payload(payload)
    if _looks_like_export_payload(payload):
        return _import_export_payload(db, payload)
    entity_type = require_text(payload, "entity_type", default="contact") or "contact"
    rows = _read_import_rows(payload)
    created: list[dict[str, Any]] = []
    for row in rows:
        if entity_type == "account":
            created.append(create_account(db, row))
        elif entity_type == "contact":
            created.append(create_contact(db, row))
        elif entity_type == "deal":
            created.append(create_deal(db, row))
        elif entity_type == "activity":
            created.append(log_activity(db, row))
        elif entity_type == "task":
            created.append(create_task(db, row))
        elif entity_type == "note":
            created.append(create_note(db, row))
        else:
            raise ValidationError("Imports support account, contact, deal, activity, task, and note.", details={"entity_type": entity_type})
    return {"ok": True, "entity_type": entity_type, "created_count": len(created), "records": created}


def _normalize_import_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("export"), dict):
        return payload["export"]
    if isinstance(payload.get("payload"), dict):
        return _normalize_import_payload(payload["payload"])
    return payload


def _looks_like_export_payload(payload: dict[str, Any]) -> bool:
    return any(isinstance(payload.get(table), list) for table in EXPORT_ENTITY_ORDER)


def _import_export_payload(db, payload: dict[str, Any]) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    for table in EXPORT_ENTITY_ORDER:
        rows = payload.get(table) or []
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValidationError(f"`{table}` must be an array of objects.")
        entity_type = TABLE_ENTITY_TYPES[table]
        for row in rows:
            record, was_created = _upsert_export_row(db, entity_type, row)
            if was_created:
                created.append(record)
            else:
                updated.append(record)
    return {"ok": True, "format": "crm_export", "created_count": len(created), "updated_count": len(updated), "records": created + updated}


def _upsert_export_row(db, entity_type: str, row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    record_id = require_text(row, "id", required=True)
    exists = _record_exists(db, entity_type, record_id)
    if entity_type == "account":
        return (update_account(db, row) if exists else create_account(db, row), not exists)
    if entity_type == "contact":
        return (update_contact(db, row) if exists else create_contact(db, row), not exists)
    if entity_type == "deal":
        return (update_deal(db, row) if exists else create_deal(db, row), not exists)
    if entity_type == "activity":
        return (_update_activity(db, row) if exists else log_activity(db, row), not exists)
    if entity_type == "task":
        return (update_task(db, row) if exists else create_task(db, row), not exists)
    if entity_type == "note":
        return (update_note(db, row) if exists else create_note(db, row), not exists)
    raise ValidationError("Unsupported entity_type.", details={"entity_type": entity_type})


def _read_import_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("rows"), list):
        rows = payload["rows"]
        if not all(isinstance(row, dict) for row in rows):
            raise ValidationError("`rows` must contain objects.")
        return rows
    csv_text = require_text(payload, "csv")
    if not csv_text:
        return []
    return [dict(row) for row in csv.DictReader(StringIO(csv_text))]


def reference_manifest() -> dict[str, Any]:
    return {
        "entity_types": [
            {"entity_type": "account", "display_name": "Account"},
            {"entity_type": "contact", "display_name": "Contact"},
            {"entity_type": "deal", "display_name": "Deal"},
            {"entity_type": "activity", "display_name": "Activity"},
            {"entity_type": "task", "display_name": "Task"},
            {"entity_type": "note", "display_name": "Note"},
        ]
    }


def reference_search(db, payload: dict[str, Any]) -> dict[str, Any]:
    results = search(db, {"query": require_text(payload, "query"), "entity_type": require_text(payload, "entity_type", default="all") or "all", "limit": parse_limit(payload, 20)})["results"]
    references = []
    for item in results:
        record = item.get("record", {}) if isinstance(item.get("record"), dict) else {}
        entity_type = str(item.get("entity_type") or "")
        entity_id = str(item.get("entity_id") or record.get("id") or "")
        title = str(item.get("title") or titleFor(record) or entity_id)
        summary = str(item.get("body") or record.get("summary") or record.get("body") or "")
        references.append(_reference(entity_type, entity_id, title, summary))
    return {"results": references}


def reference_resolve(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type, entity_id = _split_reference_payload(payload)
    record = get_record(db, entity_type, entity_id)
    return _reference(entity_type, entity_id, titleFor(record), str(record.get("summary") or ""), exists=True, record=record)


def reference_summarize(db, payload: dict[str, Any]) -> dict[str, Any]:
    resolved = reference_resolve(db, payload)
    record = resolved.get("record", {})
    return {
        "summary": resolved.get("summary") or resolved.get("title"),
        "safe_fields": {
            "title": resolved.get("title"),
            "entity_type": resolved.get("entity_type"),
            "updated_at": record.get("updated_at") if isinstance(record, dict) else "",
        },
    }


def _split_reference_payload(payload: dict[str, Any]) -> tuple[str, str]:
    entity_type = require_text(payload, "entity_type")
    entity_id = require_text(payload, "entity_id") or require_text(payload, "id")
    if not entity_type and ":" in entity_id:
        entity_type, entity_id = entity_id.split(":", 1)
    if not entity_type or not entity_id:
        raise ValidationError("`entity_type` and `entity_id` are required.")
    return entity_type, entity_id


def titleFor(record: dict[str, Any]) -> str:
    return str(record.get("name") or record.get("display_name") or record.get("subject") or record.get("title") or _note_title(record) or record.get("id") or "")


def _reference(entity_type: str, entity_id: str, title: str, summary: str, *, exists: bool = True, record: dict[str, Any] | None = None) -> dict[str, Any]:
    route_segment = ENTITY_ROUTE_SEGMENTS.get(entity_type, f"{entity_type}s")
    payload = {
        "app_id": "crm",
        "entity_type": entity_type,
        "entity_id": f"{entity_type}:{entity_id}",
        "title": title,
        "summary": summary,
        "exists": exists,
        "deep_link": f"/app/crm/{route_segment}/{entity_id}",
        "app_page": f"{route_segment}/{entity_id}",
    }
    if record is not None:
        payload["record"] = record
    return payload


def read_view_state(data_root: str | Path) -> dict[str, Any]:
    path = Path(data_root) / "view_state.json"
    if not path.exists():
        return {"schema_version": "1", "view_filter": {"entity_type": "all", "mode": "search", "query": "", "refs": [], "title": "", "updated_at": ""}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValidationError("CRM view state is invalid.")
    return payload


def write_view_state(data_root: str | Path, view_filter: dict[str, Any]) -> dict[str, Any]:
    payload = {"schema_version": "1", "view_filter": view_filter}
    path = Path(data_root) / "view_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return payload


def _record_exists(db, entity_type: str, entity_id: str) -> bool:
    if not entity_id:
        return False
    table = table_for_entity(entity_type)
    row = db.execute(f"SELECT 1 FROM {table} WHERE id = ? AND deleted_at IS NULL", (entity_id,)).fetchone()
    return row is not None


def _validate_relationships(db, payload: dict[str, Any], fields: tuple[str, ...]) -> None:
    mapping = {"account_id": "account", "contact_id": "contact", "deal_id": "deal"}
    for field in fields:
        entity_id = require_text(payload, field)
        if entity_id and not _record_exists(db, mapping[field], entity_id):
            raise ValidationError("Related CRM record was not found.", details={"field": field, "id": entity_id})


def _require_pipeline(db, pipeline_id: str) -> None:
    row = db.execute("SELECT 1 FROM pipelines WHERE id = ?", (pipeline_id,)).fetchone()
    if row is None:
        raise ValidationError("Unknown CRM pipeline.", details={"pipeline_id": pipeline_id})


def _stage_row(db, stage_id: str, pipeline_id: str):
    row = db.execute("SELECT * FROM pipeline_stages WHERE id = ? AND pipeline_id = ?", (stage_id, pipeline_id)).fetchone()
    if row is None:
        raise ValidationError("Unknown CRM pipeline stage.", details={"stage_id": stage_id, "pipeline_id": pipeline_id})
    return row


def _stage_name(db, stage_id: str, pipeline_id: str = "pipeline_default") -> str:
    return str(_stage_row(db, stage_id, pipeline_id)["name"])


def _stage_probability(db, stage_id: str, pipeline_id: str = "pipeline_default") -> float:
    return float(_stage_row(db, stage_id, pipeline_id)["probability"])


def _note_title(record: dict[str, Any]) -> str:
    body = str(record.get("body") or "").strip()
    return body[:48] if body else ""
