"""Durable, exact-version approvals for browser persistence of Storage files."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.app_sdk.storage import read_json_state, update_json_state


STATE_FILE = "file_cache_approvals.json"
SCHEMA_VERSION = "1"
APPROVED_DATA_CLASS = "workspace_internal"


def approval_for_version(data_root: Path, *, file_id: str, source_version: str) -> dict[str, Any] | None:
    """Return a normalized approval only when both stable identity parts match."""
    normalized_file_id = str(file_id or "").strip()
    normalized_version = str(source_version or "").strip()
    if not normalized_file_id or not normalized_version:
        return None
    for approval in _read_state(data_root)["approvals"]:
        if approval["file_id"] == normalized_file_id and approval["source_version"] == normalized_version:
            return dict(approval)
    return None


def approve_version(
    data_root: Path,
    *,
    file_id: str,
    source_version: str,
    approved_by_user_id: str,
) -> dict[str, Any]:
    """Approve one exact immutable revision as workspace-internal browser data."""
    normalized_file_id = str(file_id or "").strip()
    normalized_version = str(source_version or "").strip()
    if not normalized_file_id or not normalized_version:
        raise ValueError("A stable file id and source version are required for cache approval.")
    approval = {
        "file_id": normalized_file_id,
        "source_version": normalized_version,
        "data_class": APPROVED_DATA_CLASS,
        "cache_approved": True,
        "privacy_approved": False,
        "regulated_allowlisted": False,
        "approved_at": datetime.now(tz=UTC).isoformat(),
        "approved_by_user_id": str(approved_by_user_id or "").strip(),
    }

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        normalized = _normalize_state(state)
        normalized["approvals"] = [
            item for item in normalized["approvals"] if item["file_id"] != normalized_file_id
        ]
        normalized["approvals"].append(approval)
        return normalized

    update_json_state(data_root, STATE_FILE, updater, _empty_state())
    return dict(approval)


def revoke_approval(data_root: Path, *, file_id: str) -> bool:
    """Remove every approval for one stable file identity."""
    normalized_file_id = str(file_id or "").strip()
    removed = False

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal removed
        normalized = _normalize_state(state)
        retained = [item for item in normalized["approvals"] if item["file_id"] != normalized_file_id]
        removed = len(retained) != len(normalized["approvals"])
        normalized["approvals"] = retained
        return normalized

    update_json_state(data_root, STATE_FILE, updater, _empty_state())
    return removed


def public_approval(approval: dict[str, Any]) -> dict[str, Any]:
    """Project approval metadata without actor identifiers."""
    normalized = _normalize_approval(approval)
    return {
        "file_id": normalized["file_id"],
        "source_version": normalized["source_version"],
        "data_class": normalized["data_class"],
        "approved_at": normalized["approved_at"],
    }


def _read_state(data_root: Path) -> dict[str, Any]:
    return _normalize_state(read_json_state(data_root, STATE_FILE, _empty_state()))


def _empty_state() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "approvals": []}


def _normalize_state(payload: dict[str, Any]) -> dict[str, Any]:
    raw_approvals = payload.get("approvals") if isinstance(payload.get("approvals"), list) else []
    approvals: list[dict[str, Any]] = []
    for item in raw_approvals:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_approval(item)
        if (
            normalized["file_id"]
            and normalized["source_version"]
            and normalized["data_class"] == APPROVED_DATA_CLASS
            and normalized["cache_approved"] is True
        ):
            approvals.append(normalized)
    return {"schema_version": SCHEMA_VERSION, "approvals": approvals}


def _normalize_approval(payload: dict[str, Any]) -> dict[str, Any]:
    data_class = str(payload.get("data_class") or "").strip()
    return {
        "file_id": str(payload.get("file_id") or "").strip(),
        "source_version": str(payload.get("source_version") or "").strip(),
        "data_class": data_class if data_class == APPROVED_DATA_CLASS else "",
        "cache_approved": payload.get("cache_approved") is True,
        "privacy_approved": False,
        "regulated_allowlisted": False,
        "approved_at": str(payload.get("approved_at") or "").strip(),
        "approved_by_user_id": str(payload.get("approved_by_user_id") or "").strip(),
    }
