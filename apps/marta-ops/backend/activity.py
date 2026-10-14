"""Plain-text notes and an app-owned operational timeline."""
from typing import Any
from validation import _new_id, _now, _text, validate_links
from errors import MartaOpsError


def record_activity(state: dict[str, Any], title: str, *, contact_id: str = "", collaboration_id: str = "", kind: str = "change", text: str = "") -> dict[str, Any]:
    event = {"id": _new_id("activity"), "kind": kind, "title": title, "text": text,
             "contact_id": contact_id, "collaboration_id": collaboration_id, "created_at": _now()}
    state["activity"].append(event)
    return event


def add_note(state: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    links = {key: _text(body.get(key), key, max_length=80) for key in ("contact_id", "collaboration_id")}
    if not any(links.values()):
        raise MartaOpsError("Collega la nota a un contatto o a un lavoro.")
    validate_links(state, links)
    text = _text(body.get("text"), "Nota", required=True, max_length=4000)
    return {"activity": record_activity(state, "Nota aggiunta", kind="note", text=text, **links)}
