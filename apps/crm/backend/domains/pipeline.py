"""Pipeline and deal movement service domain for CRM."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from errors import ValidationError
from store import get_record, metadata, new_id, require_text, row_to_dict, table_for_entity, upsert_fts, utc_now, write_event

from .connection_summary import connection_summaries_for_deals

STUCK_AFTER_DAYS = 14


def _coerce_number(payload: dict[str, Any], key: str, default: float) -> float:
    value = payload.get(key, default)
    if value is None or value == "":
        return float(default)
    if isinstance(value, bool):
        raise ValidationError(f"`{key}` must be a number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"`{key}` must be a number.") from error
    if not math.isfinite(number):
        raise ValidationError(f"`{key}` must be a finite number.")
    return number


def _record_exists(db, entity_type: str, entity_id: str) -> str:
    if not entity_id:
        return ""
    table = table_for_entity(entity_type)
    row = db.execute(f"SELECT archived_at, deleted_at FROM {table} WHERE id = ?", (entity_id,)).fetchone()
    if row is None:
        return ""
    if row["deleted_at"]:
        return "deleted"
    if row["archived_at"]:
        return "archived"
    return "active"


def _validate_relationships(db, payload: dict[str, Any], fields: tuple[str, ...]) -> None:
    mapping = {"account_id": "account", "contact_id": "contact", "deal_id": "deal"}
    for field in fields:
        entity_id = require_text(payload, field)
        if not entity_id:
            continue
        state = _record_exists(db, mapping[field], entity_id)
        if state == "archived":
            raise ValidationError("Related CRM record is archived.", details={"field": field, "id": entity_id})
        if state != "active":
            raise ValidationError("Related CRM record was not found.", details={"field": field, "id": entity_id, "state": state or "missing"})


def move_deal(db, payload: dict[str, Any]) -> dict[str, Any]:
    deal_id = require_text(payload, "id", required=True)
    stage_id = require_text(payload, "stage_id", required=True)
    current = get_record(db, "deal", deal_id)
    pipeline_id = require_text(current, "pipeline_id", default="pipeline_default") or "pipeline_default"
    merged = {**current, "stage_id": stage_id, "stage": _stage_name(db, stage_id, pipeline_id), "probability": _stage_probability(db, stage_id, pipeline_id)}
    return _write_deal_update(db, deal_id, merged, "deal.moved")


def pipeline_board(db, payload: dict[str, Any]) -> dict[str, Any]:
    pipeline_id = require_text(payload, "pipeline_id", default="pipeline_default") or "pipeline_default"
    pipeline = row_to_dict(_pipeline_row(db, pipeline_id))
    now = _parse_datetime(utc_now()) or datetime.now(timezone.utc)
    stages = [
        {
            **row_to_dict(row),
            "deals": [],
            "deal_count": 0,
            "totals": {},
            "weighted": {},
            "total_value": 0.0,
            "weighted_value": 0.0,
        }
        for row in db.execute(
            """
            SELECT * FROM pipeline_stages
            WHERE pipeline_id = ?
            ORDER BY position ASC, lower(name) ASC
            """,
            (pipeline_id,),
        ).fetchall()
    ]
    stage_index = {stage["id"]: stage for stage in stages}
    stage_name_index = {str(stage["name"] or "").strip().lower(): stage for stage in stages}
    deals = [_pipeline_deal(row_to_dict(row), now) for row in _pipeline_deal_rows(db, pipeline_id)]
    connection_summaries = connection_summaries_for_deals(db, deals)
    for deal in deals:
        deal["connection_summary"] = connection_summaries.get(str(deal.get("id") or ""), {})
        stage = stage_index.get(str(deal.get("stage_id") or "")) or stage_name_index.get(str(deal.get("stage") or "").strip().lower())
        if stage is None:
            continue
        stage["deals"].append(deal)
        _add_stage_totals(stage, deal)
    totals = {
        "deal_count": 0,
        "currency_totals": {},
        "weighted_currency_totals": {},
        "total_value": 0.0,
        "weighted_value": 0.0,
    }
    for stage in stages:
        totals["deal_count"] += int(stage["deal_count"])
        totals["total_value"] += float(stage["total_value"])
        totals["weighted_value"] += float(stage["weighted_value"])
        _merge_currency_totals(totals["currency_totals"], stage["totals"])
        _merge_currency_totals(totals["weighted_currency_totals"], stage["weighted"])
    return {"ok": True, "pipeline": pipeline, "stages": stages, "totals": totals}


def create_pipeline(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    pipeline_id = require_text(payload, "id") or new_id("pipe")
    is_default = 1 if bool(payload.get("is_default")) else 0
    if is_default:
        db.execute("UPDATE pipelines SET is_default = 0")
    db.execute(
        "INSERT INTO pipelines(id, name, is_default, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (pipeline_id, require_text(payload, "name", required=True), is_default, now, now),
    )
    write_event(db, "pipeline.created", "pipeline", pipeline_id)
    return row_to_dict(db.execute("SELECT * FROM pipelines WHERE id = ?", (pipeline_id,)).fetchone())


def update_pipeline(db, payload: dict[str, Any]) -> dict[str, Any]:
    pipeline_id = require_text(payload, "id", required=True)
    _require_pipeline(db, pipeline_id)
    is_default = 1 if bool(payload.get("is_default")) else 0
    if is_default:
        db.execute("UPDATE pipelines SET is_default = 0")
    db.execute(
        "UPDATE pipelines SET name = ?, is_default = ?, updated_at = ? WHERE id = ?",
        (require_text(payload, "name", required=True), is_default, utc_now(), pipeline_id),
    )
    write_event(db, "pipeline.updated", "pipeline", pipeline_id)
    return row_to_dict(db.execute("SELECT * FROM pipelines WHERE id = ?", (pipeline_id,)).fetchone())


def create_pipeline_stage(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    pipeline_id = require_text(payload, "pipeline_id", default="pipeline_default") or "pipeline_default"
    _require_pipeline(db, pipeline_id)
    stage_id = require_text(payload, "id") or new_id("stage")
    db.execute(
        """
        INSERT INTO pipeline_stages(id, pipeline_id, name, position, probability, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            stage_id,
            pipeline_id,
            require_text(payload, "name", required=True),
            int(_coerce_number(payload, "position", _next_stage_position(db, pipeline_id))),
            _coerce_number(payload, "probability", 0),
            now,
            now,
        ),
    )
    write_event(db, "pipeline_stage.created", "pipeline_stage", stage_id)
    return row_to_dict(_stage_row(db, stage_id, pipeline_id))


def update_pipeline_stage(db, payload: dict[str, Any]) -> dict[str, Any]:
    stage_id = require_text(payload, "id", required=True)
    pipeline_id = require_text(payload, "pipeline_id", default="pipeline_default") or "pipeline_default"
    _stage_row(db, stage_id, pipeline_id)
    name = require_text(payload, "name", required=True)
    probability = _coerce_number(payload, "probability", _stage_probability(db, stage_id, pipeline_id))
    position = int(_coerce_number(payload, "position", float(_stage_row(db, stage_id, pipeline_id)["position"])))
    db.execute(
        "UPDATE pipeline_stages SET name = ?, position = ?, probability = ?, updated_at = ? WHERE id = ? AND pipeline_id = ?",
        (name, position, probability, utc_now(), stage_id, pipeline_id),
    )
    db.execute("UPDATE deals SET stage = ?, probability = ?, updated_at = ? WHERE stage_id = ? AND pipeline_id = ? AND deleted_at IS NULL", (name, probability, utc_now(), stage_id, pipeline_id))
    write_event(db, "pipeline_stage.updated", "pipeline_stage", stage_id)
    return row_to_dict(_stage_row(db, stage_id, pipeline_id))


def delete_pipeline_stage(db, payload: dict[str, Any]) -> dict[str, Any]:
    stage_id = require_text(payload, "id", required=True)
    pipeline_id = require_text(payload, "pipeline_id", default="pipeline_default") or "pipeline_default"
    stage = row_to_dict(_stage_row(db, stage_id, pipeline_id))
    stage_count = int(db.execute("SELECT count(*) FROM pipeline_stages WHERE pipeline_id = ?", (pipeline_id,)).fetchone()[0])
    if stage_count <= 1:
        raise ValidationError("Cannot delete the only CRM pipeline stage.", details={"stage_id": stage_id, "pipeline_id": pipeline_id})
    replacement_stage = _delete_stage_replacement(db, stage, payload)
    moved_deal_count = int(
        db.execute(
            "SELECT count(*) FROM deals WHERE pipeline_id = ? AND stage_id = ? AND deleted_at IS NULL",
            (pipeline_id, stage_id),
        ).fetchone()[0]
    )
    db.execute(
        """
        UPDATE deals
        SET stage_id = ?, stage = ?, probability = ?, updated_at = ?
        WHERE pipeline_id = ? AND stage_id = ? AND deleted_at IS NULL
        """,
        (
            replacement_stage["id"],
            replacement_stage["name"],
            replacement_stage["probability"],
            utc_now(),
            pipeline_id,
            stage_id,
        ),
    )
    db.execute("DELETE FROM pipeline_stages WHERE id = ? AND pipeline_id = ?", (stage_id, pipeline_id))
    write_event(db, "pipeline_stage.deleted", "pipeline_stage", stage_id, {"replacement_stage_id": replacement_stage["id"], "moved_deal_count": moved_deal_count})
    return {"ok": True, "stage": stage, "replacement_stage": replacement_stage, "moved_deal_count": moved_deal_count}


def _delete_stage_replacement(db, stage: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    pipeline_id = str(stage["pipeline_id"])
    stage_id = str(stage["id"])
    replacement_stage_id = require_text(payload, "replacement_stage_id")
    if replacement_stage_id:
        if replacement_stage_id == stage_id:
            raise ValidationError("Replacement CRM pipeline stage must be different.", details={"stage_id": stage_id})
        return row_to_dict(_stage_row(db, replacement_stage_id, pipeline_id))
    row = db.execute(
        """
        SELECT * FROM pipeline_stages
        WHERE pipeline_id = ? AND id != ?
        ORDER BY
          CASE WHEN position < ? THEN 0 ELSE 1 END ASC,
          CASE WHEN position < ? THEN position END DESC,
          CASE WHEN position >= ? THEN position END ASC,
          lower(name) ASC
        LIMIT 1
        """,
        (pipeline_id, stage_id, stage["position"], stage["position"], stage["position"]),
    ).fetchone()
    if row is None:
        raise ValidationError("Cannot find a replacement CRM pipeline stage.", details={"stage_id": stage_id, "pipeline_id": pipeline_id})
    return row_to_dict(row)


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
            _coerce_number(values, "value", 0),
            require_text(values, "currency", default="EUR") or "EUR",
            _coerce_number(values, "probability", _stage_probability(db, stage_id, pipeline_id)),
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

def _pipeline_row(db, pipeline_id: str):
    row = db.execute("SELECT * FROM pipelines WHERE id = ?", (pipeline_id,)).fetchone()
    if row is None:
        raise ValidationError("Unknown CRM pipeline.", details={"pipeline_id": pipeline_id})
    return row


def _pipeline_deal_rows(db, pipeline_id: str):
    return db.execute(
        """
        SELECT
          deals.*,
          COALESCE(accounts.name, '') AS account_label,
          COALESCE(contacts.display_name, '') AS contact_label
        FROM deals
        LEFT JOIN accounts
          ON accounts.id = deals.account_id
         AND accounts.deleted_at IS NULL
         AND accounts.archived_at IS NULL
        LEFT JOIN contacts
          ON contacts.id = deals.contact_id
         AND contacts.deleted_at IS NULL
         AND contacts.archived_at IS NULL
        WHERE (deals.pipeline_id = ? OR deals.pipeline_id = '')
          AND deals.deleted_at IS NULL
          AND deals.archived_at IS NULL
        ORDER BY
          deals.stage_id ASC,
          CASE WHEN deals.close_date = '' THEN 1 ELSE 0 END,
          deals.close_date ASC,
          deals.updated_at DESC,
          lower(deals.name) ASC
        """,
        (pipeline_id,),
    ).fetchall()


def _pipeline_deal(deal: dict[str, Any], now: datetime) -> dict[str, Any]:
    created_at = _parse_datetime(str(deal.get("created_at") or ""))
    updated_at = _parse_datetime(str(deal.get("updated_at") or ""))
    age_days = _days_between(now, created_at)
    stuck_days = _days_between(now, updated_at)
    past_due = _is_past_date(str(deal.get("close_date") or ""), now)
    is_stuck = past_due or (stuck_days is not None and stuck_days >= STUCK_AFTER_DAYS)
    if past_due:
        status = "past_due"
        label = "Past due"
    elif stuck_days is not None and stuck_days >= STUCK_AFTER_DAYS:
        status = "stuck"
        label = f"Stuck {stuck_days}d"
    elif age_days is not None:
        status = "active"
        label = f"Age {age_days}d"
    else:
        status = "active"
        label = "Active"
    deal["age_days"] = age_days
    deal["stuck_days"] = stuck_days
    deal["health"] = {
        "status": status,
        "label": label,
        "age_days": age_days,
        "stuck_days": stuck_days,
        "is_stuck": is_stuck,
        "past_due": past_due,
    }
    return deal


def _add_stage_totals(stage: dict[str, Any], deal: dict[str, Any]) -> None:
    currency = str(deal.get("currency") or "EUR")
    value = float(deal.get("value") or 0)
    probability = float(deal.get("probability") or stage.get("probability") or 0)
    weighted_value = value * probability
    stage["deal_count"] += 1
    stage["total_value"] += value
    stage["weighted_value"] += weighted_value
    stage["totals"][currency] = float(stage["totals"].get(currency, 0)) + value
    stage["weighted"][currency] = float(stage["weighted"].get(currency, 0)) + weighted_value


def _merge_currency_totals(target: dict[str, float], source: dict[str, float]) -> None:
    for currency, value in source.items():
        target[currency] = float(target.get(currency, 0)) + float(value or 0)


def _days_between(now: datetime, value: datetime | None) -> int | None:
    if value is None:
        return None
    return max(0, (now - value).days)


def _is_past_date(value: str, now: datetime) -> bool:
    parsed = _parse_datetime(value)
    if parsed is None:
        return False
    today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return parsed < today


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _require_pipeline(db, pipeline_id: str) -> None:
    _pipeline_row(db, pipeline_id)


def _stage_row(db, stage_id: str, pipeline_id: str):
    row = db.execute("SELECT * FROM pipeline_stages WHERE id = ? AND pipeline_id = ?", (stage_id, pipeline_id)).fetchone()
    if row is None:
        raise ValidationError("Unknown CRM pipeline stage.", details={"stage_id": stage_id, "pipeline_id": pipeline_id})
    return row


def _stage_name(db, stage_id: str, pipeline_id: str = "pipeline_default") -> str:
    return str(_stage_row(db, stage_id, pipeline_id)["name"])


def _stage_probability(db, stage_id: str, pipeline_id: str = "pipeline_default") -> float:
    return float(_stage_row(db, stage_id, pipeline_id)["probability"])


def _next_stage_position(db, pipeline_id: str) -> float:
    row = db.execute("SELECT coalesce(max(position), 0) + 10 FROM pipeline_stages WHERE pipeline_id = ?", (pipeline_id,)).fetchone()
    return float(row[0] if row else 10)
