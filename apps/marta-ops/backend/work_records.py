"""Work, deliverable and idea records."""
from copy import deepcopy
from typing import Any
from validation import _now, _new_id, _text, _choice, _date, _email, _money_minor

COLLABORATION_KINDS = {"partnership", "organic", "event", "giuntitrail"}
PHASES = {"lead", "proposal", "confirmed", "production", "approval", "scheduled", "published", "completed", "paused", "lost"}
PAYMENT_STATUSES = {"not_due", "to_invoice", "invoiced", "overdue", "paid"}
CONTRACT_STATUSES = {"not_needed", "draft", "sent", "signed"}
DELIVERABLE_STATUSES = {"planned", "in_progress", "approval", "scheduled", "published"}
IDEA_STATUSES = {"inbox", "selected", "scheduled", "archived"}
def _collaboration(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    current = deepcopy(existing or {})
    created = not current
    defaults: dict[str, Any] = {
        "title": "",
        "partner": "",
        "partner_email": "",
        "contact_id": "",
        "kind": "partnership",
        "phase": "lead",
        "next_action": "",
        "due_date": "",
        "value_minor": 0,
        "payment_status": "not_due",
        "contract_status": "not_needed",
        "rights_expiry_date": "",
        "notes": "",
    }
    for key, default in defaults.items():
        if key in payload or created:
            current[key] = payload.get(key, default)
    current.update(
        {
            "title": _text(current.get("title"), "Titolo", required=True, max_length=160),
            "partner": _text(current.get("partner"), "Partner", max_length=160),
            "partner_email": _email(current.get("partner_email"), "Email partner"),
            "contact_id": _text(current.get("contact_id"), "Id contatto", max_length=80),
            "kind": _choice(current.get("kind"), "Tipo", COLLABORATION_KINDS, "partnership"),
            "phase": _choice(current.get("phase"), "Fase", PHASES, "lead"),
            "next_action": _text(current.get("next_action"), "Prossima azione", max_length=240),
            "due_date": _date(current.get("due_date"), "Scadenza"),
            "value_minor": _money_minor(current.get("value_minor")),
            "payment_status": _choice(current.get("payment_status"), "Pagamento", PAYMENT_STATUSES, "not_due"),
            "contract_status": _choice(current.get("contract_status"), "Contratto", CONTRACT_STATUSES, "not_needed"),
            "rights_expiry_date": _date(current.get("rights_expiry_date"), "Scadenza diritti"),
            "notes": _text(current.get("notes"), "Note", max_length=4000),
        }
    )
    timestamp = _now()
    current.setdefault("id", _new_id("work"))
    current.setdefault("deliverables", [])
    current.setdefault("created_at", timestamp)
    current["updated_at"] = timestamp
    return current


def _idea(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    current = deepcopy(existing or {})
    created = not current
    for key, default in {"title": "", "pillar": "", "note": "", "status": "inbox"}.items():
        if key in payload or created:
            current[key] = payload.get(key, default)
    current.update(
        {
            "title": _text(current.get("title"), "Idea", required=True, max_length=200),
            "pillar": _text(current.get("pillar"), "Pillar", max_length=100),
            "note": _text(current.get("note"), "Nota", max_length=1200),
            "status": _choice(current.get("status"), "Stato idea", IDEA_STATUSES, "inbox"),
        }
    )
    timestamp = _now()
    current.setdefault("id", _new_id("idea"))
    current.setdefault("created_at", timestamp)
    current["updated_at"] = timestamp
    return current


def _deliverable(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    current = deepcopy(existing or {})
    created = not current
    for key, default in {"title": "", "status": "planned", "due_date": ""}.items():
        if key in payload or created:
            current[key] = payload.get(key, default)
    current.update(
        {
            "title": _text(current.get("title"), "Deliverable", required=True, max_length=180),
            "status": _choice(current.get("status"), "Stato deliverable", DELIVERABLE_STATUSES, "planned"),
            "due_date": _date(current.get("due_date"), "Scadenza deliverable"),
        }
    )
    timestamp = _now()
    current.setdefault("id", _new_id("item"))
    current.setdefault("created_at", timestamp)
    current["updated_at"] = timestamp
    return current

