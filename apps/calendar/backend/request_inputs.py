"""Calendar action argument parsing and validation."""

from __future__ import annotations

from typing import Any

from constants import ALLOWED_CONFLICT_POLICIES, EVENT_FIELDS, MAX_LIST_ITEM_LENGTH
from scalars import clean_string, optional_bool, optional_int, string_list


def filter_kwargs(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "start_after": body.get("start_after") or body.get("startAfter"),
        "end_before": body.get("end_before") or body.get("endBefore"),
        "query": str(body.get("query") or ""),
        "tags": body.get("tags"),
        "category": body.get("category"),
        "attendee": body.get("attendee"),
    }


def event_payload(body: dict[str, Any]) -> dict[str, Any]:
    event_payload = body.get("event") or body.get("payload") or {}
    if not isinstance(event_payload, dict):
        raise ValueError("Calendar event payload must be an object.")
    direct_fields = {key: value for key, value in body.items() if key in EVENT_FIELDS}
    return {**event_payload, **direct_fields}


def expected_revision(body: dict[str, Any]) -> int | None:
    nested = body.get("event") if isinstance(body.get("event"), dict) else body.get("payload")
    candidates: list[Any] = []
    for field in ("expected_revision", "expectedRevision"):
        if field in body:
            candidates.append(body.get(field))
    if isinstance(nested, dict):
        for field in ("expected_revision", "expectedRevision"):
            if field in nested:
                candidates.append(nested.get(field))
    value = next((item for item in candidates if item is not None), None)
    return optional_int(value, field="expected_revision", minimum=1)


def idempotency_key_from_payload(event_payload: dict[str, Any]) -> str:
    return clean_string(
        event_payload.get("idempotency_key") or event_payload.get("idempotencyKey"),
        "idempotency_key",
        max_length=160,
    )


def conflict_policy_from_body(body: dict[str, Any]) -> str:
    nested = body.get("event") if isinstance(body.get("event"), dict) else body.get("payload")
    nested_policy = None
    if isinstance(nested, dict):
        nested_policy = nested.get("conflict_policy") or nested.get("conflictPolicy")
    return normalize_conflict_policy(body.get("conflict_policy") or body.get("conflictPolicy") or nested_policy or "allow")


def move_strategy(body: dict[str, Any]) -> str:
    if optional_bool(body.get("first_free") or body.get("firstFree"), default=False):
        return "first_free"
    strategy = str(body.get("move_strategy") or body.get("moveStrategy") or "fixed_time").strip().lower()
    if strategy not in {"fixed_time", "first_free"}:
        raise ValueError("`move_strategy` must be `fixed_time` or `first_free`.")
    return strategy


def normalize_conflict_policy(value: Any) -> str:
    policy = str(value or "allow").strip().lower()
    if policy not in ALLOWED_CONFLICT_POLICIES:
        raise ValueError("`conflict_policy` must be `allow`, `reject`, or `warn`.")
    return policy


def participants_from_body(body: dict[str, Any]) -> set[str]:
    participants = set(string_list(body.get("attendees")))
    attendee = str(body.get("attendee") or "").strip()
    if attendee:
        participants.add(attendee[:MAX_LIST_ITEM_LENGTH])
    return participants


def required_string(body: dict[str, Any], field: str) -> str:
    value = str(body.get(field) or "").strip()
    if not value:
        raise ValueError(f"`{field}` is required.")
    return value


def reference_id(body: dict[str, Any]) -> str:
    entity_type = str(body.get("entity_type") or "event").strip()
    validate_reference_entity_type(entity_type)
    value = str(body.get("entity_id") or body.get("id") or "").strip()
    if not value:
        raise ValueError("`entity_id` is required.")
    return value


def validate_reference_entity_type(entity_type: str) -> None:
    if entity_type != "event":
        raise ValueError("Calendar references support only entity_type `event`.")
