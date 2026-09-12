"""Persisted sidebar and catalog view state."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from schema import utcnow

DEFAULT_VIEW = {"mode": "search", "query": "", "decision": "all", "email_status": "all", "title": "", "refs": []}


def read_view_state(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute("SELECT value_json, updated_at FROM app_state WHERE key='view_filter'").fetchone()
    if row is None:
        return {**DEFAULT_VIEW, "updated_at": utcnow()}
    try:
        value = json.loads(row["value_json"])
    except json.JSONDecodeError:
        value = {}
    return {**DEFAULT_VIEW, **value, "updated_at": row["updated_at"]}


def write_view_state(connection: sqlite3.Connection, value: dict[str, Any]) -> dict[str, Any]:
    decision = str(value.get("decision") or "all").strip()[:100]
    if decision not in {"all", "da_valutare", "scartato", "riserva", "selezionato"}:
        raise ValueError(f"Unsupported decision filter: {decision}")
    email_status = str(value.get("email_status") or "all").strip()[:100]
    if email_status not in {"all", "da_contattare", "email_inviata", "risposta_ricevuta", "nessuna_risposta"}:
        raise ValueError(f"Unsupported email filter: {email_status}")
    state = {
        "mode": "custom" if value.get("mode") == "custom" else "search",
        "query": str(value.get("query") or "").strip()[:500],
        "decision": decision,
        "email_status": email_status,
        "title": str(value.get("title") or "").strip()[:500],
        "refs": normalize_refs(value.get("refs")),
    }
    now = utcnow()
    connection.execute(
        "INSERT INTO app_state(key,value_json,updated_at) VALUES('view_filter',?,?) "
        "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
        (json.dumps(state, ensure_ascii=False), now),
    )
    return {**state, "updated_at": now}


def normalize_refs(raw: object) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return refs
    for item in raw[:500]:
        if not isinstance(item, dict) or str(item.get("entity_type")) != "candidate":
            continue
        entity_id = str(item.get("entity_id") or "").strip()
        if entity_id and entity_id not in {ref["entity_id"] for ref in refs}:
            refs.append({"entity_type": "candidate", "entity_id": entity_id})
    return refs
