"""Pipeline and deal movement service domain for CRM."""

from __future__ import annotations

import math
from typing import Any

from errors import ValidationError
from store import get_record, metadata, new_id, require_text, row_to_dict, table_for_entity, upsert_fts, utc_now, write_event


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


def _next_stage_position(db, pipeline_id: str) -> float:
    row = db.execute("SELECT coalesce(max(position), 0) + 10 FROM pipeline_stages WHERE pipeline_id = ?", (pipeline_id,)).fetchone()
    return float(row[0] if row else 10)
