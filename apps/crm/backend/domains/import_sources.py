"""Bounded import sources, stable identities and redacted provenance."""

import hashlib
import json
import re

from errors import ValidationError
from entity_catalog import EXTENSIONS
from store import require_text
from .import_export import _read_import_rows

MAX_IMPORT_ROWS = 2000
MAX_IMPORT_BYTES = 8_000_000
POLICIES = {"skip", "duplicate", "fill_empty", "overwrite", "manual"}
SECRET_KEY = re.compile(r"password|secret|token|credential|encrypted|api[_-]?key|authorization|cookie", re.I)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def source_record_id(source_id, source_key):
    return "imp_" + digest([source_id, source_key])[:32]


def safe_source(value):
    if isinstance(value, dict):
        return {str(key): safe_source(item) for key, item in value.items() if not SECRET_KEY.search(str(key))}
    if isinstance(value, list):
        return [safe_source(item) for item in value]
    return value


def normalize_source(payload):
    source = payload.get("source")
    if not isinstance(source, dict):
        raise ValidationError("`source` must be an import source object.")
    try:
        encoded = json.dumps(source, allow_nan=False)
    except (ValueError, TypeError) as error:
        raise ValidationError("Source must contain finite JSON data.") from error
    if len(encoded.encode()) > MAX_IMPORT_BYTES:
        raise ValidationError("Import source exceeds 8 MB; split it into ordered batches.")
    source_id = require_text(source, "source_id", required=True)
    if len(source_id) > 160:
        raise ValidationError("Source ID must be at most 160 characters.")
    source = safe_source(source)
    policy = require_text(payload, "conflict_policy", default="skip") or "skip"
    if policy not in POLICIES:
        raise ValidationError("Unsupported conflict policy.")
    if source.get("format") == "versy":
        from .versy_adapter import adapt_versy
        bundle = adapt_versy(source)
    elif source.get("format") == "crm_export":
        export = source.get("export")
        if not isinstance(export, dict):
            raise ValidationError("Native import requires an export object.")
        if policy != "overwrite":
            raise ValidationError("Native restore requires the explicit overwrite policy; preview it before applying.")
        bundle = {"native_export": export, "records": [], "links": [], "warnings": ["Native restore updates matching IDs; inspect the preview before applying."]}
    elif source.get("format", "json") in {"json", "csv"}:
        rows = _read_import_rows(source)
        entity = require_text(source, "entity_type", required=True)
        records = []
        for row in rows:
            source_key = f"{entity}:" + str(row.get("external_id") or row.get("id") or digest(row))
            record = {key: value for key, value in row.items() if key not in {"id", "external_id"}}
            if record.get("email"):
                record["email"] = str(record["email"]).strip().lower()
            for field, kind in EXTENSIONS.get(entity, {}).get("fields", {}).items():
                if field in record and isinstance(record[field], str):
                    try:
                        if kind == "integer":
                            record[field] = int(record[field] or 0)
                        elif kind == "json":
                            record[field] = json.loads(record[field] or '{}')
                    except (ValueError, TypeError) as error:
                        raise ValidationError(f"Invalid imported `{field}`.") from error
            records.append({"entity_type": entity, "source_key": source_key, "record": record})
        bundle = {"records": records, "links": [], "warnings": []}
    else:
        raise ValidationError("Format must be csv, json, crm_export or versy.")
    size = len(bundle["records"]) + len(bundle.get("links", []))
    if "native_export" in bundle:
        size = sum(len(rows) for rows in bundle["native_export"].values() if isinstance(rows, list))
    if size > MAX_IMPORT_ROWS:
        raise ValidationError("Import is limited to 2000 records/relationships per atomic batch.")
    return {**bundle, "source_id": source_id, "policy": policy, "fingerprint": digest([source, policy])}
