"""Sort field rules for the CRM records table."""

from __future__ import annotations

from typing import Any


RECORDS_TABLE_SORT_FIELDS = {
    "updated_at",
    "value",
    "close_date",
    "owner",
    "owner_id",
    "status",
    "stage",
    "name",
    "last_activity_at",
    "next_action",
    "open_task_count",
    "open_deal_value",
    "contact_count",
    "weighted_value",
    "deal_age_days",
    "probability",
}
RECORDS_TABLE_NUMERIC_SORT_FIELDS = {
    "value",
    "open_task_count",
    "open_deal_value",
    "contact_count",
    "weighted_value",
    "deal_age_days",
    "probability",
}


def records_table_sort_field(sort: dict[str, Any]) -> str:
    field = str(sort.get("field") or "updated_at")
    return field if field in RECORDS_TABLE_SORT_FIELDS else "updated_at"


def records_table_sort_direction(sort: dict[str, Any]) -> str:
    return "asc" if str(sort.get("direction") or "desc").lower() == "asc" else "desc"
