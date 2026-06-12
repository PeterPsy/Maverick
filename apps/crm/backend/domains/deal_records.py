"""CRM deal record mutations."""

from __future__ import annotations

import math
from typing import Any

from errors import ValidationError
from domains.pipeline import _require_pipeline, _stage_name, _stage_probability, _write_deal_update
from domains.record_lifecycle import validate_relationships
from store import get_record, metadata, new_id, require_text, upsert_fts, utc_now, write_event


def coerce_record_number(payload: dict[str, Any], key: str, default: float) -> float:
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


def create_deal(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    deal_id = require_text(payload, "id") or new_id("deal")
    validate_relationships(db, payload, ("account_id", "contact_id"))
    pipeline_id = require_text(payload, "pipeline_id", default="pipeline_default") or "pipeline_default"
    _require_pipeline(db, pipeline_id)
    stage_id = require_text(payload, "stage_id", default=require_text(payload, "stage", default="lead")) or "lead"
    stage = _stage_name(db, stage_id, pipeline_id)
    probability = coerce_record_number(payload, "probability", _stage_probability(db, stage_id, pipeline_id))
    value = coerce_record_number(payload, "value", 0)
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
