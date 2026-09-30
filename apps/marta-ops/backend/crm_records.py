"""Contacts and actionable follow-ups; no independent CRM infrastructure."""
from copy import deepcopy
from typing import Any
from validation import _boolean, _choice, _date, _email, _find, _new_id, _now, _object, _text, validate_links
from errors import MartaOpsError
from activity import record_activity


def contact_record(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    current = deepcopy(existing or {})
    defaults = {"name": "", "company": "", "role": "", "email": "", "phone": "", "notes": "", "tags": [], "archived": False}
    for key, default in defaults.items():
        if key in payload or not existing:
            current[key] = payload.get(key, default)
    for key, maximum in [("name", 160), ("company", 160), ("role", 160), ("phone", 80), ("notes", 4000)]:
        current[key] = _text(current.get(key), key, required=key == "name", max_length=maximum)
    current["email"] = _email(current.get("email"), "Email contatto")
    current["archived"] = _boolean(current.get("archived", False), "Archiviato")
    tags = current.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 20:
        raise MartaOpsError("I tag devono essere un elenco di massimo 20 elementi.")
    current["tags"] = list(dict.fromkeys(_text(tag, "Tag", required=True, max_length=40) for tag in tags))
    current.setdefault("id", _new_id("contact"))
    current.setdefault("created_at", _now())
    current["updated_at"] = _now()
    return current


def task_record(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    current = deepcopy(existing or {})
    defaults = {"title": "", "kind": "task", "due_date": "", "contact_id": "", "collaboration_id": "", "done": False, "notes": ""}
    for key, default in defaults.items():
        if key in payload or not existing:
            current[key] = payload.get(key, default)
    current["title"] = _text(current.get("title"), "Attività", required=True, max_length=240)
    current["notes"] = _text(current.get("notes"), "Note", max_length=2000)
    current["kind"] = _choice(current.get("kind"), "Tipo attività", {"task", "call", "email", "meeting"}, "task")
    current["due_date"] = _date(current.get("due_date"), "Scadenza attività")
    for key in ("contact_id", "collaboration_id"):
        current[key] = _text(current.get(key), key, max_length=80)
    current["done"] = _boolean(current.get("done"), "Completata")
    current["completed_at"] = ((existing or {}).get("completed_at") or _now()) if current["done"] else ""
    current.setdefault("id", _new_id("task"))
    current.setdefault("created_at", _now())
    current["updated_at"] = _now()
    return current


def handle_crm_action(state: dict[str, Any], action: str, body: dict[str, Any]) -> dict[str, Any]:
    is_contact = action.endswith("contact")
    resource, builder = ("contact", contact_record) if is_contact else ("task", task_record)
    collection = state["contacts" if is_contact else "tasks"]
    creating = action.startswith("create_")
    incoming = _object(body, resource if creating else "changes")
    previous = None if creating else _find(collection, _text(body.get("id"), "Id", required=True, max_length=80), "Contatto" if is_contact else "Attività")
    item = builder(incoming, previous)
    validate_links(state, item)
    if creating:
        collection.append(item)
    else:
        previous.clear()
        previous.update(item)
    if is_contact:
        label = "Contatto aggiunto" if creating else "Contatto aggiornato"
        record_activity(state, f"{label}: {item['name']}", contact_id=item["id"])
    else:
        label = "Attività aggiunta" if creating else "Attività completata" if item["done"] else "Attività aggiornata"
        record_activity(state, f"{label}: {item['title']}", contact_id=item["contact_id"], collaboration_id=item["collaboration_id"])
    return {resource: item}
