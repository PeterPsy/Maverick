"""Declared Mail and Calendar dependency requests."""
from datetime import date, timedelta
from typing import Any
from errors import MartaOpsError
from validation import _email, _date, _new_id

def _mail_draft_request(item: dict[str, Any]) -> dict[str, Any]:
    recipient = _email(item.get("partner_email"), "Email partner")
    if not recipient:
        raise MartaOpsError("Aggiungi l’email del partner prima di creare la bozza.")
    next_action = str(item.get("next_action") or "").strip()
    body_lines = ["Ciao,", ""]
    if next_action:
        body_lines.append(next_action)
    else:
        body_lines.append(f"Ti scrivo per aggiornarci su {item['title']}.")
    body_lines.extend(["", "A presto,", "Marta"])
    return {
        "request_id": _new_id("mail"),
        "dependency_alias": "mail",
        "body": {
            "action": "mail_create_draft",
            "to": [{"email": recipient}],
            "subject": f"{item['title']} — prossimi passi",
            "body_text": "\n".join(body_lines),
        },
    }


def _calendar_event_request(item: dict[str, Any]) -> dict[str, Any]:
    due_date = _date(item.get("due_date"), "Scadenza")
    if not due_date:
        raise MartaOpsError("Aggiungi una scadenza prima di creare l’evento.")
    next_day = (date.fromisoformat(due_date) + timedelta(days=1)).isoformat()
    description_parts = []
    if item.get("partner"):
        description_parts.append(f"Partner: {item['partner']}")
    if item.get("next_action"):
        description_parts.append(f"Prossima azione: {item['next_action']}")
    return {
        "request_id": _new_id("calendar"),
        "dependency_alias": "calendar",
        "body": {
            "action": "create",
            "title": item["title"],
            "description": "\n".join(description_parts),
            "startTime": due_date,
            "endTime": next_day,
            "timezone": "UTC",
            "all_day": True,
            "category": "Deadline",
            "source": "marta-ops",
            "external_refs": {
                "marta_ops": {"entity_type": "collaboration", "entity_id": item["id"]}
            },
            "idempotency_key": f"marta-ops:{item['id']}:{due_date}",
            "conflict_policy": "warn",
        },
    }


