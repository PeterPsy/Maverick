"""Structured Calendar surface error payloads."""

from __future__ import annotations

from typing import Any


def validation_error(action: str, detail: str) -> dict[str, Any]:
    """Return a structured validation error with corrective metadata."""
    response: dict[str, Any] = {
        "error": "validation_error",
        "operation": action,
        "detail": detail,
        "expected_fields": _expected_fields(action),
        "example": _example_for_action(action),
    }
    if "color" in detail:
        response["allowed_values"] = {"color": _allowed_values()["color"]}
    if "limit" in detail:
        response["allowed_values"] = {"limit": {"minimum": 1, "maximum": _limit_maximum_for_action(action)}}
    if "conflict_policy" in detail:
        response["allowed_values"] = {"conflict_policy": _allowed_values()["conflict_policy"]}
    if "status" in detail:
        response["allowed_values"] = {"event_status": _allowed_values()["event_status"]}
    if "move_strategy" in detail:
        response["allowed_values"] = {"move_strategy": _allowed_values()["move_strategy"]}
    return response


def not_found_error(action: str, detail: str) -> dict[str, Any]:
    """Return a structured not-found error."""
    return {
        "error": "not_found",
        "operation": action,
        "detail": detail,
        "entity_type": "event",
        "expected_fields": [],
        "example": _example_for_action(action),
    }


def conflict_error(action: str, detail: str, conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a structured scheduling conflict error."""
    return {
        "error": "calendar_conflict",
        "operation": action,
        "detail": detail,
        "conflicts": conflicts,
        "expected_fields": _expected_fields(action),
        "allowed_values": {"conflict_policy": _allowed_values()["conflict_policy"]},
        "example": _example_for_action(action),
    }


def revision_conflict_error(
    action: str,
    detail: str,
    *,
    event_id: str,
    expected_revision: int,
    actual_revision: int,
    current_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a structured optimistic-concurrency conflict error."""
    return {
        "error": "revision_conflict",
        "operation": action,
        "detail": detail,
        "entity_type": "event",
        "entity_id": event_id,
        "expected_revision": expected_revision,
        "actual_revision": actual_revision,
        "current_event": current_event or {},
        "expected_fields": _expected_fields(action),
        "example": _example_for_action(action),
    }


def unsupported_action(action: str) -> dict[str, Any]:
    """Return a structured unsupported-action error."""
    return {
        "error": "unsupported_action",
        "operation": action,
        "detail": f"Unsupported Calendar action `{action}`.",
        "allowed_values": _allowed_actions(),
        "example": {"action": "operations.manifest"},
    }


def _example_for_action(action: str) -> dict[str, Any]:
    if action == "create":
        return {"action": "create", "title": "Team standup", "startTime": "2026-05-22T09:00:00Z", "endTime": "2026-05-22T09:30:00Z"}
    if action == "update":
        return {"action": "update", "id": "evt_<id>", "expected_revision": 1, "title": "Updated title"}
    if action == "delete":
        return {"action": "delete", "id": "evt_<id>", "expected_revision": 1}
    if action == "move":
        return {"action": "move", "id": "evt_<id>", "expected_revision": 1, "startTime": "2026-05-22T10:00:00Z", "conflict_policy": "warn"}
    if action == "check_availability":
        return {"action": "check_availability", "startTime": "2026-05-22T09:00:00Z", "endTime": "2026-05-22T09:30:00Z"}
    if action == "find_free_time":
        return {"action": "find_free_time", "start_after": "2026-05-22T09:00:00Z", "end_before": "2026-05-22T17:00:00Z", "duration_minutes": 30}
    if action == "set_view_filter":
        return {"action": "set_view_filter", "query": "launch", "start_after": "2026-05-22T00:00:00Z"}
    if action == "set_custom_view":
        return {"action": "set_custom_view", "title": "Launch week", "entity_ids": ["evt_<id>"]}
    if action in {"references.resolve", "references.summarize"}:
        return {"action": action, "entity_type": "event", "entity_id": "evt_<id>"}
    return {"action": action}


def _limit_maximum_for_action(action: str) -> int:
    if action in {"find_free_time", "references.search"}:
        return 50
    return 500


def _expected_fields(action: str) -> list[str]:
    from surface_actions import EXPECTED_FIELDS_BY_ACTION

    return EXPECTED_FIELDS_BY_ACTION.get(action, [])


def _allowed_actions() -> list[str]:
    from surface_actions import ALLOWED_ACTIONS

    return ALLOWED_ACTIONS


def _allowed_values() -> dict[str, Any]:
    from surface_manifest import operations_manifest

    return operations_manifest()["allowed_values"]
