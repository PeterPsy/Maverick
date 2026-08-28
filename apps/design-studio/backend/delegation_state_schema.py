"""Closed persisted/public schemas for bounded OpenDesign delegation metadata."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


SCHEMA_VERSION = 2
DELEGATION_ID_PATTERN = re.compile(r"^dlg_[a-f0-9]{32}$")
NATIVE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$")
TERMINAL_STATUSES = {"succeeded", "failed", "canceled"}
PERSISTED_STATUSES = {
    "preparing",
    "submitting",
    "submission_uncertain",
    "submission_failed",
    "queued",
    "running",
    "awaiting_input",
    "unknown",
    *TERMINAL_STATUSES,
}
RECORD_FIELDS = {
    "delegation_id",
    "request_fingerprint",
    "run_submission_started",
    "status",
    "od_project_id",
    "od_conversation_id",
    "od_message_id",
    "od_assistant_message_id",
    "od_run_id",
    "event_cursor",
    "result_references",
    "deep_link",
    "created_at",
    "updated_at",
    "completed_at",
    "operation_owner",
    "operation_expires_at",
}


def default_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "delegations": {},
        "view_state": clean_view_state({}),
        "updated_at": "",
    }


def normalized_state(raw: dict[str, Any]) -> dict[str, Any]:
    records = raw.get("delegations") if isinstance(raw.get("delegations"), dict) else {}
    cleaned_records = {
        identifier: clean_record(record)
        for identifier, record in records.items()
        if isinstance(identifier, str)
        and DELEGATION_ID_PATTERN.fullmatch(identifier)
        and isinstance(record, dict)
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "delegations": cleaned_records,
        "view_state": clean_view_state(raw.get("view_state")),
        "updated_at": str(raw.get("updated_at") or "")[:64],
    }


def clean_record(record: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    delegation_id = str(record.get("delegation_id") or "")
    if DELEGATION_ID_PATTERN.fullmatch(delegation_id):
        cleaned["delegation_id"] = delegation_id
    status = str(record.get("status") or "unknown")
    cleaned["status"] = status if status in PERSISTED_STATUSES else "unknown"
    fingerprint = str(record.get("request_fingerprint") or "")
    cleaned["request_fingerprint"] = (
        fingerprint
        if len(fingerprint) == 64
        and all(character in "0123456789abcdef" for character in fingerprint)
        else ""
    )
    cleaned["run_submission_started"] = record.get("run_submission_started") is True
    for key in (
        "od_project_id",
        "od_conversation_id",
        "od_message_id",
        "od_assistant_message_id",
        "od_run_id",
    ):
        value = str(record.get(key) or "")
        cleaned[key] = value if not value or NATIVE_ID_PATTERN.fullmatch(value) else ""
    cursor = str(record.get("event_cursor") or "")
    cleaned["event_cursor"] = (
        cursor if not cursor or (cursor.isdigit() and len(cursor) <= 32) else ""
    )
    cleaned["result_references"] = _clean_result_references(
        record.get("result_references")
    )
    link = str(record.get("deep_link") or "")
    cleaned["deep_link"] = link[:512] if link.startswith("/app/design-studio/") else ""
    for key in ("created_at", "updated_at", "completed_at"):
        cleaned[key] = str(record.get(key) or "")[:64]
    owner = str(record.get("operation_owner") or "")
    cleaned["operation_owner"] = owner[:64] if owner.isalnum() else ""
    expiry = record.get("operation_expires_at")
    cleaned["operation_expires_at"] = (
        float(expiry)
        if isinstance(expiry, (int, float))
        and not isinstance(expiry, bool)
        and expiry >= 0
        else 0
    )
    return cleaned


def clean_view_state(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    mode = "custom" if source.get("mode") == "custom" else "search"
    project_ids = source.get("project_ids") if isinstance(source.get("project_ids"), list) else []
    return {
        "mode": mode,
        "query": str(source.get("query") or "").strip()[:200],
        "title": str(source.get("title") or "").strip()[:120],
        "project_ids": [
            item
            for item in project_ids
            if isinstance(item, str) and NATIVE_ID_PATTERN.fullmatch(item)
        ][:100],
    }


def public_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return the display-safe public projection of one delegation record."""
    cleaned = clean_record(record)
    return {
        "delegation_id": cleaned.get("delegation_id", ""),
        "status": cleaned.get("status", "unknown"),
        "opendesign": {
            "project_id": cleaned.get("od_project_id", ""),
            "conversation_id": cleaned.get("od_conversation_id", ""),
            "message_id": cleaned.get("od_message_id", ""),
            "assistant_message_id": cleaned.get("od_assistant_message_id", ""),
            "run_id": cleaned.get("od_run_id", ""),
        },
        "event_cursor": cleaned.get("event_cursor", ""),
        "result_references": deepcopy(cleaned.get("result_references", {})),
        "deep_link": cleaned.get("deep_link", ""),
        "created_at": cleaned.get("created_at", ""),
        "updated_at": cleaned.get("updated_at", ""),
        "completed_at": cleaned.get("completed_at", ""),
    }


def validate_delegation_id(value: object) -> str:
    identifier = str(value or "").strip()
    if not DELEGATION_ID_PATTERN.fullmatch(identifier):
        raise ValueError("A valid delegation id is required.")
    return identifier


def _clean_result_references(value: object) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    if not source:
        return {}
    run_id = str(source.get("run_id") or "")
    project = source.get("project") if isinstance(source.get("project"), dict) else {}
    project_id = str(project.get("id") or "")
    file_count = project.get("file_count")
    artifacts = source.get("artifacts") if isinstance(source.get("artifacts"), list) else []
    return {
        "run_id": run_id if NATIVE_ID_PATTERN.fullmatch(run_id) else "",
        "project": {
            "id": project_id if NATIVE_ID_PATTERN.fullmatch(project_id) else "",
            "name": str(project.get("name") or "").replace("\x00", "")[:200],
            "file_count": (
                file_count
                if isinstance(file_count, int)
                and not isinstance(file_count, bool)
                and file_count >= 0
                else 0
            ),
        },
        "artifacts": [
            {
                "reference_id": str(item.get("reference_id") or "")[:40],
                "title": str(item.get("title") or "").replace("\x00", "")[:200],
                "kind": str(item.get("kind") or "")[:80],
                "renderer": str(item.get("renderer") or "")[:80],
                "status": str(item.get("status") or "")[:80],
            }
            for item in artifacts[:100]
            if isinstance(item, dict)
        ],
    }
