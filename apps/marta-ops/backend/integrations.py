"""Governed Mail, Calendar and Storage dependency requests."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from errors import MartaOpsError
from validation import _date, _email, _new_id, _text


def integration_refresh_requests() -> list[dict[str, Any]]:
    """Read only the bounded provider metadata needed by the work drawer."""
    return [
        _request(
            "mail",
            {"action": "connections.list"},
            "integrations.mail_connections_refreshed",
        ),
        _request(
            "calendar",
            {"action": "calendar_connections.list"},
            "integrations.calendar_connections_refreshed",
        ),
        _request(
            "calendar",
            {"action": "calendar_calendars.list"},
            "integrations.calendar_calendars_refreshed",
        ),
        _request(
            "storage",
            {"action": "catalog", "limit": 1},
            "integrations.storage_refreshed",
        ),
    ]


def mail_draft_request(
    item: dict[str, Any],
    preferences: dict[str, Any],
) -> dict[str, Any]:
    recipient = _email(item.get("partner_email"), "Email partner")
    if not recipient:
        raise MartaOpsError("Aggiungi l’email del partner prima di creare la bozza.")
    connection_id = _text(
        preferences.get("mail_connection_id"),
        "Account Mail",
        max_length=160,
    )
    if not connection_id:
        raise MartaOpsError("Scegli l’account Mail da usare nelle integrazioni.")
    next_action = str(item.get("next_action") or "").strip()
    body_lines = [
        "Ciao,",
        "",
        next_action or f"Ti scrivo per aggiornarci su {item['title']}.",
        "",
        "A presto,",
        "Marta",
    ]
    body: dict[str, Any] = {
        "action": "mail_create_draft",
        "connection_id": connection_id,
        "to": [{"email": recipient}],
        "subject": f"{item['title']} — prossimi passi",
        "body_text": "\n".join(body_lines),
        "workspace_attachments": [
            document["workspace_relative_path"]
            for document in item.get("documents", [])
            if isinstance(document, dict) and document.get("workspace_relative_path")
        ],
    }
    current = (
        item.get("mail_draft")
        if isinstance(item.get("mail_draft"), dict)
        else {}
    )
    if current.get("id") and current.get("connection_id") == connection_id:
        body.pop("connection_id", None)
        body.update(action="mail_update_draft", draft_id=current["id"])
    return _request(
        "mail",
        body,
        "integrations.mail_draft_completed",
        {"work_id": item["id"]},
    )


def calendar_event_request(
    item: dict[str, Any],
    preferences: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, Any]:
    due_date = _date(item.get("due_date"), "Scadenza")
    if not due_date:
        raise MartaOpsError("Aggiungi una scadenza prima di creare l’evento.")
    next_day = (date.fromisoformat(due_date) + timedelta(days=1)).isoformat()
    description_parts = []
    if item.get("partner"):
        description_parts.append(f"Partner: {item['partner']}")
    if item.get("next_action"):
        description_parts.append(f"Prossima azione: {item['next_action']}")
    common: dict[str, Any] = {
        "title": item["title"],
        "description": "\n".join(description_parts),
        "startTime": due_date,
        "endTime": next_day,
        "all_day": True,
        "category": "Deadline",
        "conflict_policy": "warn",
    }
    current = (
        item.get("calendar_event")
        if isinstance(item.get("calendar_event"), dict)
        else {}
    )
    if current.get("id") and int(current.get("revision") or 0) > 0:
        body = {
            "action": "update",
            "id": current["id"],
            "expected_revision": int(current["revision"]),
            **common,
        }
    else:
        connection_id = _text(
            preferences.get("calendar_connection_id"),
            "Account Calendario",
            max_length=160,
        )
        calendar_id = _text(
            preferences.get("calendar_id"),
            "Calendario",
            max_length=320,
        )
        if not connection_id or not calendar_id:
            raise MartaOpsError("Scegli il calendario Google da usare nelle integrazioni.")
        calendar = next(
            (
                value
                for value in options.get("calendar_calendars", [])
                if value.get("connection_id") == connection_id
                and value.get("provider_calendar_id") == calendar_id
            ),
            None,
        )
        if not calendar:
            raise MartaOpsError(
                "Il calendario scelto non è più disponibile. Aggiorna le connessioni."
            )
        body = {
            "action": "create",
            **common,
            "timezone": calendar.get("timezone") or "Europe/Rome",
            "source": "google_calendar",
            "external_refs": {
                "provider": "google",
                "calendar_connection_id": connection_id,
                "provider_calendar_id": calendar_id,
                "marta_ops": {"entity_type": "collaboration", "entity_id": item["id"]},
            },
            "idempotency_key": f"marta-ops:{item['id']}:calendar",
        }
    return _request(
        "calendar",
        body,
        "integrations.calendar_event_completed",
        {"work_id": item["id"]},
    )


def storage_file_request(
    work_id: object,
    workspace_relative_path: object,
) -> dict[str, Any]:
    item_id = _text(work_id, "Id", required=True, max_length=80)
    path = _text(
        workspace_relative_path,
        "File Storage",
        required=True,
        max_length=1000,
    )
    if not path.startswith(("storage/uploaded/", "storage/generated/")):
        raise MartaOpsError("Scegli un file locale da Storage.")
    return _request(
        "storage",
        {"action": "file_info", "workspace_relative_path": path},
        "integrations.storage_file_completed",
        {"work_id": item_id},
    )


def _request(
    alias: str,
    body: dict[str, Any],
    callback_action: str,
    callback_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "request_id": _new_id(alias),
        "dependency_alias": alias,
        "body": body,
        "callback": {"action": callback_action, "payload": callback_payload or {}},
    }
