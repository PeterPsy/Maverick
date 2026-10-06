"""Read-only, bounded summary for the app-owned shell sidebar."""

from datetime import date
from typing import Any

from errors import MartaOpsError
from validation import _date


def sidebar_summary(state: dict[str, Any], today_value: object) -> dict[str, int]:
    """Use the client's local day, as the full app does for deadlines."""
    today = _date(today_value, "Data locale")
    if not today or len(today) != 10 or date.fromisoformat(today).isoformat() != today:
        raise MartaOpsError("Data locale deve essere una data YYYY-MM-DD.")
    works = state["collaborations"]
    deliveries = [item for work in works for item in work.get("deliverables", [])]
    return {
        "overdue_deliveries": sum(
            item.get("status") != "published" and bool(item.get("due_date"))
            and item["due_date"] < today for item in deliveries
        ),
        "approvals": sum(item.get("status") == "approval" for item in deliveries),
        "open_tasks": sum(not item.get("done", False) for item in state["tasks"]),
        "receivables": sum(work.get("payment_status") in {"invoiced", "overdue"} for work in works),
        "overdue_payments": sum(work.get("payment_status") == "overdue" for work in works),
    }
