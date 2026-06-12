"""Sales reporting service domain for CRM."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from store import parse_limit, row_to_dict, utc_now

from .connection_summary import connection_report_metrics


def sales_reports(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = _parse_datetime(utc_now()) or datetime.now(timezone.utc)
    open_stage_rows = db.execute(
        """
        SELECT stage_id, stage, currency, count(*) AS deal_count, sum(value) AS total_value, sum(value * probability) AS weighted_value
        FROM deals
        WHERE deleted_at IS NULL
          AND archived_at IS NULL
          AND stage_id NOT IN ('won', 'lost')
          AND lower(stage) NOT IN ('won', 'lost')
        GROUP BY stage_id, stage, currency
        ORDER BY total_value DESC
        """
    ).fetchall()
    pipeline_value_by_stage = [
        {
            "stage_id": row["stage_id"],
            "stage": row["stage"],
            "currency": row["currency"],
            "deal_count": int(row["deal_count"] or 0),
            "total_value": float(row["total_value"] or 0),
            "weighted_value": float(row["weighted_value"] or 0),
        }
        for row in open_stage_rows
    ]
    weighted_forecast = {
        "currency_totals": _sum_rows_by_currency(open_stage_rows, "weighted_value"),
        "total_weighted_value": sum(item["weighted_value"] for item in pipeline_value_by_stage),
        "by_stage": pipeline_value_by_stage,
    }
    aging_rows = db.execute(
        """
        SELECT id, name, stage, value, currency, owner_id, created_at, updated_at, close_date
        FROM deals
        WHERE deleted_at IS NULL
          AND archived_at IS NULL
          AND stage_id NOT IN ('won', 'lost')
          AND lower(stage) NOT IN ('won', 'lost')
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (parse_limit(payload, 25),),
    ).fetchall()
    deal_aging = []
    for row in aging_rows:
        created_at = _parse_datetime(str(row["created_at"] or ""))
        age_days = max(0, (now - created_at).days) if created_at else 0
        deal_aging.append({**row_to_dict(row), "age_days": age_days})
    lead_stats = db.execute(
        """
        SELECT
          count(*) AS total,
          sum(CASE WHEN converted_at != '' OR status = 'converted' THEN 1 ELSE 0 END) AS converted,
          avg(CASE WHEN converted_at != '' THEN julianday(converted_at) - julianday(created_at) ELSE NULL END) AS avg_days_to_convert
        FROM leads
        WHERE deleted_at IS NULL AND archived_at IS NULL
        """
    ).fetchone()
    total_leads = int(lead_stats["total"] or 0)
    converted_leads = int(lead_stats["converted"] or 0)
    lead_conversion = {
        "total": total_leads,
        "converted": converted_leads,
        "conversion_rate": (converted_leads / total_leads) if total_leads else 0,
        "avg_days_to_convert": float(lead_stats["avg_days_to_convert"] or 0),
    }
    overdue_rows = db.execute(
        """
        SELECT owner_id, count(*) AS task_count
        FROM tasks
        WHERE deleted_at IS NULL AND archived_at IS NULL AND status = 'open' AND due_at != '' AND due_at < ?
        GROUP BY owner_id
        ORDER BY task_count DESC, owner_id ASC
        """,
        (utc_now(),),
    ).fetchall()
    task_overdue = {
        "total": sum(int(row["task_count"] or 0) for row in overdue_rows),
        "drilldown_filters": {"kind": "task", "status": "open", "due_overdue": "true"},
        "by_owner": [
            {
                "owner_id": row["owner_id"],
                "task_count": int(row["task_count"] or 0),
                "drilldown_filters": {
                    "kind": "task",
                    "status": "open",
                    "due_overdue": "true",
                    "owner_id": row["owner_id"] or "",
                },
            }
            for row in overdue_rows
        ],
    }
    activity_rows = db.execute(
        """
        SELECT owner_id, activity_type, count(*) AS activity_count
        FROM activities
        WHERE deleted_at IS NULL AND archived_at IS NULL
        GROUP BY owner_id, activity_type
        ORDER BY activity_count DESC, owner_id ASC, activity_type ASC
        """
    ).fetchall()
    activities_by_owner: dict[str, dict[str, Any]] = {}
    for row in activity_rows:
        owner_id = str(row["owner_id"] or "")
        bucket = activities_by_owner.setdefault(
            owner_id,
            {
                "owner_id": owner_id,
                "total": 0,
                "by_type": {},
                "drilldown_filters": {"kind": "activity", "owner_id": owner_id},
            },
        )
        count = int(row["activity_count"] or 0)
        bucket["total"] += count
        bucket["by_type"][str(row["activity_type"] or "activity")] = count
    return {
        "ok": True,
        "pipeline_value_by_stage": pipeline_value_by_stage,
        "weighted_forecast": weighted_forecast,
        "deal_aging": deal_aging,
        "lead_conversion": lead_conversion,
        "connection_metrics": connection_report_metrics(db),
        "task_overdue": task_overdue,
        "activities_by_owner": list(activities_by_owner.values()),
    }

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


def _sum_rows_by_currency(rows: list[Any], value_key: str) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        currency = str(row["currency"] or "")
        totals[currency] = totals.get(currency, 0) + float(row[value_key] or 0)
    return totals
