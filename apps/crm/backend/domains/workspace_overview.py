"""Operational read model: live CRM work, not cached workflow authority."""

from entity_catalog import ENTITY_TABLES
from store import count_tables, row_to_dict
from .operations import list_next_actions


def overview(db):
    active = "deleted_at IS NULL AND archived_at IS NULL"
    counts = count_tables(db, ENTITY_TABLES.values())
    overdue = db.execute(f"SELECT count(*) FROM tasks WHERE {active} AND status='open' AND due_at!='' AND julianday(due_at)<julianday('now')").fetchone()[0]
    financials = [dict(row) for row in db.execute(f"SELECT currency, sum(value) AS value, sum(value * probability) AS weighted_value, sum(margin_minor) AS margin_minor FROM deals WHERE {active} AND stage_id NOT IN ('won', 'lost') GROUP BY currency")]
    expenses = [dict(row) for row in db.execute(f"SELECT currency, sum(amount_minor) AS amount_minor FROM expenses WHERE {active} GROUP BY currency")]
    return {"ok": True, "counts": counts, "overdue_tasks": overdue,
            "pending_approvals": db.execute("SELECT count(*) FROM workflow_proposals WHERE status='pending'").fetchone()[0],
            "tasks": list_next_actions(db, {"limit": 30}), "pipeline": financials, "expenses": expenses,
            "threads": [row_to_dict(row) for row in db.execute(f"SELECT * FROM conversation_threads WHERE {active} ORDER BY last_activity_at DESC, id LIMIT 8")],
            "briefs": [row_to_dict(row) for row in db.execute(f"SELECT * FROM briefs WHERE {active} ORDER BY updated_at DESC, id LIMIT 6")],
            "recent_deals": [row_to_dict(row) for row in db.execute(f"SELECT * FROM deals WHERE {active} AND stage_id NOT IN ('won','lost') ORDER BY updated_at DESC,id LIMIT 4")],
            "pipeline_stages": [row_to_dict(row) for row in db.execute("SELECT * FROM pipeline_stages ORDER BY position,id")],
            "recent_contacts": [row_to_dict(row) for row in db.execute(f"SELECT * FROM contacts WHERE {active} ORDER BY updated_at DESC,id LIMIT 4")],
            "stage_totals": [dict(row) for row in db.execute(f"SELECT stage_id,stage,currency,count(*) deal_count,sum(value) value,sum(margin_minor) margin_minor FROM deals WHERE {active} GROUP BY stage_id,stage,currency")],
            "active_deal_count": db.execute(f"SELECT count(*) FROM deals WHERE {active} AND stage_id NOT IN ('won','lost')").fetchone()[0],
            "activities": [row_to_dict(row) for row in db.execute(f"SELECT * FROM activities WHERE {active} ORDER BY occurred_at DESC, id LIMIT 8")]}
