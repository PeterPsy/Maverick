"""Health check service domain for CRM."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from errors import ValidationError
from store import SCHEMA_VERSION, count_tables, export_payload, row_to_dict


EXPORT_ENTITY_ORDER = ["leads", "accounts", "contacts", "deals", "activities", "tasks", "notes"]
EXPORT_CONFIG_TABLES = ["custom_field_definitions", "custom_field_values", "automation_rules", "workflow_proposals", "external_refs"]
TABLE_ENTITY_TYPES = {
    "leads": "lead",
    "accounts": "account",
    "contacts": "contact",
    "deals": "deal",
    "activities": "activity",
    "tasks": "task",
    "notes": "note",
}


def health_report(db, data_root: str | Path, *, read_view_state, import_preview, workflow_proposal_action_issues, record_exists) -> dict[str, Any]:
    tables = list(EXPORT_ENTITY_ORDER)
    checks = {
        "schema": _schema_health(db),
        "fts": _fts_health(db),
        "references": _reference_health(db),
        "view_state": _view_state_health(data_root, read_view_state),
        "export": _export_health(db),
        "archive_import": _archive_import_health(db, import_preview),
        "custom_field_values": _custom_field_values_health(db, record_exists),
        "workflow_proposals": _workflow_proposals_health(db, workflow_proposal_action_issues),
        "external_refs": _external_refs_health(db, record_exists),
    }
    ok = all(check.get("ok") is True for check in checks.values())
    return {
        "ok": ok,
        "status": "healthy" if ok else "degraded",
        "counts": count_tables(db, tables),
        "checks": checks,
    }


def _schema_health(db) -> dict[str, Any]:
    expected_tables = {
        "schema_metadata",
        "leads",
        "accounts",
        "contacts",
        "pipelines",
        "pipeline_stages",
        "deals",
        "activities",
        "tasks",
        "notes",
        "tags",
        "record_tags",
        "saved_views",
        "custom_field_definitions",
        "custom_field_values",
        "automation_rules",
        "workflow_proposals",
        "external_refs",
        "events",
        "crm_fts",
    }
    existing_tables = {str(row["name"]) for row in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')").fetchall()}
    metadata_row = db.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()
    integrity_row = db.execute("PRAGMA integrity_check").fetchone()
    missing = sorted(expected_tables - existing_tables)
    schema_version = str(metadata_row["value"]) if metadata_row else ""
    integrity = str(integrity_row[0]) if integrity_row else "missing"
    return {"ok": not missing and schema_version == SCHEMA_VERSION and integrity == "ok", "missing_tables": missing, "schema_version": schema_version, "sqlite_integrity": integrity}


def _fts_health(db) -> dict[str, Any]:
    missing: dict[str, int] = {}
    for table in EXPORT_ENTITY_ORDER:
        entity_type = TABLE_ENTITY_TYPES[table]
        count = db.execute(
            f"""
            SELECT count(*) FROM {table}
            WHERE deleted_at IS NULL AND archived_at IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM crm_fts
                WHERE crm_fts.entity_type = ? AND crm_fts.entity_id = {table}.id
              )
            """,
            (entity_type,),
        ).fetchone()[0]
        missing[entity_type] = int(count)
    stale = 0
    for table in EXPORT_ENTITY_ORDER:
        entity_type = TABLE_ENTITY_TYPES[table]
        stale += int(
            db.execute(
                f"""
                SELECT count(*) FROM crm_fts
                WHERE entity_type = ?
                  AND NOT EXISTS (
                    SELECT 1 FROM {table}
                    WHERE {table}.id = crm_fts.entity_id
                      AND {table}.deleted_at IS NULL
                      AND {table}.archived_at IS NULL
                  )
                """,
                (entity_type,),
            ).fetchone()[0]
        )
    missing_total = sum(missing.values())
    return {"ok": missing_total == 0 and stale == 0, "missing": missing, "missing_total": missing_total, "stale_total": stale}


def _reference_health(db) -> dict[str, Any]:
    relation_specs = [
        ("contacts", "account_id", "accounts"),
        ("deals", "account_id", "accounts"),
        ("deals", "contact_id", "contacts"),
        ("activities", "account_id", "accounts"),
        ("activities", "contact_id", "contacts"),
        ("activities", "deal_id", "deals"),
        ("tasks", "account_id", "accounts"),
        ("tasks", "contact_id", "contacts"),
        ("tasks", "deal_id", "deals"),
        ("notes", "account_id", "accounts"),
        ("notes", "contact_id", "contacts"),
        ("notes", "deal_id", "deals"),
        ("leads", "account_id", "accounts"),
        ("leads", "contact_id", "contacts"),
        ("leads", "deal_id", "deals"),
    ]
    orphan_counts: dict[str, int] = {
        "deals.pipeline_id": int(db.execute("SELECT count(*) FROM deals WHERE deleted_at IS NULL AND archived_at IS NULL AND pipeline_id != '' AND NOT EXISTS (SELECT 1 FROM pipelines WHERE pipelines.id = deals.pipeline_id)").fetchone()[0]),
        "deals.stage_id": int(db.execute("SELECT count(*) FROM deals WHERE deleted_at IS NULL AND archived_at IS NULL AND stage_id != '' AND NOT EXISTS (SELECT 1 FROM pipeline_stages WHERE pipeline_stages.id = deals.stage_id AND pipeline_stages.pipeline_id = deals.pipeline_id)").fetchone()[0]),
    }
    archived_parent_counts: dict[str, int] = {}
    for child_table, field, parent_table in relation_specs:
        name = f"{child_table}.{field}"
        orphan_counts[name] = int(
            db.execute(
                f"""
                SELECT count(*) FROM {child_table}
                WHERE deleted_at IS NULL AND archived_at IS NULL AND {field} != ''
                  AND NOT EXISTS (
                    SELECT 1 FROM {parent_table}
                    WHERE {parent_table}.id = {child_table}.{field}
                      AND {parent_table}.deleted_at IS NULL
                  )
                """
            ).fetchone()[0]
        )
        archived_parent_counts[name] = int(
            db.execute(
                f"""
                SELECT count(*) FROM {child_table}
                WHERE deleted_at IS NULL AND archived_at IS NULL AND {field} != ''
                  AND EXISTS (
                    SELECT 1 FROM {parent_table}
                    WHERE {parent_table}.id = {child_table}.{field}
                      AND {parent_table}.deleted_at IS NULL
                      AND {parent_table}.archived_at IS NOT NULL
                  )
                """
            ).fetchone()[0]
        )
    orphan_total = sum(orphan_counts.values())
    archived_parent_total = sum(archived_parent_counts.values())
    return {"ok": orphan_total == 0 and archived_parent_total == 0, "orphan_total": orphan_total, "orphan_counts": orphan_counts, "archived_parent_total": archived_parent_total, "archived_parent_counts": archived_parent_counts}


def _view_state_health(data_root: str | Path, read_view_state) -> dict[str, Any]:
    try:
        state = read_view_state(data_root)
    except Exception as error:
        return {"ok": False, "error": error.__class__.__name__, "message": str(error)}
    view_filter = state.get("view_filter") if isinstance(state, dict) else None
    refs = view_filter.get("refs") if isinstance(view_filter, dict) else None
    ok = isinstance(view_filter, dict) and isinstance(refs, list)
    return {"ok": ok, "mode": view_filter.get("mode") if isinstance(view_filter, dict) else "", "refs_count": len(refs) if isinstance(refs, list) else 0}


def _export_health(db) -> dict[str, Any]:
    try:
        payload = export_payload(db)
    except Exception as error:
        return {"ok": False, "error": error.__class__.__name__, "message": str(error)}
    counts = {table: len(payload.get(table) or []) for table in [*EXPORT_CONFIG_TABLES, *EXPORT_ENTITY_ORDER]}
    return {"ok": True, "counts": counts}


def _archive_import_health(db, import_preview) -> dict[str, Any]:
    try:
        payload = export_payload(db)
        preview = import_preview(payload)
    except Exception as error:
        return {"ok": False, "error": error.__class__.__name__, "message": str(error)}
    table_counts = {table: int(db.execute(f"SELECT count(*) FROM {table} WHERE deleted_at IS NULL").fetchone()[0]) for table in EXPORT_ENTITY_ORDER}
    export_counts = {table: len(payload.get(table) or []) for table in EXPORT_ENTITY_ORDER}
    archived_counts = {table: int(db.execute(f"SELECT count(*) FROM {table} WHERE deleted_at IS NULL AND archived_at IS NOT NULL").fetchone()[0]) for table in EXPORT_ENTITY_ORDER}
    exported_archived_counts = {table: sum(1 for row in payload.get(table) or [] if isinstance(row, dict) and row.get("archived_at")) for table in EXPORT_ENTITY_ORDER}
    mismatched_counts = {table: {"database": table_counts[table], "export": export_counts[table]} for table in EXPORT_ENTITY_ORDER if table_counts[table] != export_counts[table]}
    mismatched_archived = {table: {"database": archived_counts[table], "export": exported_archived_counts[table]} for table in EXPORT_ENTITY_ORDER if archived_counts[table] != exported_archived_counts[table]}
    ok = not mismatched_counts and not mismatched_archived and bool(preview.get("ok"))
    return {"ok": ok, "counts": export_counts, "archived_counts": exported_archived_counts, "mismatched_counts": mismatched_counts, "mismatched_archived_counts": mismatched_archived, "preview_ok": bool(preview.get("ok"))}


def _custom_field_values_health(db, record_exists) -> dict[str, Any]:
    missing_field_definition = int(
        db.execute(
            """
            SELECT count(*) FROM custom_field_values
            WHERE NOT EXISTS (
              SELECT 1 FROM custom_field_definitions
              WHERE custom_field_definitions.id = custom_field_values.field_id
                AND custom_field_definitions.entity_type = custom_field_values.entity_type
            )
            """
        ).fetchone()[0]
    )
    missing_records = 0
    invalid_entity_types = 0
    for row in db.execute("SELECT entity_type, entity_id FROM custom_field_values").fetchall():
        entity_type = str(row["entity_type"] or "")
        try:
            state = record_exists(db, entity_type, str(row["entity_id"] or ""))
        except ValidationError:
            invalid_entity_types += 1
            continue
        if state in {"", "deleted"}:
            missing_records += 1
    ok = missing_field_definition == 0 and missing_records == 0 and invalid_entity_types == 0
    return {"ok": ok, "missing_field_definition": missing_field_definition, "missing_records": missing_records, "invalid_entity_types": invalid_entity_types}


def _workflow_proposals_health(db, workflow_proposal_action_issues) -> dict[str, Any]:
    invalid: list[dict[str, Any]] = []
    rows = db.execute("SELECT * FROM workflow_proposals WHERE status IN ('pending', 'approved') ORDER BY updated_at DESC").fetchall()
    for row in rows:
        proposal = row_to_dict(row)
        issues = workflow_proposal_action_issues(db, proposal)
        if issues:
            invalid.append({"id": proposal.get("id"), "issues": issues})
    return {"ok": not invalid, "checked_count": len(rows), "invalid_count": len(invalid), "invalid": invalid[:20]}


def _external_refs_health(db, record_exists) -> dict[str, Any]:
    malformed: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    rows = db.execute("SELECT * FROM external_refs WHERE deleted_at IS NULL ORDER BY updated_at DESC").fetchall()
    for row in rows:
        ref = row_to_dict(row)
        issues: list[str] = []
        crm_entity_type = str(ref.get("crm_entity_type") or "")
        crm_entity_id = str(ref.get("crm_entity_id") or "")
        try:
            state = record_exists(db, crm_entity_type, crm_entity_id)
        except ValidationError:
            state = ""
            issues.append("invalid CRM entity type")
        if state in {"", "deleted"}:
            issues.append("CRM target is missing or deleted")
        for key in ("source_app_id", "source_entity_type", "source_entity_id"):
            if not str(ref.get(key) or "").strip():
                issues.append(f"{key} is required")
        if issues:
            malformed.append({"id": ref.get("id"), "status": "malformed", "issues": issues})
        else:
            unresolved.append({"id": ref.get("id"), "status": "unresolved", "source_app_id": ref.get("source_app_id"), "source_entity_type": ref.get("source_entity_type")})
    return {
        "ok": not malformed,
        "checked_count": len(rows),
        "malformed_count": len(malformed),
        "malformed": malformed[:20],
        "unresolved_count": len(unresolved),
        "unresolved": unresolved[:20],
    }
