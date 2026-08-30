"""Workspace-scoped metadata store for external OpenDesign delegations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from time import time
from typing import Any
from uuid import uuid4

from core.app_sdk.storage import read_json_state, update_json_state
from delegation_state_schema import (
    RECORD_FIELDS,
    TERMINAL_STATUSES,
    clean_record,
    clean_view_state,
    default_state,
    normalized_state,
    public_record,
    validate_delegation_id,
)


STATE_PATH = "delegations/state.json"
MAX_RECORDS = 1000
LEASE_SECONDS = 90
TERMINAL_RETENTION_SECONDS = 30 * 24 * 60 * 60


@dataclass(frozen=True)
class DelegationClaim:
    acquired: bool
    owner: str
    record: dict[str, Any]


class DelegationStoreError(RuntimeError):
    """The bounded delegation metadata store could not honor an operation."""


class DelegationStore:
    """Persist only correlation, status, cursor, link, and safe result references."""

    def __init__(self, data_root: str) -> None:
        if not str(data_root or "").strip():
            raise ValueError("A Design Studio data root is required.")
        self.data_root = data_root

    def get(self, delegation_id: str) -> dict[str, Any] | None:
        identifier = validate_delegation_id(delegation_id)
        state = normalized_state(read_json_state(self.data_root, STATE_PATH, default_state()))
        record = state["delegations"].get(identifier)
        return deepcopy(record) if isinstance(record, dict) else None

    def claim(self, delegation_id: str, initial: dict[str, Any]) -> DelegationClaim:
        identifier = validate_delegation_id(delegation_id)
        owner = uuid4().hex
        now_epoch = time()
        captured: dict[str, Any] = {}
        acquired = False

        def mutate(raw: dict[str, Any]) -> dict[str, Any]:
            nonlocal acquired, captured
            state = normalized_state(raw)
            records = state["delegations"]
            _prune_records(
                records,
                now_epoch=now_epoch,
                protected_ids={identifier},
            )
            record = records.get(identifier)
            if not isinstance(record, dict):
                _prune_records(records, reserve=1, now_epoch=now_epoch)
                if len(records) >= MAX_RECORDS:
                    raise DelegationStoreError("Delegation metadata capacity is exhausted.")
                now = utc_now()
                record = clean_record({
                    **initial,
                    "delegation_id": identifier,
                    "created_at": now,
                    "updated_at": now,
                })
                records[identifier] = record
            lease_expiry = record.get("operation_expires_at")
            if (
                record.get("operation_owner")
                and isinstance(lease_expiry, (int, float))
                and lease_expiry > now_epoch
            ):
                captured = deepcopy(record)
                return state
            record["operation_owner"] = owner
            record["operation_expires_at"] = now_epoch + LEASE_SECONDS
            record["updated_at"] = utc_now()
            acquired = True
            captured = deepcopy(record)
            state["updated_at"] = record["updated_at"]
            return state

        update_json_state(self.data_root, STATE_PATH, mutate, default_state())
        return DelegationClaim(acquired=acquired, owner=owner, record=captured)

    def patch(self, delegation_id: str, updates: dict[str, Any], *, owner: str | None = None) -> dict[str, Any]:
        identifier = validate_delegation_id(delegation_id)
        captured: dict[str, Any] = {}

        def mutate(raw: dict[str, Any]) -> dict[str, Any]:
            nonlocal captured
            state = normalized_state(raw)
            record = state["delegations"].get(identifier)
            if not isinstance(record, dict):
                raise DelegationStoreError("Delegation record not found.")
            if owner is not None and record.get("operation_owner") != owner:
                raise DelegationStoreError("Delegation operation lease was lost.")
            for key, value in updates.items():
                if key in RECORD_FIELDS:
                    record[key] = deepcopy(value)
            if owner is not None and record.get("operation_owner") == owner:
                record["operation_expires_at"] = time() + LEASE_SECONDS
            record = clean_record(record)
            record["updated_at"] = utc_now()
            if record.get("status") in TERMINAL_STATUSES and not record.get("completed_at"):
                record["completed_at"] = record["updated_at"]
            state["delegations"][identifier] = record
            state["updated_at"] = record["updated_at"]
            captured = deepcopy(record)
            return state

        update_json_state(self.data_root, STATE_PATH, mutate, default_state())
        return captured

    def heartbeat(self, delegation_id: str, owner: str) -> dict[str, Any]:
        """Atomically renew a live operation lease or fail if ownership changed."""
        return self.patch(delegation_id, {}, owner=owner)

    def release(
        self,
        delegation_id: str,
        owner: str,
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.patch(
            delegation_id,
            {
                **(updates or {}),
                "operation_owner": "",
                "operation_expires_at": 0,
            },
            owner=owner,
        )

    def records(self, *, limit: int = 50) -> list[dict[str, Any]]:
        state = normalized_state(read_json_state(self.data_root, STATE_PATH, default_state()))
        records = sorted(
            state["delegations"].values(),
            key=lambda item: str(item.get("updated_at") or ""),
            reverse=True,
        )
        return [public_record(record) for record in records[: max(1, min(limit, 100))]]

    def view_state(self) -> dict[str, Any]:
        state = normalized_state(read_json_state(self.data_root, STATE_PATH, default_state()))
        return deepcopy(state["view_state"])

    def set_view_state(self, view_state: dict[str, Any]) -> dict[str, Any]:
        captured: dict[str, Any] = {}

        def mutate(raw: dict[str, Any]) -> dict[str, Any]:
            nonlocal captured
            state = normalized_state(raw)
            captured = clean_view_state(view_state)
            state["view_state"] = captured
            state["updated_at"] = utc_now()
            return state

        update_json_state(self.data_root, STATE_PATH, mutate, default_state())
        return deepcopy(captured)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _prune_records(
    records: dict[str, dict[str, Any]],
    *,
    reserve: int = 0,
    now_epoch: float | None = None,
    protected_ids: set[str] | None = None,
) -> None:
    """Expire terminal metadata and make bounded room before a new claim."""
    target = MAX_RECORDS - max(0, reserve)
    current_epoch = time() if now_epoch is None else now_epoch
    protected = protected_ids or set()
    terminal = sorted(
        (
            record
            for record in records.values()
            if record.get("status") in TERMINAL_STATUSES
            and record.get("delegation_id") not in protected
            and not _active_lease(record, now_epoch=current_epoch)
        ),
        key=lambda item: (_terminal_epoch(item), str(item.get("delegation_id") or "")),
    )
    for record in terminal:
        expired = _terminal_epoch(record) <= current_epoch - TERMINAL_RETENTION_SECONDS
        if not expired and len(records) <= target:
            break
        records.pop(str(record.get("delegation_id") or ""), None)


def _active_lease(record: dict[str, Any], *, now_epoch: float) -> bool:
    expiry = record.get("operation_expires_at")
    return bool(
        record.get("operation_owner")
        and isinstance(expiry, (int, float))
        and not isinstance(expiry, bool)
        and expiry > now_epoch
    )


def _terminal_epoch(record: dict[str, Any]) -> float:
    value = str(record.get("completed_at") or record.get("updated_at") or "")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (OverflowError, ValueError):
        return 0.0
