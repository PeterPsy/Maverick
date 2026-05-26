"""Calendar timestamp and timezone normalization."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from constants import MAX_TIMEZONE_LENGTH
from scalars import clean_string


def event_time(value: Any, field: str, timezone_name: str) -> datetime:
    if not value:
        raise ValueError(f"`{field}` is required.")
    text = str(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError) as error:
        raise ValueError(f"`{field}` must be an ISO 8601 timestamp.") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.astimezone(timezone.utc)


def iso_time(value: Any, field: str) -> datetime:
    if not value:
        raise ValueError(f"`{field}` is required.")
    text = str(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError) as error:
        raise ValueError(f"`{field}` must be an ISO 8601 timestamp.") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def now_string() -> str:
    return format_time(datetime.now(timezone.utc))


def event_timestamp(value: Any, field: str, *, default: str) -> str:
    if not value:
        return default
    return format_time(iso_time(value, field))


def event_timezone(value: Any) -> str:
    text = clean_string(value or "UTC", "timezone", required=True, max_length=MAX_TIMEZONE_LENGTH)
    try:
        ZoneInfo(text)
    except ZoneInfoNotFoundError as error:
        raise ValueError("Event timezone must be a valid IANA timezone name.") from error
    return text


def optional_time_string(value: Any, field: str) -> str:
    if not value:
        return ""
    return format_time(iso_time(value, field))
