"""CRM search, listing, and reference reads."""

from __future__ import annotations

from pathlib import Path
import re
import sqlite3
from typing import Any

from database import connect, ensure_schema, normalize_entity_type, row_payload
from records import get_entity_with_context


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


REFERENCE_MANIFEST = {
    "app_id": "crm",
    "schema_version": "1",
    "entity_types": [
        {"entity_type": "account", "display_name": "Account", "id_stability": "stable", "searchable": True, "resolvable": True, "summarizable": True, "deep_link_supported": True},
        {"entity_type": "contact", "display_name": "Contact", "id_stability": "stable", "searchable": True, "resolvable": True, "summarizable": True, "deep_link_supported": True},
        {"entity_type": "deal", "display_name": "Deal", "id_stability": "stable", "searchable": True, "resolvable": True, "summarizable": True, "deep_link_supported": True},
        {"entity_type": "activity", "display_name": "Activity", "id_stability": "stable", "searchable": True, "resolvable": True, "summarizable": True, "deep_link_supported": True},
    ],
}


def fts_query(query: str) -> str:
    tokens = TOKEN_PATTERN.findall(query)
    if not tokens:
        return ""
    return " OR ".join(f"{token}*" for token in tokens[:12])


def title_for(entity_type: str, item: dict[str, Any]) -> str:
    if entity_type == "account":
        return item["name"]
    if entity_type == "contact":
        return item["display_name"]
    if entity_type == "deal":
        return item["name"]
    return item["subject"]


def body_for(entity_type: str, item: dict[str, Any]) -> str:
    if entity_type == "account":
        return " ".join([item.get("domain", ""), item.get("industry", ""), item.get("status", ""), item.get("summary", "")]).strip()
    if entity_type == "contact":
        return " ".join([item.get("email", ""), item.get("phone", ""), item.get("role", ""), item.get("summary", "")]).strip()
    if entity_type == "deal":
        return " ".join([item.get("stage", ""), str(item.get("value", "")), item.get("currency", ""), item.get("close_date", ""), item.get("summary", "")]).strip()
    return item.get("body", "")


def result_payload(entity_type: str, item: dict[str, Any], score: float = 0.0) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "entity_id": item["id"],
        "title": title_for(entity_type, item),
        "summary": body_for(entity_type, item)[:400],
        "score": score,
        "updated_at": item["updated_at"],
        "deep_link": f"/apps/crm/{entity_type}s/{item['id']}",
    }


def search_records(data_root: Path, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    ensure_schema(data_root)
    normalized_limit = max(1, min(int(limit or 10), 50))
    with connect(data_root) as db:
        search = fts_query(query)
        rows: list[sqlite3.Row] = []
        if search:
            try:
                rows = list(
                    db.execute(
                        """
                        SELECT entity_type, entity_id, bm25(crm_fts) AS score
                        FROM crm_fts
                        WHERE crm_fts MATCH ?
                        ORDER BY score
                        LIMIT ?
                        """,
                        (search, normalized_limit),
                    )
                )
            except sqlite3.OperationalError:
                rows = []
        results = []
        for row in rows:
            entity = get_entity_with_context(db, row["entity_type"], row["entity_id"])
            results.append(result_payload(row["entity_type"], entity, float(row["score"])))
        if results:
            return results
        like = f"%{query.strip()}%"
        fallback: list[tuple[str, sqlite3.Row]] = []
        fallback.extend(("account", row) for row in db.execute("SELECT * FROM accounts WHERE deleted_at IS NULL AND (name LIKE ? OR domain LIKE ? OR industry LIKE ? OR summary LIKE ?) ORDER BY updated_at DESC LIMIT ?", (like, like, like, like, normalized_limit)))
        fallback.extend(("contact", row) for row in db.execute("SELECT * FROM contacts WHERE deleted_at IS NULL AND (display_name LIKE ? OR email LIKE ? OR role LIKE ? OR summary LIKE ?) ORDER BY updated_at DESC LIMIT ?", (like, like, like, like, normalized_limit)))
        fallback.extend(("deal", row) for row in db.execute("SELECT * FROM deals WHERE deleted_at IS NULL AND (name LIKE ? OR stage LIKE ? OR summary LIKE ?) ORDER BY updated_at DESC LIMIT ?", (like, like, like, normalized_limit)))
        fallback.extend(("activity", row) for row in db.execute("SELECT * FROM activities WHERE deleted_at IS NULL AND (subject LIKE ? OR body LIKE ?) ORDER BY updated_at DESC LIMIT ?", (like, like, normalized_limit)))
        return [result_payload(entity_type, row_payload(row) or {}) for entity_type, row in fallback[:normalized_limit]]


def list_recent(data_root: Path, *, limit: int = 20) -> dict[str, Any]:
    ensure_schema(data_root)
    normalized_limit = max(1, min(int(limit or 20), 100))
    with connect(data_root) as db:
        return {
            "accounts": [row_payload(row) or {} for row in db.execute("SELECT * FROM accounts WHERE deleted_at IS NULL ORDER BY updated_at DESC LIMIT ?", (normalized_limit,))],
            "contacts": [row_payload(row) or {} for row in db.execute("SELECT * FROM contacts WHERE deleted_at IS NULL ORDER BY updated_at DESC LIMIT ?", (normalized_limit,))],
            "deals": [row_payload(row) or {} for row in db.execute("SELECT * FROM deals WHERE deleted_at IS NULL ORDER BY updated_at DESC LIMIT ?", (normalized_limit,))],
            "activities": [row_payload(row) or {} for row in db.execute("SELECT * FROM activities WHERE deleted_at IS NULL ORDER BY updated_at DESC LIMIT ?", (normalized_limit,))],
        }


def list_deals(data_root: Path, *, stage: str = "", limit: int = 50) -> list[dict[str, Any]]:
    ensure_schema(data_root)
    normalized_limit = max(1, min(int(limit or 50), 200))
    with connect(data_root) as db:
        if stage:
            rows = db.execute("SELECT * FROM deals WHERE deleted_at IS NULL AND stage = ? ORDER BY updated_at DESC LIMIT ?", (stage, normalized_limit))
        else:
            rows = db.execute("SELECT * FROM deals WHERE deleted_at IS NULL ORDER BY updated_at DESC LIMIT ?", (normalized_limit,))
        return [row_payload(row) or {} for row in rows]


def reference_search(data_root: Path, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    results = []
    for item in search_records(data_root, query, limit=limit):
        results.append(
            {
                "app_id": "crm",
                "entity_type": item["entity_type"],
                "entity_id": item["entity_id"],
                "title": item["title"],
                "subtitle": item["entity_type"],
                "summary": item["summary"],
                "confidence": 1.0,
                "deep_link": item["deep_link"],
            }
        )
    return results


def reference_resolve(data_root: Path, entity_type: str, entity_id: str) -> dict[str, Any]:
    normalized_type = normalize_entity_type(entity_type)
    with connect(data_root) as db:
        entity = get_entity_with_context(db, normalized_type, entity_id)
    return {
        "exists": True,
        "app_id": "crm",
        "entity_type": normalized_type,
        "entity_id": entity["id"],
        "title": title_for(normalized_type, entity),
        "subtitle": normalized_type,
        "deep_link": f"/apps/crm/{normalized_type}s/{entity['id']}",
        "updated_at": entity["updated_at"],
    }


def reference_summarize(data_root: Path, entity_type: str, entity_id: str) -> dict[str, Any]:
    normalized_type = normalize_entity_type(entity_type)
    with connect(data_root) as db:
        entity = get_entity_with_context(db, normalized_type, entity_id)
    return {
        "summary": body_for(normalized_type, entity) or title_for(normalized_type, entity),
        "safe_fields": {key: value for key, value in entity.items() if key not in {"metadata", "relationships"}},
        "source_updated_at": entity["updated_at"],
    }
