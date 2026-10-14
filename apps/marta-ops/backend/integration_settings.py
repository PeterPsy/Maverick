"""App-owned integration preferences and linked-document removal."""

from __future__ import annotations

from typing import Any

from activity import record_activity
from errors import MartaOpsError
from validation import _find, _now, _text


def update_integration_preferences(
    state: dict[str, Any],
    changes: dict[str, Any],
) -> dict[str, Any]:
    preferences = state["integration_preferences"]
    options = state["integration_options"]
    if "mail_connection_id" in changes:
        mail_id = _text(
            changes.get("mail_connection_id"),
            "Account Mail",
            max_length=160,
        )
        valid_mail_ids = {item.get("id") for item in options["mail_connections"]}
        if mail_id and mail_id not in valid_mail_ids:
            raise MartaOpsError("L’account Mail scelto non è disponibile.")
        preferences["mail_connection_id"] = mail_id
    if "calendar_connection_id" in changes or "calendar_id" in changes:
        connection_id = _text(
            changes.get(
                "calendar_connection_id",
                preferences["calendar_connection_id"],
            ),
            "Account Calendario",
            max_length=160,
        )
        calendar_id = _text(
            changes.get("calendar_id", preferences["calendar_id"]),
            "Calendario",
            max_length=320,
        )
        valid_calendars = {
            (item.get("connection_id"), item.get("provider_calendar_id"))
            for item in options["calendar_calendars"]
        }
        if (
            (connection_id or calendar_id)
            and (connection_id, calendar_id) not in valid_calendars
        ):
            raise MartaOpsError("Il calendario scelto non è disponibile.")
        preferences["calendar_connection_id"] = connection_id
        preferences["calendar_id"] = calendar_id
    return {"integration_preferences": preferences}


def unlink_document(
    state: dict[str, Any],
    work_id: object,
    document_id: object,
) -> dict[str, Any]:
    item_id = _text(work_id, "Id lavoro", required=True, max_length=80)
    linked_id = _text(document_id, "Id documento", required=True, max_length=160)
    work = _find(state["collaborations"], item_id, "Lavoro")
    documents = work.get("documents", [])
    document = next((item for item in documents if item.get("id") == linked_id), None)
    if not document:
        raise MartaOpsError("Documento collegato non trovato.", status_code=404)
    work["documents"] = [item for item in documents if item.get("id") != linked_id]
    work["updated_at"] = _now()
    record_activity(
        state,
        f"Documento scollegato: {document.get('name') or 'File'}",
        collaboration_id=item_id,
        contact_id=work.get("contact_id", ""),
    )
    return {"collaboration": work, "document": document}
