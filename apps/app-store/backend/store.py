"""Workspace data store for the app-store app."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from core.app_sdk.storage import read_json_state, update_json_state, write_json_state


STATE_FILENAME = "state.json"
SCHEMA_VERSION = "1"
PINNED_APPS_IDEMPOTENCY_KEY = "_pinned_apps_idempotency"
MAX_PINNED_APPS_IDEMPOTENCY_RECORDS = 64
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,199}$")


def utcnow() -> str:
    return datetime.now(tz=UTC).isoformat()


def default_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_url": "",
        "pinned_apps": ["chat"],
        "view_filter": {
            "mode": "search",
            "query": "",
            "scope": "all",
            "title": "",
            "refs": [],
            "updated_at": utcnow(),
        },
        "recent_installs": [],
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }


def state_path(data_root: Path) -> Path:
    return data_root / STATE_FILENAME


def load_state(data_root: Path) -> dict[str, Any]:
    path = state_path(data_root)
    if not path.exists():
        return seed_state(data_root)
    payload = read_json_state(data_root, STATE_FILENAME)
    if not isinstance(payload, dict):
        return seed_state(data_root)
    payload.setdefault("pinned_apps", ["chat"])
    payload.setdefault(
        "view_filter",
        {
            "mode": "search",
            "query": "",
            "scope": "all",
            "title": "",
            "refs": [],
            "updated_at": utcnow(),
        },
    )
    return payload


def save_state(data_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    data_root.mkdir(parents=True, exist_ok=True)
    state["schema_version"] = SCHEMA_VERSION
    state["updated_at"] = utcnow()
    write_json_state(data_root, STATE_FILENAME, state)
    return public_state(state)


def seed_state(data_root: Path) -> dict[str, Any]:
    state = default_state()
    return save_state(data_root, state)


def remember_install(data_root: Path, *, app_id: str, version: str, workspace_ids: list[str]) -> dict[str, Any]:
    state = load_state(data_root)
    installs = state.setdefault("recent_installs", [])
    if not isinstance(installs, list):
        installs = []
        state["recent_installs"] = installs
    installs.insert(
        0,
        {
            "app_id": app_id,
            "version": version,
            "workspace_ids": workspace_ids,
            "installed_at": utcnow(),
        },
    )
    state["recent_installs"] = installs[:20]
    return save_state(data_root, state)


def pinned_apps(data_root: Path) -> list[str]:
    pinned = load_state(data_root).get("pinned_apps", [])
    if not isinstance(pinned, list):
        return []
    return [item for item in pinned if isinstance(item, str) and item.strip()]


def set_pinned_apps(data_root: Path, app_ids: list[str]) -> dict[str, Any]:
    state = load_state(data_root)
    unique_ids = []
    for app_id in app_ids:
        normalized = app_id.strip()
        if normalized and normalized not in unique_ids:
            unique_ids.append(normalized)
    state["pinned_apps"] = unique_ids
    return save_state(data_root, state)


def set_pinned_apps_idempotent(
    data_root: Path,
    *,
    requested_app_ids: list[str],
    stored_app_ids: list[str],
    idempotency_key: str,
    request_fingerprint: str,
) -> tuple[dict[str, Any], bool]:
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise ValueError("idempotency_key is invalid.")
    canonical_request = json.dumps(
        {"action": "pinned_apps.set", "app_ids": requested_app_ids},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    expected_fingerprint = f"sha256:{hashlib.sha256(canonical_request).hexdigest()}"
    if request_fingerprint != expected_fingerprint:
        raise ValueError("request_fingerprint does not match the pinned_apps.set request.")

    normalized_stored_ids = _unique_app_ids(stored_app_ids)
    replayed = False

    def update(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal replayed
        records = state.get(PINNED_APPS_IDEMPOTENCY_KEY)
        records = records if isinstance(records, list) else []
        for record in records:
            if not isinstance(record, dict) or record.get("idempotency_key") != idempotency_key:
                continue
            if record.get("request_fingerprint") != request_fingerprint:
                raise ValueError("idempotency_key is already bound to a different pinned_apps.set request.")
            replayed = True
            return state

        state["pinned_apps"] = normalized_stored_ids
        records.append(
            {
                "idempotency_key": idempotency_key,
                "request_fingerprint": request_fingerprint,
                "pinned_apps": normalized_stored_ids,
                "completed_at": utcnow(),
            }
        )
        state[PINNED_APPS_IDEMPOTENCY_KEY] = records[-MAX_PINNED_APPS_IDEMPOTENCY_RECORDS:]
        state["schema_version"] = SCHEMA_VERSION
        state["updated_at"] = utcnow()
        return state

    state = update_json_state(data_root, STATE_FILENAME, update, default=default_state())
    if replayed:
        records = state.get(PINNED_APPS_IDEMPOTENCY_KEY)
        matching = (
            next(
                (
                    record
                    for record in records
                    if isinstance(record, dict) and record.get("idempotency_key") == idempotency_key
                ),
                {},
            )
            if isinstance(records, list)
            else {}
        )
        replayed_ids = matching.get("pinned_apps") if isinstance(matching, dict) else []
        replay_state = public_state(state)
        replay_state["pinned_apps"] = _unique_app_ids(replayed_ids if isinstance(replayed_ids, list) else [])
        return replay_state, True
    return public_state(state), False


def toggle_pinned_app(data_root: Path, app_id: str) -> dict[str, Any]:
    current = pinned_apps(data_root)
    if app_id in current:
        return set_pinned_apps(data_root, [item for item in current if item != app_id])
    return set_pinned_apps(data_root, [*current, app_id])


def public_state(state: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in state.items() if not key.startswith("_")}


def _unique_app_ids(app_ids: list[Any]) -> list[str]:
    unique_ids: list[str] = []
    for app_id in app_ids:
        normalized = str(app_id).strip()
        if normalized and normalized not in unique_ids:
            unique_ids.append(normalized)
    return unique_ids


def view_filter_state(data_root: Path) -> dict[str, Any]:
    state = load_state(data_root)
    view_filter = state.get("view_filter")
    if not isinstance(view_filter, dict):
        state["view_filter"] = default_state()["view_filter"]
        save_state(data_root, state)
        view_filter = state["view_filter"]
    return view_filter


def set_view_filter(data_root: Path, *, query: object = None, scope: object = None, preserve_custom: bool = False) -> dict[str, Any]:
    state = load_state(data_root)
    current = state.get("view_filter") if isinstance(state.get("view_filter"), dict) else {}
    next_scope = str(scope or current.get("scope") or "all").strip() or "all"
    if next_scope not in {"all", "catalog", "installed", "local"}:
        raise ValueError("scope must be one of: all, catalog, installed, local")
    state["view_filter"] = {
        "mode": "custom" if preserve_custom and current.get("mode") == "custom" else "search",
        "query": str(query if query is not None else current.get("query") or "").strip(),
        "scope": next_scope,
        "title": str(current.get("title") or "") if preserve_custom and current.get("mode") == "custom" else "",
        "refs": list(current.get("refs") or []) if preserve_custom and current.get("mode") == "custom" else [],
        "updated_at": utcnow(),
    }
    return save_state(data_root, state)


def set_custom_view(data_root: Path, *, title: object = None, refs: object = None, query: object = None, scope: object = None) -> dict[str, Any]:
    next_scope = str(scope or "all").strip() or "all"
    if next_scope not in {"all", "catalog", "installed", "local"}:
        raise ValueError("scope must be one of: all, catalog, installed, local")
    normalized_refs: list[dict[str, str]] = []
    for item in refs if isinstance(refs, list) else []:
        if not isinstance(item, dict):
            continue
        entity_type = str(item.get("entity_type") or "").strip()
        entity_id = str(item.get("entity_id") or "").strip()
        if entity_type != "installed_app" or not entity_id:
            raise ValueError("custom view refs must target installed_app entities")
        normalized_refs.append({"entity_type": entity_type, "entity_id": entity_id})
    state = load_state(data_root)
    state["view_filter"] = {
        "mode": "custom",
        "query": str(query or "").strip(),
        "scope": next_scope,
        "title": str(title or "").strip(),
        "refs": normalized_refs,
        "updated_at": utcnow(),
    }
    return save_state(data_root, state)


def clear_custom_view(data_root: Path) -> dict[str, Any]:
    state = load_state(data_root)
    current = state.get("view_filter") if isinstance(state.get("view_filter"), dict) else {}
    state["view_filter"] = {
        "mode": "search",
        "query": str(current.get("query") or "").strip(),
        "scope": str(current.get("scope") or "all").strip() or "all",
        "title": "",
        "refs": [],
        "updated_at": utcnow(),
    }
    return save_state(data_root, state)
