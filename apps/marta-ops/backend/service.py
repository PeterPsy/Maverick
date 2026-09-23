"""Product behavior for Marta Ops."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from errors import MartaOpsError
from store import load_state, mutate_state


COLLABORATION_KINDS = {"partnership", "organic", "event", "giuntitrail"}
PHASES = {"lead", "proposal", "confirmed", "production", "approval", "scheduled", "published", "completed", "paused", "lost"}
PAYMENT_STATUSES = {"not_due", "to_invoice", "invoiced", "overdue", "paid"}
CONTRACT_STATUSES = {"not_needed", "draft", "sent", "signed"}
DELIVERABLE_STATUSES = {"planned", "in_progress", "approval", "scheduled", "published"}
IDEA_STATUSES = {"inbox", "selected", "scheduled", "archived"}
MUTATING_ACTIONS = {
    "create_collaboration",
    "update_collaboration",
    "add_deliverable",
    "update_deliverable",
    "create_idea",
    "update_idea",
}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def _text(value: object, field: str, *, required: bool = False, max_length: int = 500) -> str:
    cleaned = str(value or "").strip()
    if required and not cleaned:
        raise MartaOpsError(f"{field} è obbligatorio.")
    if len(cleaned) > max_length:
        raise MartaOpsError(f"{field} è troppo lungo.")
    return cleaned


def _choice(value: object, field: str, allowed: set[str], default: str) -> str:
    cleaned = str(value or default).strip()
    if cleaned not in allowed:
        raise MartaOpsError(f"{field} non è valido.")
    return cleaned


def _date(value: object, field: str) -> str:
    cleaned = _text(value, field, max_length=10)
    if not cleaned:
        return ""
    try:
        date.fromisoformat(cleaned)
    except ValueError as exc:
        raise MartaOpsError(f"{field} deve essere una data valida.") from exc
    return cleaned


def _email(value: object, field: str) -> str:
    cleaned = _text(value, field, max_length=320)
    if cleaned and not EMAIL_PATTERN.fullmatch(cleaned):
        raise MartaOpsError(f"{field} non è valida.")
    return cleaned


def _money_minor(value: object) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, bool):
        raise MartaOpsError("Il valore economico non è valido.")
    try:
        amount = int(value)
    except (TypeError, ValueError) as exc:
        raise MartaOpsError("Il valore economico non è valido.") from exc
    if amount < 0 or amount > 1_000_000_000:
        raise MartaOpsError("Il valore economico è fuori intervallo.")
    return amount


def _object(body: dict[str, Any], key: str) -> dict[str, Any]:
    value = body.get(key)
    if not isinstance(value, dict):
        raise MartaOpsError(f"{key} deve essere un oggetto.")
    return value


def _find(items: list[dict[str, Any]], item_id: str, label: str) -> dict[str, Any]:
    for item in items:
        if str(item.get("id") or "") == item_id:
            return item
    raise MartaOpsError(f"{label} non trovato.", status_code=404)


def _collaboration(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    current = deepcopy(existing or {})
    created = not current
    defaults: dict[str, Any] = {
        "title": "",
        "partner": "",
        "partner_email": "",
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


def handle_action(data_root: Path, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Dispatch one mounted backend action."""
    action = str(body.get("action") or "bootstrap").strip().lower()
    if action in {"bootstrap", "status"}:
        state = load_state(data_root)
        return 200, {"app_id": "marta-ops", "status": "ready", "state": state}

    if action == "create_collaboration":
        incoming = _object(body, "collaboration")

        def create(state: dict[str, Any]) -> dict[str, Any]:
            item = _collaboration(incoming)
            state["collaborations"].append(item)
            return {"collaboration": item}

        state, result = mutate_state(data_root, create)
    elif action == "update_collaboration":
        item_id = _text(body.get("id"), "Id", required=True, max_length=80)
        changes = _object(body, "changes")

        def update(state: dict[str, Any]) -> dict[str, Any]:
            item = _find(state["collaborations"], item_id, "Lavoro")
            updated = _collaboration(changes, item)
            item.clear()
            item.update(updated)
            return {"collaboration": item}

        state, result = mutate_state(data_root, update)
    elif action in {"add_deliverable", "update_deliverable"}:
        collaboration_id = _text(body.get("collaboration_id"), "Id lavoro", required=True, max_length=80)
        incoming = _object(body, "deliverable" if action == "add_deliverable" else "changes")

        def change_deliverable(state: dict[str, Any]) -> dict[str, Any]:
            collaboration = _find(state["collaborations"], collaboration_id, "Lavoro")
            deliverables = collaboration.setdefault("deliverables", [])
            if action == "add_deliverable":
                item = _deliverable(incoming)
                deliverables.append(item)
            else:
                item_id = _text(body.get("id"), "Id deliverable", required=True, max_length=80)
                item = _find(deliverables, item_id, "Deliverable")
                updated = _deliverable(incoming, item)
                item.clear()
                item.update(updated)
            collaboration["updated_at"] = _now()
            return {"deliverable": item, "collaboration": collaboration}

        state, result = mutate_state(data_root, change_deliverable)
    elif action == "create_idea":
        incoming = _object(body, "idea")

        def create_idea(state: dict[str, Any]) -> dict[str, Any]:
            item = _idea(incoming)
            state["ideas"].append(item)
            return {"idea": item}

        state, result = mutate_state(data_root, create_idea)
    elif action == "update_idea":
        item_id = _text(body.get("id"), "Id", required=True, max_length=80)
        changes = _object(body, "changes")

        def update_idea(state: dict[str, Any]) -> dict[str, Any]:
            item = _find(state["ideas"], item_id, "Idea")
            updated = _idea(changes, item)
            item.clear()
            item.update(updated)
            return {"idea": item}

        state, result = mutate_state(data_root, update_idea)
    elif action in {"create_mail_draft", "create_calendar_event"}:
        item_id = _text(body.get("id"), "Id", required=True, max_length=80)
        state = load_state(data_root)
        item = _find(state["collaborations"], item_id, "Lavoro")
        request = _mail_draft_request(item) if action == "create_mail_draft" else _calendar_event_request(item)
        result = {"dependency_backend_requests": [request]}
    else:
        raise MartaOpsError(f"Azione non supportata: {action}.")

    return 200, {**result, "state": state}


def app_events_for_action(action: str) -> list[dict[str, str]]:
    """Notify mounted clients after app-owned state changes."""
    if action.strip().lower() not in MUTATING_ACTIONS:
        return []
    return [{"type": "maverick.app.data-changed", "owner_app_id": "marta-ops", "resource": "state"}]
