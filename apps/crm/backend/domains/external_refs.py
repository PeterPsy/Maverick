"""External reference linking and record timeline operations."""

from __future__ import annotations

import json
from typing import Any

from errors import NotFoundError, ValidationError
from store import get_record, new_id, parse_limit, require_text, row_to_dict, table_for_entity, utc_now, write_event

from .record_lifecycle import record_exists, title_for_record

PROVIDER_ALIASES = {"mail", "calendar", "files", "agent"}
PROVIDER_INTERFACE_PREFIXES = {
    "mail": "mail",
    "email": "mail",
    "calendar": "calendar",
    "file": "files",
    "files": "files",
    "storage": "files",
    "agent": "agent",
    "agents": "agent",
}
LINK_TYPE_ALIASES = {
    "email": "mail",
    "email_thread": "mail",
    "mail": "mail",
    "mail_thread": "mail",
    "thread": "mail",
    "call": "calendar",
    "meeting": "calendar",
    "sales_call": "calendar",
    "calendar_event": "calendar",
    "event": "calendar",
    "attachment": "files",
    "brief": "files",
    "document": "files",
    "file": "files",
    "file_attachment": "files",
    "agent_activity": "agent",
    "agent_run": "agent",
}
ENTITY_TYPE_ALIASES = {
    "email": "mail",
    "message": "mail",
    "thread": "mail",
    "event": "calendar",
    "calendar_event": "calendar",
    "attachment": "files",
    "document": "files",
    "file": "files",
    "run": "agent",
}


def link_external_ref(db, payload: dict[str, Any]) -> dict[str, Any]:
    crm_entity_type, crm_entity_id = _crm_external_ref_target(payload)
    get_record(db, crm_entity_type, crm_entity_id)
    source_app_id = require_text(payload, "source_app_id", required=True)
    source_entity_type = require_text(payload, "source_entity_type", required=True)
    source_entity_id = require_text(payload, "source_entity_id", required=True)
    link_type = require_text(payload, "link_type", default="related") or "related"
    normalized = normalize_external_ref_provider(payload)
    ref_id = require_text(payload, "id")
    now = utc_now()
    existing = None
    if ref_id:
        existing = db.execute("SELECT * FROM external_refs WHERE id = ?", (ref_id,)).fetchone()
    if existing is None:
        existing = db.execute(
            """
            SELECT * FROM external_refs
            WHERE crm_entity_type = ? AND crm_entity_id = ?
              AND source_app_id = ? AND source_entity_type = ? AND source_entity_id = ?
              AND link_type = ? AND deleted_at IS NULL
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (crm_entity_type, crm_entity_id, source_app_id, source_entity_type, source_entity_id, link_type),
        ).fetchone()
    ref_id = str(existing["id"]) if existing is not None else (ref_id or new_id("xref"))
    created_at = str(existing["created_at"]) if existing is not None else now
    db.execute(
        """
        INSERT INTO external_refs(
          id, crm_entity_type, crm_entity_id, source_app_id, source_entity_type, source_entity_id,
          link_type, provider_alias, source_interface, normalized_link_type, title, summary, occurred_at,
          metadata_json, created_at, updated_at, deleted_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        ON CONFLICT(id) DO UPDATE SET
          crm_entity_type = excluded.crm_entity_type,
          crm_entity_id = excluded.crm_entity_id,
          source_app_id = excluded.source_app_id,
          source_entity_type = excluded.source_entity_type,
          source_entity_id = excluded.source_entity_id,
          link_type = excluded.link_type,
          provider_alias = excluded.provider_alias,
          source_interface = excluded.source_interface,
          normalized_link_type = excluded.normalized_link_type,
          title = excluded.title,
          summary = excluded.summary,
          occurred_at = excluded.occurred_at,
          metadata_json = excluded.metadata_json,
          updated_at = excluded.updated_at,
          deleted_at = NULL
        """,
        (
            ref_id,
            crm_entity_type,
            crm_entity_id,
            source_app_id,
            source_entity_type,
            source_entity_id,
            link_type,
            normalized["provider_alias"],
            normalized["source_interface"],
            normalized["normalized_link_type"],
            require_text(payload, "title") or f"{source_app_id}:{source_entity_type}:{source_entity_id}",
            require_text(payload, "summary"),
            require_text(payload, "occurred_at"),
            _external_ref_metadata_json(payload, normalized),
            created_at,
            now,
        ),
    )
    write_event(db, "external_ref.linked", crm_entity_type, crm_entity_id, {"external_ref_id": ref_id, "source_app_id": source_app_id})
    return _external_ref_from_row(db.execute("SELECT * FROM external_refs WHERE id = ?", (ref_id,)).fetchone())


def unlink_external_ref(db, payload: dict[str, Any]) -> dict[str, Any]:
    ref_id = require_text(payload, "id")
    row = None
    if ref_id:
        row = db.execute("SELECT * FROM external_refs WHERE id = ? AND deleted_at IS NULL", (ref_id,)).fetchone()
    else:
        crm_entity_type, crm_entity_id = _crm_external_ref_target(payload)
        row = db.execute(
            """
            SELECT * FROM external_refs
            WHERE crm_entity_type = ? AND crm_entity_id = ?
              AND source_app_id = ? AND source_entity_type = ? AND source_entity_id = ?
              AND link_type = ? AND deleted_at IS NULL
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (
                crm_entity_type,
                crm_entity_id,
                require_text(payload, "source_app_id", required=True),
                require_text(payload, "source_entity_type", required=True),
                require_text(payload, "source_entity_id", required=True),
                require_text(payload, "link_type", default="related") or "related",
            ),
        ).fetchone()
    if row is None:
        raise NotFoundError("external_ref was not found.")
    now = utc_now()
    db.execute("UPDATE external_refs SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL", (now, now, row["id"]))
    write_event(db, "external_ref.unlinked", str(row["crm_entity_type"]), str(row["crm_entity_id"]), {"external_ref_id": str(row["id"])})
    return {"ok": True, "id": str(row["id"]), "deleted_at": now}


def list_external_refs(db, payload: dict[str, Any]) -> list[dict[str, Any]]:
    where = ["deleted_at IS NULL"]
    params: list[Any] = []
    crm_entity_type = require_text(payload, "crm_entity_type") or require_text(payload, "entity_type")
    crm_entity_id = require_text(payload, "crm_entity_id") or require_text(payload, "id") or require_text(payload, "entity_id")
    if crm_entity_type:
        table_for_entity(crm_entity_type)
        where.append("crm_entity_type = ?")
        params.append(crm_entity_type)
    if crm_entity_id:
        where.append("crm_entity_id = ?")
        params.append(crm_entity_id)
    for key in ("source_app_id", "source_entity_type", "source_entity_id", "link_type", "provider_alias", "source_interface", "normalized_link_type"):
        value = require_text(payload, key)
        if value:
            where.append(f"{key} = ?")
            params.append(value)
    params.append(parse_limit(payload, 100))
    rows = db.execute(
        f"SELECT * FROM external_refs WHERE {' AND '.join(where)} ORDER BY COALESCE(NULLIF(occurred_at, ''), updated_at) DESC LIMIT ?",
        params,
    ).fetchall()
    return [_external_ref_from_row(row) for row in rows]


def _upsert_external_ref_export(db, row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    ref_id = require_text(row, "id") or new_id("xref")
    crm_entity_type = require_text(row, "crm_entity_type", required=True)
    crm_entity_id = require_text(row, "crm_entity_id", required=True)
    state = record_exists(db, crm_entity_type, crm_entity_id)
    if state in {"", "deleted"}:
        raise ValidationError("External ref references a missing CRM record.", details={"crm_entity_type": crm_entity_type, "crm_entity_id": crm_entity_id, "state": state or "missing"})
    for key in ("source_app_id", "source_entity_type", "source_entity_id"):
        require_text(row, key, required=True)
    normalized = normalize_external_ref_provider(row)
    exists = db.execute("SELECT 1 FROM external_refs WHERE id = ?", (ref_id,)).fetchone() is not None
    now = utc_now()
    db.execute(
        """
        INSERT INTO external_refs(
          id, crm_entity_type, crm_entity_id, source_app_id, source_entity_type, source_entity_id,
          link_type, provider_alias, source_interface, normalized_link_type, title, summary, occurred_at,
          metadata_json, created_at, updated_at, deleted_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          crm_entity_type = excluded.crm_entity_type,
          crm_entity_id = excluded.crm_entity_id,
          source_app_id = excluded.source_app_id,
          source_entity_type = excluded.source_entity_type,
          source_entity_id = excluded.source_entity_id,
          link_type = excluded.link_type,
          provider_alias = excluded.provider_alias,
          source_interface = excluded.source_interface,
          normalized_link_type = excluded.normalized_link_type,
          title = excluded.title,
          summary = excluded.summary,
          occurred_at = excluded.occurred_at,
          metadata_json = excluded.metadata_json,
          updated_at = excluded.updated_at,
          deleted_at = excluded.deleted_at
        """,
        (
            ref_id,
            crm_entity_type,
            crm_entity_id,
            require_text(row, "source_app_id", required=True),
            require_text(row, "source_entity_type", required=True),
            require_text(row, "source_entity_id", required=True),
            require_text(row, "link_type", default="related") or "related",
            normalized["provider_alias"],
            normalized["source_interface"],
            normalized["normalized_link_type"],
            require_text(row, "title"),
            require_text(row, "summary"),
            require_text(row, "occurred_at"),
            _external_ref_metadata_json(row, normalized),
            require_text(row, "created_at") or now,
            require_text(row, "updated_at") or now,
            require_text(row, "deleted_at") or None,
        ),
    )
    return (_external_ref_from_row(db.execute("SELECT * FROM external_refs WHERE id = ?", (ref_id,)).fetchone()), not exists)


def _crm_external_ref_target(payload: dict[str, Any]) -> tuple[str, str]:
    entity_type = require_text(payload, "crm_entity_type") or require_text(payload, "entity_type", required=True)
    entity_id = require_text(payload, "crm_entity_id") or require_text(payload, "id") or require_text(payload, "entity_id", required=True)
    table_for_entity(entity_type)
    return entity_type, entity_id


def _external_ref_from_row(row) -> dict[str, Any]:
    item = row_to_dict(row)
    normalized = normalize_external_ref_provider(item)
    item["provider_alias"] = normalized["provider_alias"]
    item["source_interface"] = normalized["source_interface"]
    item["normalized_link_type"] = normalized["normalized_link_type"]
    item["entity_type"] = "external_ref"
    item["timestamp"] = item.get("occurred_at") or item.get("updated_at")
    item["status"] = "linked" if not item.get("deleted_at") else "deleted"
    item["ref"] = {
        "app_id": item.get("source_app_id"),
        "entity_type": item.get("source_entity_type"),
        "entity_id": item.get("source_entity_id"),
        "title": item.get("title"),
        "summary": item.get("summary"),
    }
    return item


def normalize_external_ref_provider(payload: dict[str, Any]) -> dict[str, str]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    link_type = _normalize_token(require_text(payload, "link_type", default="related") or "related")
    source_interface = _normalize_interface(_first_text(payload, metadata, "source_interface", "interface"))
    provider_alias = _normalize_provider_alias(_first_text(payload, metadata, "provider_alias", "provider"))
    if not provider_alias:
        provider_alias = _provider_from_interface(source_interface)
    if not provider_alias:
        provider_alias = _provider_from_link_type(link_type)
    if not provider_alias:
        provider_alias = ENTITY_TYPE_ALIASES.get(_normalize_token(require_text(payload, "source_entity_type")))
    if not provider_alias:
        provider_alias = _provider_from_interface(_normalize_interface(require_text(payload, "source_app_id")))
    if not source_interface and provider_alias:
        source_interface = _default_source_interface(provider_alias, require_text(payload, "source_entity_type"))
    return {
        "provider_alias": provider_alias,
        "source_interface": source_interface,
        "normalized_link_type": link_type,
    }


def external_ref_kind(ref: dict[str, Any]) -> str:
    normalized = normalize_external_ref_provider(ref)
    provider_alias = normalized["provider_alias"]
    if provider_alias in PROVIDER_ALIASES:
        return provider_alias
    return ""


def _external_ref_metadata_json(payload: dict[str, Any], normalized: dict[str, str]) -> str:
    value = payload.get("metadata") or {}
    if not isinstance(value, dict):
        raise ValidationError("`metadata` must be an object.")
    merged = dict(value)
    for key in ("provider_alias", "source_interface", "normalized_link_type"):
        if normalized.get(key):
            merged.setdefault(key, normalized[key])
    return json.dumps(merged, ensure_ascii=True, sort_keys=True)


def _first_text(payload: dict[str, Any], metadata: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        metadata_value = metadata.get(key)
        if isinstance(metadata_value, str) and metadata_value.strip():
            return metadata_value.strip()
    return ""


def _normalize_provider_alias(value: str) -> str:
    token = _normalize_token(value)
    return PROVIDER_INTERFACE_PREFIXES.get(token, token if token in PROVIDER_ALIASES else "")


def _provider_from_interface(value: str) -> str:
    if not value:
        return ""
    prefix = value.split(".", 1)[0]
    return PROVIDER_INTERFACE_PREFIXES.get(prefix, "")


def _provider_from_link_type(value: str) -> str:
    return LINK_TYPE_ALIASES.get(value, "")


def _normalize_interface(value: str) -> str:
    return ".".join(_normalize_token(part) for part in value.split(".") if _normalize_token(part))


def _normalize_token(value: str) -> str:
    return "_".join(str(value or "").strip().lower().replace("-", "_").split())


def _default_source_interface(provider_alias: str, source_entity_type: str) -> str:
    entity_type = _normalize_token(source_entity_type)
    if provider_alias == "mail":
        return f"mail.{entity_type or 'item'}"
    if provider_alias == "calendar":
        return f"calendar.{entity_type or 'event'}"
    if provider_alias == "files":
        return f"file.{entity_type or 'item'}"
    if provider_alias == "agent":
        return f"agent.{entity_type or 'activity'}"
    return ""


def external_timeline_rows(db, refs: dict[str, set[str]], direct_target: tuple[str, str] | None = None) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for entity_type, ids in {
        "lead": refs.get("lead_id", set()),
        "account": refs.get("account_id", set()),
        "contact": refs.get("contact_id", set()),
        "deal": refs.get("deal_id", set()),
    }.items():
        if ids:
            placeholders = ", ".join("?" for _ in ids)
            clauses.append(f"(crm_entity_type = ? AND crm_entity_id IN ({placeholders}))")
            params.append(entity_type)
            params.extend(sorted(ids))
    if not clauses:
        return []
    rows = db.execute(
        f"""
        SELECT * FROM external_refs
        WHERE deleted_at IS NULL AND ({' OR '.join(clauses)})
        ORDER BY COALESCE(NULLIF(occurred_at, ''), updated_at) DESC
        LIMIT 100
        """,
        params,
    ).fetchall()
    origin_titles = _origin_titles(db, rows)
    items = []
    for row in rows:
        item = _external_ref_from_row(row)
        origin_key = (str(item.get("crm_entity_type") or ""), str(item.get("crm_entity_id") or ""))
        item["relationship_scope"] = "direct" if direct_target and origin_key == direct_target else "inherited"
        item["origin"] = {
            "entity_type": origin_key[0],
            "entity_id": origin_key[1],
            "title": origin_titles.get(origin_key, origin_key[1]),
        }
        items.append(item)
    return items


def _origin_titles(db, rows) -> dict[tuple[str, str], str]:
    titles: dict[tuple[str, str], str] = {}
    for row in rows:
        entity_type = str(row["crm_entity_type"] or "")
        entity_id = str(row["crm_entity_id"] or "")
        key = (entity_type, entity_id)
        if not entity_type or not entity_id or key in titles:
            continue
        try:
            titles[key] = title_for_record(get_record(db, entity_type, entity_id))
        except NotFoundError:
            titles[key] = entity_id
    return titles
