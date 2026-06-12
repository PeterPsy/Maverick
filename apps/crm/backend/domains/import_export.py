"""Import/export parsing helpers for CRM."""

from __future__ import annotations

import csv
from io import StringIO
import math
from typing import Any, Callable

from errors import ValidationError
from store import require_text

from .export_restore import EXPORT_CONFIG_TABLES, EXPORT_ENTITY_ORDER, restore_export_payload


RecordCreator = Callable[[Any, dict[str, Any]], dict[str, Any]]


def import_preview(payload: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_import_payload(payload)
    if _looks_like_export_payload(payload):
        counts = {table: len(payload.get(table) or []) for table in [*EXPORT_CONFIG_TABLES, *EXPORT_ENTITY_ORDER]}
        return {"ok": True, "format": "crm_export", "counts": counts, "row_count": sum(counts.values()), "sample": {table: (payload.get(table) or [])[:3] for table in EXPORT_ENTITY_ORDER}, "warnings": []}
    entity_type = require_text(payload, "entity_type", default="contact") or "contact"
    rows = _read_import_rows(payload)
    errors = _validate_import_rows(entity_type, rows)
    return {"ok": not errors, "entity_type": entity_type, "row_count": len(rows), "sample": rows[:10], "warnings": [], "errors": errors}


def import_commit(db, payload: dict[str, Any], creators: dict[str, RecordCreator]) -> dict[str, Any]:
    payload = _normalize_import_payload(payload)
    if _looks_like_export_payload(payload):
        return restore_export_payload(db, payload)
    entity_type = require_text(payload, "entity_type", default="contact") or "contact"
    rows = _read_import_rows(payload)
    errors = _validate_import_rows(entity_type, rows)
    if errors:
        return {"ok": False, "entity_type": entity_type, "created_count": 0, "records": [], "errors": errors}
    creator = creators.get(entity_type)
    if creator is None:
        raise ValidationError("Imports support lead, account, contact, deal, activity, task, and note.", details={"entity_type": entity_type})
    created = [creator(db, row) for row in rows]
    return {"ok": True, "entity_type": entity_type, "created_count": len(created), "records": created, "errors": []}


def _normalize_import_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("export"), dict):
        return payload["export"]
    if isinstance(payload.get("payload"), dict):
        return _normalize_import_payload(payload["payload"])
    return payload


def _looks_like_export_payload(payload: dict[str, Any]) -> bool:
    return any(isinstance(payload.get(table), list) for table in [*EXPORT_CONFIG_TABLES, *EXPORT_ENTITY_ORDER])


def _read_import_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("rows"), list):
        rows = payload["rows"]
        if not all(isinstance(row, dict) for row in rows):
            raise ValidationError("`rows` must contain objects.")
        return [_map_import_row(row, payload) for row in rows]
    csv_text = require_text(payload, "csv")
    if not csv_text:
        return []
    return [_map_import_row(dict(row), payload) for row in csv.DictReader(StringIO(csv_text))]


def _map_import_row(row: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    mapping = payload.get("column_mapping") or payload.get("mapping") or {}
    if not isinstance(mapping, dict) or not mapping:
        return row
    mapped: dict[str, Any] = {}
    for source_key, value in row.items():
        target_key = str(mapping.get(source_key) or source_key).strip()
        if target_key:
            mapped[target_key] = value
    return mapped


def _validate_import_rows(entity_type: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required_by_entity = {
        "lead": ("display_name|email",),
        "account": ("name",),
        "contact": ("display_name|email",),
        "deal": ("name",),
        "activity": ("subject",),
        "task": ("title",),
        "note": ("body",),
    }
    if entity_type not in required_by_entity:
        raise ValidationError("Imports support lead, account, contact, deal, activity, task, and note.", details={"entity_type": entity_type})
    errors: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        row_errors: list[str] = []
        for requirement in required_by_entity[entity_type]:
            alternatives = requirement.split("|")
            if not any(str(row.get(key) or "").strip() for key in alternatives):
                row_errors.append(f"Missing {' or '.join(alternatives)}")
        for key in ("value", "probability"):
            value = row.get(key)
            if value not in (None, ""):
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    row_errors.append(f"`{key}` must be a number")
                else:
                    if not math.isfinite(number):
                        row_errors.append(f"`{key}` must be finite")
        if row_errors:
            errors.append({"row": index, "errors": row_errors, "data": row})
    return errors
