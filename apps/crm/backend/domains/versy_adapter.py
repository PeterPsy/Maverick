"""Explicit adapter for the reviewed external schema; no upstream executable code."""

import json
import re
from datetime import datetime, timezone

from errors import ValidationError

# Source names are adapter vocabulary, not the generic product model.
TABLE_TYPES = {
    "contacts": "contact", "interactions": "activity", "conversation_threads": "conversation_thread",
    "follow_ups": "task", "deals": "deal", "expenses": "expense",
    "real_estate_agencies": "account", "outreach_campaigns": "campaign",
    "outreach_campaign_variants": "campaign_variant", "outreach_campaign_steps": "campaign_step",
    "outreach_campaign_enrollments": "campaign_member", "outreach_campaign_events": "campaign_event",
    "weekly_briefs": "brief", "competitors": "intelligence_profile",
    "calendar_events": "brief", "transcripts": "note", "email_threads": "conversation_thread",
    "property_listings": "custom_object_record", "presentation_generations": "custom_object_record",
    "data_quality_suggestions": "workflow_proposal",
}
EXCLUDED_TABLES = {"integration_settings", "company_settings", "real_estate_pages", "property_search_jobs", "campaign_runs"}


def timestamp(value):
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()
        except (OverflowError, ValueError, OSError) as error:
            raise ValidationError("Source timestamp is out of range.") from error
    return str(value)


def array(value):
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as error:
            raise ValidationError("Source relationship array is invalid JSON.") from error
    if not isinstance(value, list):
        raise ValidationError("Source relationship value must be an array.")
    return value


def snake_row(row):
    if not isinstance(row, dict):
        raise ValidationError("Source tables must contain objects.")
    return {re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower(): value for key, value in row.items()}


def adapt_versy(source):
    tables = source.get("tables")
    if not isinstance(tables, dict):
        raise ValidationError("Versy adapter requires `tables`, a JSON table-to-rows object.")
    if not all(isinstance(rows, list) for rows in tables.values()):
        raise ValidationError("Source tables must be arrays of objects.")
    records, links, warnings = [], [], []
    from .versy_relationships import extract_links
    # Definitions are generated only when matching vertical records are supplied.
    for table in ("property_listings", "presentation_generations"):
        if tables.get(table):
            records.append({"entity_type": "custom_object_definition", "source_key": f"definition:{table}",
                            "record": {"title": table.replace("_", " ").title(), "object_key": table.rstrip("s"), "fields": {"source": "json"}}})
    companies = {}
    for raw in tables.get("contacts", []):
        row = snake_row(raw)
        company = str(row.get("company") or "").strip()
        if company:
            key = "company:" + company.casefold()
            companies[key] = company
    for key, name in companies.items():
        records.append({"entity_type": "account", "source_key": key, "record": {"name": name}})
    for table, raw_rows in tables.items():
        if not isinstance(raw_rows, list):
            raise ValidationError(f"`{table}` must be an array.")
        if table not in TABLE_TYPES:
            reason = "excluded configuration/cache/job data" if table in EXCLUDED_TABLES else "unsupported table; export separately before cutover"
            warnings.append(f"{table}: {len(raw_rows)} rows not imported ({reason}).")
            continue
        for raw in raw_rows:
            row = snake_row(raw)
            if not isinstance(row.get("id"), str) or not row["id"]:
                raise ValidationError(f"{table}: every source row requires a string ID.")
            key = f"{table}:{row['id']}"
            record = convert_record(table, row)
            # Original owner is retained only as provenance, not a new CRM assignee.
            record["metadata"] = {"import_source": {"table": table, "record": row}}
            for field in ("created_at", "updated_at"):
                if row.get(field):
                    record[field] = timestamp(row[field])
            item = {"entity_type": TABLE_TYPES[table], "source_key": key, "record": record}
            records.append(item)
            links.extend(extract_links(table, row, key, item))
    for item in records:
        if item["entity_type"] == "contact":
            company = str(item["record"].get("metadata", {}).get("import_source", {}).get("record", {}).get("company") or "").strip()
            if company:
                item.setdefault("foreign", {})["account_id"] = "company:" + company.casefold()
    if any(tables.get(t) for t in ("email_threads", "calendar_events", "transcripts", "brand_assets")):
        warnings.append("Provider snapshots retain provenance only. Match Mail/Calendar/Storage identities through selected providers before cutover; no provider records or credentials were imported.")
    return {"records": records, "links": links, "warnings": warnings}


def convert_record(table, r):
    title = r.get("title") or r.get("name") or r.get("subject") or r["id"]
    body = r.get("body") or r.get("summary") or r.get("notes") or ""
    base = {"title": str(title), "body": str(body)}
    if table == "contacts":
        return {"display_name": r.get("full_name") or r.get("email") or r["id"], "email": (r.get("email") or "").strip().lower(),
                "phone": r.get("phone") or "", "role": r.get("role") or "", "summary": r.get("notes") or ""}
    if table == "real_estate_agencies":
        return {"name": title, "summary": body, "industry": "real_estate"}
    if table == "interactions":
        return {"subject": r.get("summary") or title, "body": body, "activity_type": "interaction", "occurred_at": timestamp(r.get("occurred_at"))}
    if table == "follow_ups":
        return {**base, "body": r.get("task_details") or r.get("summary") or "", "due_at": timestamp(r.get("scheduled_at")),
                "status": "done" if str(r.get("status", "")).lower() in {"completato", "completata", "done"} else "open"}
    if table == "deals":
        stage = {"lead": "lead", "qualificato": "qualified", "proposta": "proposal", "vinto": "won", "perso": "lost"}.get(str(r.get("status", "")).lower(), "lead")
        return {"name": title, "summary": r.get("description") or "", "value": r.get("value_cents", 0) / 100,
                "currency": r.get("currency") or "EUR", "stage_id": stage, "close_date": timestamp(r.get("expected_close_at")),
                "margin_minor": r.get("margin_cents", 0)}
    if table == "expenses":
        return {**base, "amount_minor": r.get("amount_cents", 0), "currency": r.get("currency") or "EUR", "incurred_at": timestamp(r.get("expense_date")), "supplier": r.get("supplier") or "", "category": r.get("category") or ""}
    if table in {"conversation_threads", "email_threads"}:
        return {**base, "title": r.get("thread_title") or title, "channel": "email", "status": "open", "last_activity_at": timestamp(r.get("last_activity_at") or r.get("occurred_at"))}
    if table == "outreach_campaigns":
        return {**base, "status": "draft", "channel": str(r.get("channel") or "email").lower(), "objective": r.get("objective") or "", "segment": {"city": r["city"]} if r.get("city") else {}}
    if table == "outreach_campaign_variants":
        return {**base, "body": r.get("message_template") or "", "weight": r.get("weight", 100)}
    if table == "outreach_campaign_steps":
        return {**base, "body": r.get("instructions") or "", "position": r.get("position", 0), "delay_hours": r.get("delay_hours", 0), "channel": r.get("kind") or "manual"}
    if table == "outreach_campaign_enrollments":
        return {**base, "status": "pending", "record_type": "account", "next_action_at": timestamp(r.get("next_action_at"))}
    if table == "outreach_campaign_events":
        return {**base, "event_type": r.get("kind") or "note", "occurred_at": timestamp(r.get("occurred_at"))}
    if table == "weekly_briefs":
        return {**base, "body": "\n\n".join(str(r.get(key) or "") for key in ("executive_summary", "previous_week_highlights", "current_week_priorities")), "period_start": timestamp(r.get("current_week_start")), "period_end": timestamp(r.get("current_week_end"))}
    if table == "competitors":
        return {**base, "body": r.get("positioning") or "", "website": r.get("website_url") or "", "reviewed_at": timestamp(r.get("last_checked_at"))}
    if table == "calendar_events":
        return {**base, "body": "\n\n".join(str(r.get(k) or "") for k in ("briefing_summary", "meeting_note", "decisions", "activity_notes", "ai_outcome_summary")), "period_start": timestamp(r.get("start_at")), "period_end": timestamp(r.get("end_at"))}
    if table == "transcripts":
        return {"body": r.get("transcript") or r.get("summary") or title}
    if table in {"property_listings", "presentation_generations"}:
        return {**base, "fields": {"source": r}}
    return base
