"""Calendar scalar input normalization."""

from __future__ import annotations

import json
from typing import Any

from constants import MAX_LIST_ITEM_LENGTH, MAX_LIST_ITEMS, MAX_METADATA_LENGTH


def casefold_text(value: Any) -> str:
    return str(value or "").strip().casefold()


def casefold_set(values: Any) -> set[str]:
    return {str(item).strip().casefold() for item in values if str(item).strip()}


def json_object(value: Any, field: str) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Event {field} must be a JSON object.")
    return _bounded_json(value, field, expected_type=dict)


def json_list(value: Any, field: str) -> list[Any]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError(f"Event {field} must be a JSON array.")
    if len(value) > MAX_LIST_ITEMS:
        raise ValueError(f"Event {field} can contain at most {MAX_LIST_ITEMS} items.")
    return _bounded_json(value, field, expected_type=list)


def _bounded_json(value: Any, field: str, *, expected_type: type) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Event {field} must be JSON-serializable.") from error
    if len(encoded) > MAX_METADATA_LENGTH:
        raise ValueError(f"Event {field} must serialize to {MAX_METADATA_LENGTH} characters or fewer.")
    return json.loads(encoded)


def clean_string(value: Any, field: str, *, required: bool = False, max_length: int) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"Event {field} is required.")
    if len(text) > max_length:
        raise ValueError(f"Event {field} must be {max_length} characters or fewer.")
    return text


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value[:MAX_LIST_ITEMS]:
        text = str(item).strip()
        if text:
            items.append(text[:MAX_LIST_ITEM_LENGTH])
    return items


def optional_int(value: Any, *, field: str, minimum: int, maximum: int | None = None) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, bool) or isinstance(value, (dict, list, set, tuple)):
        raise ValueError(_integer_error(field, minimum=minimum, maximum=maximum))
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(_integer_error(field, minimum=minimum, maximum=maximum))
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(_integer_error(field, minimum=minimum, maximum=maximum)) from None
    if parsed < minimum:
        raise ValueError(_integer_error(field, minimum=minimum, maximum=maximum))
    if maximum is not None and parsed > maximum:
        raise ValueError(_integer_error(field, minimum=minimum, maximum=maximum))
    return parsed


def optional_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _integer_error(field: str, *, minimum: int, maximum: int | None) -> str:
    if maximum is None:
        return f"{field} must be an integer greater than or equal to {minimum}."
    return f"{field} must be an integer between {minimum} and {maximum}."
