"""CRM account summaries and account-level insight payloads."""

from __future__ import annotations

from typing import Any

from domains.record_intelligence import intelligent_next_actions
from store import get_record, row_to_dict


def summarize_account(db, account_id: str) -> dict[str, Any]:
    account = get_record(db, "account", account_id)
    contacts = [row_to_dict(row) for row in db.execute("SELECT * FROM contacts WHERE account_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 10", (account_id,)).fetchall()]
    deals = [row_to_dict(row) for row in db.execute("SELECT * FROM deals WHERE account_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 10", (account_id,)).fetchall()]
    activities = [row_to_dict(row) for row in db.execute("SELECT * FROM activities WHERE account_id = ? AND deleted_at IS NULL ORDER BY occurred_at DESC LIMIT 10", (account_id,)).fetchall()]
    tasks = [row_to_dict(row) for row in db.execute("SELECT * FROM tasks WHERE account_id = ? AND deleted_at IS NULL ORDER BY due_at ASC, updated_at DESC LIMIT 10", (account_id,)).fetchall()]
    notes = [row_to_dict(row) for row in db.execute("SELECT * FROM notes WHERE account_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 10", (account_id,)).fetchall()]
    return {"account": account, "contacts": contacts, "deals": deals, "activities": activities, "tasks": tasks, "notes": notes}


def account_brief(db, account_id: str) -> dict[str, Any]:
    summary = summarize_account(db, account_id)
    account = summary["account"]
    open_deals = [deal for deal in summary["deals"] if str(deal.get("stage") or "").lower() not in {"won", "lost"}]
    open_tasks = [task for task in summary["tasks"] if task.get("status") == "open"]
    next_actions = [action for action in intelligent_next_actions(db, {"limit": 20}) if action.get("entity_type") in {"account", "deal"} and (action.get("entity_id") == account_id or _action_belongs_to_account(db, action, account_id))]
    total_pipeline = sum(float(deal.get("value") or 0) for deal in open_deals)
    risks: list[str] = []
    if open_deals and not open_tasks:
        risks.append("Open pipeline exists without an open account task.")
    if not summary["contacts"]:
        risks.append("No contacts are linked to this account.")
    if any(not deal.get("close_date") for deal in open_deals):
        risks.append("At least one open deal has no close date.")
    opportunities: list[str] = []
    if total_pipeline:
        opportunities.append(f"Open pipeline value: {account.get('currency', 'EUR')} {total_pipeline:,.0f}.")
    if summary["contacts"]:
        opportunities.append(f"{len(summary['contacts'])} linked contact(s) available for outreach.")
    brief_lines = [
        f"{account['name']} is a {account.get('status') or 'prospect'} account.",
        f"Linked contacts: {len(summary['contacts'])}. Open deals: {len(open_deals)}. Open tasks: {len(open_tasks)}.",
    ]
    if account.get("summary"):
        brief_lines.append(str(account["summary"]))
    return {
        "ok": True,
        "account": account,
        "brief": "\n".join(brief_lines),
        "metrics": {"contacts": len(summary["contacts"]), "open_deals": len(open_deals), "open_tasks": len(open_tasks), "open_pipeline_value": total_pipeline},
        "risks": risks,
        "opportunities": opportunities,
        "next_actions": next_actions[:5],
        "source": summary,
    }


def _action_belongs_to_account(db, action: dict[str, Any], account_id: str) -> bool:
    if action.get("entity_type") == "deal":
        row = db.execute("SELECT account_id FROM deals WHERE id = ?", (str(action.get("entity_id") or ""),)).fetchone()
        return bool(row and row["account_id"] == account_id)
    return False
