"""Persist redaction-safe results returned by governed app dependencies."""

from __future__ import annotations

from typing import Any

from activity import record_activity
from errors import MartaOpsError
from validation import _find, _now, _text


CALLBACK_ACTIONS = {
    "integrations.mail_connections_refreshed",
    "integrations.calendar_connections_refreshed",
    "integrations.calendar_calendars_refreshed",
    "integrations.storage_refreshed",
    "integrations.mail_draft_completed",
    "integrations.calendar_event_completed",
    "integrations.storage_file_completed",
}

CALLBACK_ALIASES = {
    "integrations.mail_connections_refreshed": "mail",
    "integrations.calendar_connections_refreshed": "calendar",
    "integrations.calendar_calendars_refreshed": "calendar",
    "integrations.storage_refreshed": "storage",
    "integrations.mail_draft_completed": "mail",
    "integrations.calendar_event_completed": "calendar",
    "integrations.storage_file_completed": "storage",
}


def apply_integration_callback(
    state: dict[str, Any],
    action: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    if body.get("_app_surface") != "dependency_backend_request_callback":
        raise MartaOpsError("Callback integrazione non autorizzato.", status_code=403)
    if body.get("dependency_alias") != CALLBACK_ALIASES[action]:
        raise MartaOpsError("Callback integrazione non coerente.", status_code=409)
    _, payload, provider_app_id = _completed_result(body)
    options = state["integration_options"]
    preferences = state["integration_preferences"]

    if action == "integrations.mail_connections_refreshed":
        connections = [
            {
                "id": _bounded(item.get("id"), 160),
                "label": _bounded(
                    item.get("display_name") or item.get("email_address"),
                    200,
                ),
                "email": _bounded(item.get("email_address"), 320),
                "provider": _bounded(item.get("provider"), 40),
            }
            for item in _objects(payload.get("items"))
            if item.get("status") == "connected" and item.get("id")
        ][:20]
        options.update(
            mail_provider_app_id=provider_app_id,
            mail_connections=connections,
            refreshed_at=_now(),
        )
        valid_ids = {item["id"] for item in connections}
        if preferences["mail_connection_id"] not in valid_ids:
            preferences["mail_connection_id"] = (
                connections[0]["id"] if connections else ""
            )
        return {"integration_options": options, "integration_preferences": preferences}

    if action == "integrations.calendar_connections_refreshed":
        connections = [
            {
                "id": _bounded(item.get("id"), 160),
                "label": _bounded(
                    item.get("account_label") or item.get("account_id"),
                    200,
                ),
            }
            for item in _objects(payload.get("connections"))
            if item.get("status") == "connected" and item.get("id")
        ][:20]
        options.update(
            calendar_provider_app_id=provider_app_id,
            calendar_connections=connections,
            refreshed_at=_now(),
        )
        return {"integration_options": options}

    if action == "integrations.calendar_calendars_refreshed":
        writable = [
            {
                "connection_id": _bounded(item.get("connection_id"), 160),
                "provider_calendar_id": _bounded(
                    item.get("provider_calendar_id") or item.get("id"),
                    320,
                ),
                "summary": _bounded(item.get("summary"), 200),
                "timezone": _bounded(item.get("timezone"), 80),
                "primary": bool(item.get("primary")),
                "selected": bool(item.get("selected")),
            }
            for item in _objects(payload.get("calendars"))
            if item.get("access_role") in {"owner", "writer"}
            and item.get("connection_id")
            and (item.get("provider_calendar_id") or item.get("id"))
        ][:50]
        writable.sort(
            key=lambda item: (
                not item["selected"],
                not item["primary"],
                item["summary"].lower(),
            )
        )
        options.update(
            calendar_provider_app_id=provider_app_id,
            calendar_calendars=writable,
            refreshed_at=_now(),
        )
        valid = {
            (item["connection_id"], item["provider_calendar_id"])
            for item in writable
        }
        selected = (
            preferences["calendar_connection_id"],
            preferences["calendar_id"],
        )
        if selected not in valid:
            first = writable[0] if writable else {}
            preferences["calendar_connection_id"] = str(
                first.get("connection_id") or ""
            )
            preferences["calendar_id"] = str(
                first.get("provider_calendar_id") or ""
            )
        return {"integration_options": options, "integration_preferences": preferences}

    if action == "integrations.storage_refreshed":
        options.update(storage_provider_app_id=provider_app_id, refreshed_at=_now())
        return {"integration_options": options}

    work_id = _text(body.get("work_id"), "Id lavoro", required=True, max_length=80)
    work = _find(state["collaborations"], work_id, "Lavoro")
    original = body.get("request") if isinstance(body.get("request"), dict) else {}
    original_body = (
        original.get("body") if isinstance(original.get("body"), dict) else {}
    )

    if action == "integrations.mail_draft_completed":
        draft = payload.get("draft") if isinstance(payload.get("draft"), dict) else {}
        draft_id = _text(
            draft.get("id"),
            "Id bozza",
            required=True,
            max_length=160,
        )
        work["mail_draft"] = {
            "id": draft_id,
            "connection_id": _bounded(draft.get("connection_id"), 160),
            "provider_app_id": provider_app_id,
            "updated_at": _bounded(draft.get("updated_at") or _now(), 80),
        }
        work["updated_at"] = _now()
        record_activity(
            state,
            f"Bozza Mail aggiornata: {work['title']}",
            collaboration_id=work_id,
            contact_id=work.get("contact_id", ""),
        )
        return {"collaboration": work, "mail_draft": work["mail_draft"]}

    if action == "integrations.calendar_event_completed":
        event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
        event_id = _text(
            event.get("id"),
            "Id evento",
            required=True,
            max_length=160,
        )
        refs = (
            event.get("external_refs")
            if isinstance(event.get("external_refs"), dict)
            else {}
        )
        current = (
            work.get("calendar_event")
            if isinstance(work.get("calendar_event"), dict)
            else {}
        )
        work["calendar_event"] = {
            "id": event_id,
            "revision": max(1, _positive_int(event.get("revision"), 1)),
            "connection_id": _bounded(
                refs.get("calendar_connection_id") or current.get("connection_id"),
                160,
            ),
            "calendar_id": _bounded(
                refs.get("provider_calendar_id") or current.get("calendar_id"),
                320,
            ),
            "provider_app_id": provider_app_id,
            "start_date": _bounded(
                event.get("startTime") or original_body.get("startTime"),
                40,
            ),
            "updated_at": _bounded(event.get("updated_at") or _now(), 80),
        }
        work["updated_at"] = _now()
        record_activity(
            state,
            f"Calendario aggiornato: {work['title']}",
            collaboration_id=work_id,
            contact_id=work.get("contact_id", ""),
        )
        return {"collaboration": work, "calendar_event": work["calendar_event"]}

    file = payload.get("file") if isinstance(payload.get("file"), dict) else {}
    path = _text(
        file.get("workspace_relative_path"),
        "File Storage",
        required=True,
        max_length=1000,
    )
    requested_path = _text(
        original_body.get("workspace_relative_path"),
        "File richiesto",
        required=True,
        max_length=1000,
    )
    if path != requested_path:
        raise MartaOpsError(
            "Storage ha restituito un file diverso da quello richiesto.",
            status_code=409,
        )
    document = {
        "id": _text(
            file.get("id") or file.get("file_id"),
            "Id file",
            required=True,
            max_length=160,
        ),
        "name": _text(
            file.get("name"),
            "Nome file",
            required=True,
            max_length=240,
        ),
        "workspace_relative_path": path,
        "content_type": _bounded(file.get("content_type"), 160),
        "size_bytes": _positive_int(file.get("size_bytes"), 0),
        "sha256": _bounded(file.get("sha256"), 128),
        "provider_app_id": provider_app_id,
        "linked_at": _now(),
    }
    documents = [
        item
        for item in work.get("documents", [])
        if item.get("workspace_relative_path") != path
        and item.get("id") != document["id"]
    ]
    documents.append(document)
    work["documents"] = documents
    work["updated_at"] = _now()
    record_activity(
        state,
        f"Documento collegato: {document['name']}",
        collaboration_id=work_id,
        contact_id=work.get("contact_id", ""),
    )
    return {"collaboration": work, "document": document}


def _completed_result(
    body: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    if body.get("dependency_backend_status") != "completed":
        raise MartaOpsError(
            "L’app collegata non ha completato la richiesta.",
            status_code=502,
        )
    result = body.get("dependency_backend_result")
    if not isinstance(result, dict):
        raise MartaOpsError(
            "La risposta dell’app collegata non è valida.",
            status_code=502,
        )
    status_code = _http_status(result.get("status_code"))
    if status_code >= 400:
        raise MartaOpsError(
            "La risposta dell’app collegata non è valida.",
            status_code=502,
        )
    payload = result.get("json") if isinstance(result.get("json"), dict) else {}
    provider_app_id = _text(
        result.get("dependency_provider_app_id"),
        "Provider",
        required=True,
        max_length=160,
    )
    return result, payload, provider_app_id


def _objects(value: object) -> list[dict[str, Any]]:
    return (
        [item for item in value if isinstance(item, dict)]
        if isinstance(value, list)
        else []
    )


def _bounded(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _positive_int(value: object, default: int) -> int:
    try:
        return max(0, int(value if value is not None else default))
    except (TypeError, ValueError):
        return default


def _http_status(value: object) -> int:
    try:
        status = int(value)
    except (TypeError, ValueError):
        return 500
    return status if 100 <= status <= 599 else 500
