"""Calendar connection record normalization."""

from __future__ import annotations

from typing import Any

from constants import (
    ALLOWED_CONNECTION_STATUSES,
    GOOGLE_PROVIDER,
    GOOGLE_REFRESH_TOKEN_LOGICAL_NAME,
    MAX_CONNECTIONS,
    MAX_LIST_ITEM_LENGTH,
    MAX_PROVIDER_ID_LENGTH,
)
from scalars import clean_string, json_object, string_list
from time_values import optional_time_string


def normalize_connections(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [normalize_connection(item) for item in value[:MAX_CONNECTIONS] if isinstance(item, dict)]


def normalize_connection(payload: dict[str, Any]) -> dict[str, Any]:
    connection_id = clean_string(
        payload.get("id") or payload.get("connection_id") or payload.get("connectionId"),
        "connection_id",
        required=True,
        max_length=MAX_LIST_ITEM_LENGTH,
    )
    provider = _provider(payload.get("provider"))
    account_id = clean_string(
        payload.get("account_id")
        or payload.get("accountId")
        or payload.get("calendar_account_id")
        or payload.get("calendarAccountId"),
        "account_id",
        max_length=MAX_PROVIDER_ID_LENGTH,
    )
    account_label = clean_string(
        payload.get("account_label")
        or payload.get("accountLabel")
        or payload.get("calendar_account_label")
        or payload.get("calendarAccountLabel")
        or account_id,
        "account_label",
        max_length=MAX_PROVIDER_ID_LENGTH,
    )
    return {
        "id": connection_id,
        "resource_type": "calendar_connection",
        "provider": provider,
        "account_id": account_id,
        "account_label": account_label,
        "status": _connection_status(payload.get("status")),
        "scopes": string_list(payload.get("scopes")),
        "created_at": optional_time_string(payload.get("created_at") or payload.get("createdAt"), "created_at"),
        "updated_at": optional_time_string(payload.get("updated_at") or payload.get("updatedAt"), "updated_at"),
        "last_sync_at": optional_time_string(payload.get("last_sync_at") or payload.get("lastSyncAt"), "last_sync_at"),
        "token_resource": _token_resource(connection_id),
        "external_refs": json_object(payload.get("external_refs") or payload.get("externalRefs"), "external_refs"),
    }


def _provider(value: Any) -> str:
    provider = str(value or GOOGLE_PROVIDER).strip().lower()
    if provider != GOOGLE_PROVIDER:
        raise ValueError("Calendar connections currently support provider `google` only.")
    return provider


def _connection_status(value: Any) -> str:
    status = str(value or "connected").strip().lower()
    if status not in ALLOWED_CONNECTION_STATUSES:
        raise ValueError("Calendar connection status must be one of: connected, disabled, error, pending.")
    return status


def _token_resource(connection_id: str) -> dict[str, str]:
    return {
        "logical_name": GOOGLE_REFRESH_TOKEN_LOGICAL_NAME,
        "resource_type": "calendar_connection",
        "resource_id": connection_id,
    }
