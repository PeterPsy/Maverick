"""Idempotent external delegation into native OpenDesign conversations."""

from __future__ import annotations

from contextlib import suppress
from time import time
from typing import Any, Callable

from delegation_errors import DelegationError
from delegation_inputs import DelegationInputError, parse_delegation_request
from delegation_lease import DelegationLeaseHeartbeat
from delegation_native_flow import NativeDelegationFlow
from delegation_projection import (
    TERMINAL_STATUSES,
    assistant_run_projection,
    normalized_run_status,
    sanitized_result_references,
)
from delegation_store import DelegationStore, DelegationStoreError, public_record
from opendesign_client import (
    OpenDesignClient,
    OpenDesignNotFound,
    OpenDesignProtocolError,
    OpenDesignRequestFailed,
    OpenDesignUnavailable,
)


class DelegationService:
    """Track only safe correlation metadata around native OpenDesign runs."""

    def __init__(
        self,
        payload: Any,
        *,
        client: Any | None = None,
        store: DelegationStore | None = None,
        clock_ms: Callable[[], int] | None = None,
        heartbeat_interval_seconds: float | None = None,
    ) -> None:
        self.payload = payload
        self.app_id = str(getattr(payload, "app_id", "") or "design-studio")
        self.workspace_id = str(getattr(payload, "workspace_id", "") or "")
        self.store = store or DelegationStore(str(getattr(payload, "data_root", "") or ""))
        self._client = client
        self._clock_ms = clock_ms or (lambda: int(time() * 1000))
        self._heartbeat_interval_seconds = heartbeat_interval_seconds

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = OpenDesignClient(self.payload)
        return self._client

    def delegate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            request = parse_delegation_request(self.workspace_id, arguments)
        except DelegationInputError as error:
            raise DelegationError("delegation_input_invalid", str(error), status_code=400) from error
        claim = self.store.claim(
            request.delegation_id,
            {
                "status": "preparing",
                "request_fingerprint": request.request_fingerprint,
                "run_submission_started": False,
                "od_message_id": request.message_id,
                "od_assistant_message_id": request.assistant_message_id,
            },
        )
        try:
            self._assert_request_identity(request.request_fingerprint, claim.record)
        except DelegationError:
            if claim.acquired:
                self._release_without_failure(request.delegation_id, claim.owner)
            raise
        if not claim.acquired:
            return self._response(claim.record, in_progress=True, replay=True)
        record = claim.record
        try:
            if record.get("status") in TERMINAL_STATUSES:
                record = self.store.release(request.delegation_id, claim.owner)
                return self._response(record, replay=True)
            if record.get("od_run_id"):
                self.store.release(request.delegation_id, claim.owner)
                return {**self.status(request.delegation_id), "idempotent_replay": True}
            with DelegationLeaseHeartbeat(
                self.store,
                request.delegation_id,
                claim.owner,
                interval_seconds=self._heartbeat_interval_seconds,
            ) as lease:
                record, replay = NativeDelegationFlow(self.client, self._clock_ms).submit(
                    request,
                    record,
                    store=self.store,
                    owner=claim.owner,
                    app_id=self.app_id,
                    lease_check=lease.check,
                )
            record = self.store.release(request.delegation_id, claim.owner)
            return self._response(record, replay=replay)
        except DelegationError:
            self._release_failed(request.delegation_id, claim.owner)
            raise
        except Exception as error:
            self._release_failed(request.delegation_id, claim.owner)
            raise public_delegation_error(error) from error

    def status(self, delegation_id: str) -> dict[str, Any]:
        record = self._required_record(delegation_id)
        run_id = str(record.get("od_run_id") or "")
        if not run_id:
            return self._response(record)
        if record.get("status") in TERMINAL_STATUSES:
            if not record.get("result_references"):
                with suppress(
                    OpenDesignNotFound,
                    OpenDesignRequestFailed,
                    OpenDesignUnavailable,
                    OpenDesignProtocolError,
                    DelegationStoreError,
                    ValueError,
                ):
                    record = self._capture_result(record)
            return self._response(record)
        project_id = str(record.get("od_project_id") or "")
        conversation_id = str(record.get("od_conversation_id") or "")
        assistant_id = str(record.get("od_assistant_message_id") or "")
        updates: dict[str, Any] = {}
        try:
            run = self.client.get_run(run_id)
            _validate_run_identity(run, record)
            updates["status"] = normalized_run_status(run.get("status"))
        except OpenDesignNotFound:
            updates["status"] = "unknown"
        try:
            messages = self.client.list_messages(project_id, conversation_id)
            projection = assistant_run_projection(messages, assistant_id)
            if projection["run_id"] and projection["run_id"] != run_id:
                raise OpenDesignProtocolError("OpenDesign run correlation changed unexpectedly.")
            if projection["event_cursor"]:
                updates["event_cursor"] = projection["event_cursor"]
            if updates.get("status") == "unknown" and projection["status"] != "unknown":
                updates["status"] = projection["status"]
        except OpenDesignNotFound:
            pass
        if updates:
            record = self.store.patch(delegation_id, updates)
        if record.get("status") in TERMINAL_STATUSES and not record.get("result_references"):
            with suppress(
                OpenDesignNotFound,
                OpenDesignRequestFailed,
                OpenDesignUnavailable,
                OpenDesignProtocolError,
                DelegationStoreError,
                ValueError,
            ):
                record = self._capture_result(record)
        return self._response(record)

    def cancel(self, delegation_id: str) -> dict[str, Any]:
        record = self._required_record(delegation_id)
        claim = self.store.claim(delegation_id, record)
        if not claim.acquired:
            return self._response(claim.record, in_progress=True)
        record = claim.record
        if record.get("status") in TERMINAL_STATUSES:
            return self._response(self.store.release(delegation_id, claim.owner))
        run_id = str(record.get("od_run_id") or "")
        if not run_id:
            if record.get("run_submission_started") is True:
                self.store.release(delegation_id, claim.owner)
                raise DelegationError(
                    "delegation_submission_uncertain",
                    "The original OpenDesign run must be correlated before it can be canceled.",
                    status_code=409,
                )
            return self._response(
                self.store.release(delegation_id, claim.owner, {"status": "canceled"})
            )
        try:
            response = self.client.cancel_run(run_id)
            run = response.get("run") if isinstance(response.get("run"), dict) else {}
            status = normalized_run_status(run.get("status"))
            if status == "unknown":
                status = "canceled"
            return self._response(
                self.store.release(delegation_id, claim.owner, {"status": status})
            )
        except Exception as error:
            self._release_without_failure(delegation_id, claim.owner)
            raise public_delegation_error(error) from error

    def result(self, delegation_id: str) -> dict[str, Any]:
        response = self.status(delegation_id)
        record = self._required_record(delegation_id)
        if record.get("status") not in TERMINAL_STATUSES:
            return {**response, "result_available": False}
        if not record.get("result_references"):
            try:
                record = self._capture_result(record)
            except Exception as error:
                raise public_delegation_error(error) from error
        return {**self._response(record), "result_available": True}

    def _capture_result(self, record: dict[str, Any]) -> dict[str, Any]:
        project_id = str(record.get("od_project_id") or "")
        run_id = str(record.get("od_run_id") or "")
        references = sanitized_result_references(
            self.client.get_result_package(run_id),
            project_id=project_id,
            run_id=run_id,
        )
        return self.store.patch(
            str(record.get("delegation_id") or ""),
            {"result_references": references},
        )

    def _required_record(self, delegation_id: str) -> dict[str, Any]:
        try:
            record = self.store.get(delegation_id)
        except ValueError as error:
            raise DelegationError("delegation_id_invalid", str(error), status_code=400) from error
        if record is None:
            raise DelegationError(
                "delegation_not_found",
                "The delegation was not found.",
                status_code=404,
            )
        return record

    def _release_failed(self, delegation_id: str, owner: str) -> None:
        with suppress(Exception):
            record = self.store.get(delegation_id) or {}
            status = (
                "queued"
                if record.get("od_run_id")
                else "submission_uncertain"
                if record.get("run_submission_started") is True
                else "submission_failed"
            )
            self.store.release(delegation_id, owner, {"status": status})

    @staticmethod
    def _assert_request_identity(fingerprint: str, record: dict[str, Any]) -> None:
        if record.get("request_fingerprint") == fingerprint:
            return
        raise DelegationError(
            "idempotency_key_reused",
            "The idempotency key is already bound to a different delegation request.",
            status_code=409,
        )

    def _release_without_failure(self, delegation_id: str, owner: str) -> None:
        with suppress(Exception):
            self.store.release(delegation_id, owner)

    @staticmethod
    def _response(
        record: dict[str, Any],
        *,
        in_progress: bool = False,
        replay: bool = False,
    ) -> dict[str, Any]:
        return {
            "delegation": public_record(record),
            "in_progress": in_progress,
            "idempotent_replay": replay,
            "retry_safe": True,
        }


def _validate_run_identity(run: dict[str, Any], record: dict[str, Any]) -> None:
    expected = {
        "id": str(record.get("od_run_id") or ""),
        "projectId": str(record.get("od_project_id") or ""),
        "conversationId": str(record.get("od_conversation_id") or ""),
        "assistantMessageId": str(record.get("od_assistant_message_id") or ""),
    }
    for key, expected_value in expected.items():
        returned = str(run.get(key) or "")
        if returned and returned != expected_value:
            raise OpenDesignProtocolError("OpenDesign run identity mismatch.")


def public_delegation_error(error: Exception) -> DelegationError:
    """Map internal/client failures without exposing paths, bodies, or credentials."""
    if isinstance(error, DelegationError):
        return error
    if isinstance(error, OpenDesignUnavailable):
        return DelegationError(
            "delegation_unavailable",
            "OpenDesign delegation is unavailable; native OpenDesign remains usable directly.",
            status_code=503,
        )
    if isinstance(error, OpenDesignNotFound):
        return DelegationError(
            "opendesign_resource_not_found",
            "OpenDesign resource not found.",
            status_code=404,
        )
    if isinstance(error, OpenDesignRequestFailed):
        return DelegationError(
            "opendesign_request_failed",
            "OpenDesign rejected the delegation request.",
            status_code=502,
        )
    if isinstance(error, (OpenDesignProtocolError, ValueError)):
        return DelegationError(
            "opendesign_response_invalid",
            "OpenDesign returned an invalid public response.",
            status_code=502,
        )
    if isinstance(error, DelegationStoreError):
        return DelegationError(
            "delegation_busy",
            "The delegation is busy; retry with the same key.",
            status_code=409,
        )
    return DelegationError(
        "delegation_failed",
        "The OpenDesign delegation could not be completed.",
        status_code=500,
    )
