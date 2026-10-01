"""Mounted backend dispatch for Marta Ops."""
from pathlib import Path
from typing import Any
from errors import MartaOpsError
from store import load_state, mutate_state
from validation import _text, _object, _find, _now
from work_records import _collaboration, _idea, _deliverable
from integration_callbacks import CALLBACK_ACTIONS, apply_integration_callback
from integration_settings import unlink_document, update_integration_preferences
from integrations import (
    calendar_event_request,
    integration_refresh_requests,
    mail_draft_request,
    storage_file_request,
)
from activity import add_note, record_activity
from crm_records import handle_crm_action
from pipeline import move_work, next_order
from validation import validate_links

MUTATING_ACTIONS = {
    "create_collaboration",
    "update_collaboration",
    "add_deliverable",
    "update_deliverable",
    "create_idea",
    "update_idea",
    "move_collaboration",
    "create_contact",
    "update_contact",
    "create_task",
    "update_task",
    "add_note",
    "unlink_storage_file",
    "update_integration_preferences",
    *CALLBACK_ACTIONS,
}
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
            validate_links(state, item)
            item["pipeline_order"] = next_order(state, item["phase"])
            state["collaborations"].append(item)
            record_activity(state, f"Lavoro aggiunto: {item['title']}", collaboration_id=item["id"], contact_id=item["contact_id"])
            return {"collaboration": item}

        state, result = mutate_state(data_root, create)
    elif action == "update_collaboration":
        item_id = _text(body.get("id"), "Id", required=True, max_length=80)
        changes = _object(body, "changes")

        def update(state: dict[str, Any]) -> dict[str, Any]:
            item = _find(state["collaborations"], item_id, "Lavoro")
            updated = _collaboration(changes, item)
            validate_links(state, updated)
            phase_changed = updated["phase"] != item["phase"]
            if phase_changed:
                updated["pipeline_order"] = next_order(state, updated["phase"])
            item.clear()
            item.update(updated)
            record_activity(state, f"{'Fase aggiornata' if phase_changed else 'Lavoro aggiornato'}: {item['title']}", collaboration_id=item["id"], contact_id=item["contact_id"])
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
            record_activity(state, f"Deliverable {'aggiunto' if action == 'add_deliverable' else 'aggiornato'}: {item['title']}", collaboration_id=collaboration_id, contact_id=collaboration.get("contact_id", ""))
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
    elif action == "move_collaboration":
        state, result = mutate_state(data_root, lambda current: move_work(current, body))
    elif action in {"create_contact", "update_contact", "create_task", "update_task"}:
        state, result = mutate_state(data_root, lambda current: handle_crm_action(current, action, body))
    elif action == "add_note":
        state, result = mutate_state(data_root, lambda current: add_note(current, body))
    elif action == "update_integration_preferences":
        changes = _object(body, "changes")
        state, result = mutate_state(
            data_root,
            lambda current: update_integration_preferences(current, changes),
        )
    elif action == "unlink_storage_file":
        state, result = mutate_state(
            data_root,
            lambda current: unlink_document(current, body.get("id"), body.get("document_id")),
        )
    elif action in CALLBACK_ACTIONS:
        state, result = mutate_state(
            data_root,
            lambda current: apply_integration_callback(current, action, body),
        )
    elif action == "refresh_integrations":
        state = load_state(data_root)
        result = {"dependency_backend_requests": integration_refresh_requests()}
    elif action == "link_storage_file":
        state = load_state(data_root)
        _find(state["collaborations"], _text(body.get("id"), "Id", required=True, max_length=80), "Lavoro")
        result = {
            "dependency_backend_requests": [
                storage_file_request(body.get("id"), body.get("workspace_relative_path"))
            ]
        }
    elif action in {"create_mail_draft", "create_calendar_event"}:
        item_id = _text(body.get("id"), "Id", required=True, max_length=80)
        state = load_state(data_root)
        item = _find(state["collaborations"], item_id, "Lavoro")
        if item.get("contact_id") and not item.get("partner_email"):
            contact = _find(state["contacts"], item["contact_id"], "Contatto")
            item = {**item, "partner_email": contact["email"]}
        request = (
            mail_draft_request(item, state["integration_preferences"])
            if action == "create_mail_draft"
            else calendar_event_request(
                item,
                state["integration_preferences"],
                state["integration_options"],
            )
        )
        result = {"dependency_backend_requests": [request]}
    else:
        raise MartaOpsError(f"Azione non supportata: {action}.")

    return 200, {**result, "state": state}


def app_events_for_action(action: str) -> list[dict[str, str]]:
    """Notify mounted clients after app-owned state changes."""
    if action.strip().lower() not in MUTATING_ACTIONS:
        return []
    return [{"type": "maverick.app.data-changed", "owner_app_id": "marta-ops", "resource": "state"}]
