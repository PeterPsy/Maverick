"""CRM external-reference summaries for UI badges and aggregate reports."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from store import row_to_dict, utc_now

from .external_refs import external_ref_kind


CRM_RECORD_TYPES = {"lead", "account", "contact", "deal"}
PENDING_APPROVAL_STATUSES = {"pending"}
RECENT_TOUCH_DAYS = 30


def connection_summaries_for_records(db, keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
    normalized_keys = _normalized_keys(keys)
    if not normalized_keys:
        return {}
    refs_by_key = _external_refs_by_key(db, normalized_keys)
    approvals_by_key = _approval_counts_by_key(db, normalized_keys)
    return {
        key: _summarize_refs(refs_by_key.get(key, []), approvals_by_key.get(key, 0))
        for key in normalized_keys
    }


def connection_summaries_for_deals(db, deals: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    deal_refs: dict[str, set[tuple[str, str]]] = {}
    all_keys: set[tuple[str, str]] = set()
    for deal in deals:
        deal_id = str(deal.get("id") or "")
        if not deal_id:
            continue
        keys = {("deal", deal_id)}
        account_id = str(deal.get("account_id") or "")
        contact_id = str(deal.get("contact_id") or "")
        if account_id:
            keys.add(("account", account_id))
        if contact_id:
            keys.add(("contact", contact_id))
        deal_refs[deal_id] = keys
        all_keys.update(keys)
    refs_by_key = _external_refs_by_key(db, all_keys)
    approvals_by_key = _approval_counts_by_key(db, all_keys)
    summaries: dict[str, dict[str, Any]] = {}
    for deal_id, keys in deal_refs.items():
        refs: list[dict[str, Any]] = []
        approval_count = 0
        for key in keys:
            refs.extend(refs_by_key.get(key, []))
            approval_count += approvals_by_key.get(key, 0)
        summaries[deal_id] = _summarize_refs(refs, approval_count)
    return summaries


def connection_summary_for_ref_context(db, refs: dict[str, set[str]]) -> dict[str, Any]:
    keys = _keys_from_ref_context(refs)
    if not keys:
        return _summarize_refs([])
    refs_by_key = _external_refs_by_key(db, keys)
    approvals_by_key = _approval_counts_by_key(db, keys)
    external_refs: list[dict[str, Any]] = []
    approval_count = 0
    for key in keys:
        external_refs.extend(refs_by_key.get(key, []))
        approval_count += approvals_by_key.get(key, 0)
    return _summarize_refs(external_refs, approval_count)


def connection_report_metrics(db) -> dict[str, Any]:
    ref_rows = [
        row_to_dict(row)
        for row in db.execute(
            """
            SELECT *
            FROM external_refs
            WHERE deleted_at IS NULL
            """
        ).fetchall()
    ]
    lead_email_ids = {
        str(row.get("crm_entity_id") or "")
        for row in ref_rows
        if str(row.get("crm_entity_type") or "") == "lead" and external_ref_kind(row) == "mail"
    }
    call_rows = [
        row
        for row in ref_rows
        if external_ref_kind(row) == "calendar"
    ]
    future_call_keys: set[tuple[str, str]] = set()
    now = _parse_datetime(utc_now()) or datetime.now(timezone.utc)
    for row in call_rows:
        entity_type = str(row.get("crm_entity_type") or "")
        entity_id = str(row.get("crm_entity_id") or "")
        occurred_at = str(row.get("occurred_at") or "")
        occurred = _parse_datetime(occurred_at)
        if occurred is not None and occurred >= now:
            future_call_keys.add((entity_type, entity_id))
    account_call_ids = {entity_id for entity_type, entity_id in future_call_keys if entity_type == "account"}
    contact_call_ids = {entity_id for entity_type, entity_id in future_call_keys if entity_type == "contact"}
    deals_with_calls: set[str] = set()
    pipeline_value_with_next_call: dict[str, float] = {}
    for row in db.execute(
        """
        SELECT id, account_id, contact_id, value, currency
        FROM deals
        WHERE deleted_at IS NULL
          AND archived_at IS NULL
          AND stage_id NOT IN ('won', 'lost')
          AND lower(stage) NOT IN ('won', 'lost')
        """
    ).fetchall():
        deal_id = str(row["id"])
        account_id = str(row["account_id"] or "")
        contact_id = str(row["contact_id"] or "")
        has_future_call = ("deal", deal_id) in future_call_keys or ("account", account_id) in future_call_keys or ("contact", contact_id) in future_call_keys
        if has_future_call:
            deals_with_calls.add(deal_id)
            currency = str(row["currency"] or "EUR")
            pipeline_value_with_next_call[currency] = pipeline_value_with_next_call.get(currency, 0.0) + float(row["value"] or 0)
    no_follow_up_count = int(
        db.execute(
            """
            SELECT count(*)
            FROM accounts
            WHERE deleted_at IS NULL
              AND archived_at IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM tasks
                WHERE tasks.account_id = accounts.id
                  AND tasks.deleted_at IS NULL
                  AND tasks.archived_at IS NULL
                  AND tasks.status = 'open'
              )
              AND NOT EXISTS (
                SELECT 1 FROM activities
                WHERE activities.account_id = accounts.id
                  AND activities.deleted_at IS NULL
                  AND activities.archived_at IS NULL
                  AND COALESCE(NULLIF(activities.occurred_at, ''), activities.updated_at) >= datetime('now', '-30 days')
              )
              AND NOT EXISTS (
                SELECT 1 FROM external_refs
                WHERE external_refs.deleted_at IS NULL
                  AND COALESCE(NULLIF(external_refs.occurred_at, ''), external_refs.updated_at) >= datetime('now', '-30 days')
                  AND (
                    (external_refs.crm_entity_type = 'account' AND external_refs.crm_entity_id = accounts.id)
                    OR (
                      external_refs.crm_entity_type = 'contact'
                      AND external_refs.crm_entity_id IN (
                        SELECT contacts.id FROM contacts
                        WHERE contacts.account_id = accounts.id AND contacts.deleted_at IS NULL
                      )
                    )
                    OR (
                      external_refs.crm_entity_type = 'deal'
                      AND external_refs.crm_entity_id IN (
                        SELECT deals.id FROM deals
                        WHERE deals.account_id = accounts.id AND deals.deleted_at IS NULL
                      )
                    )
                  )
              )
            """
        ).fetchone()[0]
        or 0
    )
    pending_approval_count = int(
        db.execute(
            """
            SELECT count(*)
            FROM (
                SELECT entity_type, entity_id
                FROM workflow_proposals
                WHERE status = 'pending'
                  AND entity_type != ''
                  AND entity_id != ''
                GROUP BY entity_type, entity_id
            )
            """
        ).fetchone()[0]
        or 0
    )
    return {
        "leads_with_linked_email": len({entity_id for entity_id in lead_email_ids if entity_id}),
        "deals_with_scheduled_call": len(deals_with_calls),
        "accounts_without_recent_follow_up": no_follow_up_count,
        "records_with_pending_approvals": pending_approval_count,
        "pipeline_value_with_next_call": pipeline_value_with_next_call,
    }


def _normalized_keys(keys: Iterable[tuple[str, str]]) -> set[tuple[str, str]]:
    return {
        (str(entity_type), str(entity_id))
        for entity_type, entity_id in keys
        if str(entity_type) in CRM_RECORD_TYPES and str(entity_id)
    }


def _keys_from_ref_context(refs: dict[str, set[str]]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for ref_field, entity_type in {
        "lead_id": "lead",
        "account_id": "account",
        "contact_id": "contact",
        "deal_id": "deal",
    }.items():
        keys.update((entity_type, entity_id) for entity_id in refs.get(ref_field, set()) if entity_id)
    return keys


def _external_refs_by_key(db, keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    where_sql, params = _key_where(keys, "crm_entity_type", "crm_entity_id")
    if not where_sql:
        return {}
    rows = db.execute(
        f"""
        SELECT *
        FROM external_refs
        WHERE deleted_at IS NULL AND ({where_sql})
        ORDER BY COALESCE(NULLIF(occurred_at, ''), updated_at) DESC
        """,
        params,
    ).fetchall()
    refs_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        ref = row_to_dict(row)
        refs_by_key.setdefault((str(ref["crm_entity_type"]), str(ref["crm_entity_id"])), []).append(ref)
    return refs_by_key


def _approval_counts_by_key(db, keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], int]:
    where_sql, params = _key_where(keys, "entity_type", "entity_id")
    if not where_sql:
        return {}
    placeholders = ", ".join("?" for _ in PENDING_APPROVAL_STATUSES)
    rows = db.execute(
        f"""
        SELECT entity_type, entity_id, count(*) AS approval_count
        FROM workflow_proposals
        WHERE status IN ({placeholders}) AND ({where_sql})
        GROUP BY entity_type, entity_id
        """,
        [*sorted(PENDING_APPROVAL_STATUSES), *params],
    ).fetchall()
    return {(str(row["entity_type"]), str(row["entity_id"])): int(row["approval_count"] or 0) for row in rows}


def _key_where(keys: Iterable[tuple[str, str]], entity_column: str, id_column: str) -> tuple[str, list[Any]]:
    ids_by_entity: dict[str, list[str]] = {}
    for entity_type, entity_id in _normalized_keys(keys):
        ids_by_entity.setdefault(entity_type, []).append(entity_id)
    clauses: list[str] = []
    params: list[Any] = []
    for entity_type, entity_ids in sorted(ids_by_entity.items()):
        placeholders = ", ".join("?" for _ in entity_ids)
        clauses.append(f"({entity_column} = ? AND {id_column} IN ({placeholders}))")
        params.extend([entity_type, *sorted(entity_ids)])
    return " OR ".join(clauses), params


def _summarize_refs(refs: list[dict[str, Any]], approval_count: int = 0) -> dict[str, Any]:
    mail_refs = [ref for ref in refs if _is_mail_ref(ref)]
    calendar_refs = [ref for ref in refs if _is_calendar_ref(ref)]
    file_refs = [ref for ref in refs if _is_file_ref(ref)]
    agent_refs = [ref for ref in refs if _is_agent_ref(ref)]
    latest_touch_at = max((str(ref.get("occurred_at") or ref.get("updated_at") or "") for ref in refs), default="")
    next_calendar_at = _next_calendar_at(calendar_refs)
    has_recent_touch = _has_recent_touch(refs, next_calendar_at)
    summary = {
        "total_count": len(refs),
        "mail_count": len(mail_refs),
        "calendar_count": len(calendar_refs),
        "file_count": len(file_refs),
        "agent_count": len(agent_refs),
        "approval_count": approval_count,
        "latest_touch_at": latest_touch_at,
        "next_calendar_at": next_calendar_at,
        "has_recent_touch": has_recent_touch,
        "brief_ready": any(_is_brief_ref(ref) for ref in file_refs),
        "badges": [],
    }
    badges: list[dict[str, Any]] = []
    if mail_refs:
        badges.append({"key": "mail", "kind": "mail", "label": f"Mail {len(mail_refs)}", "count": len(mail_refs)})
    if calendar_refs:
        badges.append({"key": "calendar", "kind": "calendar", "label": _calendar_badge_label(next_calendar_at), "count": len(calendar_refs), "date": next_calendar_at})
    if file_refs:
        badges.append({"key": "files", "kind": "files", "label": f"Files {len(file_refs)}", "count": len(file_refs)})
    if agent_refs:
        badges.append({"key": "agent", "kind": "agent", "label": "Agent", "count": len(agent_refs)})
    if approval_count:
        badges.append({"key": "approval", "kind": "approval", "label": "Approval", "count": approval_count})
    summary["badges"] = badges
    return summary


def _is_mail_ref(ref: dict[str, Any]) -> bool:
    return external_ref_kind(ref) == "mail"


def _is_calendar_ref(ref: dict[str, Any]) -> bool:
    return external_ref_kind(ref) == "calendar"


def _is_file_ref(ref: dict[str, Any]) -> bool:
    return external_ref_kind(ref) == "files"


def _is_agent_ref(ref: dict[str, Any]) -> bool:
    metadata = ref.get("metadata") if isinstance(ref.get("metadata"), dict) else {}
    return external_ref_kind(ref) == "agent" or "agent" in str(metadata.get("actor_type") or metadata.get("created_by") or "").lower()


def _is_brief_ref(ref: dict[str, Any]) -> bool:
    return "brief" in _ref_text(ref)


def _ref_text(ref: dict[str, Any]) -> str:
    return " ".join(
        str(ref.get(key) or "").lower()
        for key in ("source_app_id", "source_entity_type", "link_type", "title", "summary")
    )


def _next_calendar_at(refs: list[dict[str, Any]]) -> str:
    now = _parse_datetime(utc_now()) or datetime.now(timezone.utc)
    dated = [(parsed, str(ref.get("occurred_at") or ref.get("updated_at") or "")) for ref in refs if (parsed := _parse_datetime(str(ref.get("occurred_at") or ref.get("updated_at") or "")))]
    future = sorted((item for item in dated if item[0] >= now), key=lambda item: item[0])
    if future:
        return future[0][1]
    past = sorted(dated, key=lambda item: item[0], reverse=True)
    return past[0][1] if past else ""


def _has_recent_touch(refs: list[dict[str, Any]], next_calendar_at: str) -> bool:
    now = _parse_datetime(utc_now()) or datetime.now(timezone.utc)
    next_calendar = _parse_datetime(next_calendar_at)
    if next_calendar is not None and next_calendar >= now:
        return True
    threshold = now - timedelta(days=RECENT_TOUCH_DAYS)
    for ref in refs:
        parsed = _parse_datetime(str(ref.get("occurred_at") or ref.get("updated_at") or ""))
        if parsed is not None and parsed >= threshold:
            return True
    return False


def _calendar_badge_label(value: str) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return "Call booked"
    return f"Call {parsed.strftime('%b')} {parsed.day}"


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
