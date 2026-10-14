"""Workspace-owned JSON persistence for Marta Ops."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from core.app_sdk.storage import read_json_state, update_json_state

from errors import MartaOpsError


STATE_FILE = "state.json"
SCHEMA_VERSION = "3"


def default_state() -> dict[str, Any]:
    """Return a fresh empty Marta Ops state."""
    return {
        "schema_version": SCHEMA_VERSION,
        "collaborations": [],
        "ideas": [],
        "contacts": [],
        "tasks": [],
        "activity": [],
        "integration_options": {
            "mail_provider_app_id": "",
            "calendar_provider_app_id": "",
            "storage_provider_app_id": "",
            "mail_connections": [],
            "calendar_connections": [],
            "calendar_calendars": [],
            "refreshed_at": "",
        },
        "integration_preferences": {
            "mail_connection_id": "",
            "calendar_connection_id": "",
            "calendar_id": "",
        },
    }


def normalize_state(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Validate the small stable storage envelope."""
    state = dict(raw or {})
    normalized = {**state, "schema_version": SCHEMA_VERSION}
    for key in ("collaborations", "ideas", "contacts", "tasks", "activity"):
        items = state.get(key, [])
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise MartaOpsError("Lo stato di Marta Ops non è valido.", status_code=500)
        normalized[key] = [dict(item) for item in items]
    for index, item in enumerate(normalized["collaborations"]):
        item.setdefault("contact_id", "")
        item.setdefault("pipeline_order", index)
        item.setdefault("documents", [])
        item.setdefault("mail_draft", {})
        item.setdefault("calendar_event", {})
        if not isinstance(item["documents"], list) or any(not isinstance(document, dict) for document in item["documents"]):
            raise MartaOpsError("I documenti di un lavoro non sono validi.", status_code=500)
        if not isinstance(item["mail_draft"], dict) or not isinstance(item["calendar_event"], dict):
            raise MartaOpsError("I collegamenti di un lavoro non sono validi.", status_code=500)
    options = state.get("integration_options", {})
    preferences = state.get("integration_preferences", {})
    if not isinstance(options, dict) or not isinstance(preferences, dict):
        raise MartaOpsError("Le impostazioni delle integrazioni non sono valide.", status_code=500)
    normalized["integration_options"] = {
        "mail_provider_app_id": str(options.get("mail_provider_app_id") or ""),
        "calendar_provider_app_id": str(options.get("calendar_provider_app_id") or ""),
        "storage_provider_app_id": str(options.get("storage_provider_app_id") or ""),
        "mail_connections": _object_list(options.get("mail_connections")),
        "calendar_connections": _object_list(options.get("calendar_connections")),
        "calendar_calendars": _object_list(options.get("calendar_calendars")),
        "refreshed_at": str(options.get("refreshed_at") or ""),
    }
    normalized["integration_preferences"] = {
        "mail_connection_id": str(preferences.get("mail_connection_id") or ""),
        "calendar_connection_id": str(preferences.get("calendar_connection_id") or ""),
        "calendar_id": str(preferences.get("calendar_id") or ""),
    }
    return normalized


def _object_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def load_state(data_root: Path) -> dict[str, Any]:
    """Load a defensive copy of workspace state."""
    return deepcopy(normalize_state(read_json_state(data_root, STATE_FILE, default_state())))


def mutate_state(
    data_root: Path,
    mutator: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Atomically mutate state and return the updated state plus action result."""
    result: dict[str, Any] = {}

    def apply(raw: dict[str, Any]) -> dict[str, Any]:
        state = normalize_state(raw)
        result.update(mutator(state) or {})
        return state

    state = update_json_state(data_root, STATE_FILE, apply, default=default_state())
    return deepcopy(normalize_state(state)), deepcopy(result)
