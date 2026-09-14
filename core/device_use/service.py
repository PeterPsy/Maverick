"""Thread-safe activation, lease, invocation, and image admission service."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import math
import queue
import secrets
import threading
import time
from typing import Callable
from uuid import uuid4

from core.device_use.contract import (
    DEVICE_USE_EXECUTOR_CONTRACT,
    DEVICE_USE_MAX_ARGUMENT_BYTES,
    DEVICE_USE_MAX_JPEG_BYTES,
    DEVICE_USE_MAX_RESULT_BYTES,
    DEVICE_USE_MODEL_ID,
    DEVICE_USE_PROTOCOL_VERSION,
    DEVICE_USE_REASONING_EFFORT,
    DEVICE_USE_TOOL_CONTRACT_DIGEST,
    device_use_dynamic_tools,
    device_use_effect_class,
)
from core.device_use.errors import (
    DeviceUseAuthorizationError,
    DeviceUseExecutionUnknownError,
    DeviceUseUnavailableError,
)
from core.device_use.models import (
    DeviceUseInvocationJournalRecord,
    DeviceUseResult,
    DeviceUseSessionBinding,
)


ACTIVATION_TTL_SECONDS = 60
DEFAULT_INVOCATION_TIMEOUT_SECONDS = 180.0
MAX_APPROVED_APPS = 24
MAX_CALLS_PER_TURN = 512
MAX_JOURNAL_RECORDS = 2048
MAX_BINARY_HEADER_BYTES = 4096
MAX_TASK_TEXT_CHARACTERS = 4000
TERMINAL_ACTIVATION_RETENTION_SECONDS = 10 * 60
DEVICE_USE_TOOL_NAMES = frozenset(
    str(item["name"]) for item in device_use_dynamic_tools()
)


@dataclass
class _Activation:
    activation_id: str
    ticket_digest: str
    owner_user_id: str
    auth_session_id: str
    workspace_id: str
    session_generation: str
    status: str
    created_at: datetime
    expires_at: datetime
    protocol_version: str = ""
    executor_contract: str = ""
    tool_contract_digest: str = ""
    mode: str = ""
    initial_app: str = ""
    approved_apps: tuple[str, ...] = ()
    outbound: queue.Queue[dict[str, object] | None] | None = None
    bound_session_id: str | None = None
    stopped_reason: str | None = None


@dataclass
class _PendingInvocation:
    record: DeviceUseInvocationJournalRecord
    result: dict[str, object] | None = None
    image_jpeg: bytes | None = None
    expected_image_sha256: str | None = None
    native_duration_ms: float | None = None
    failure_reason_code: str | None = None
    completed: threading.Event = field(default_factory=threading.Event)


class DeviceUseService:
    """Own ephemeral Mac activations and serialize physical device calls."""

    def __init__(
        self,
        *,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._now = now or (lambda: datetime.now(tz=UTC))
        self._monotonic = monotonic or time.monotonic
        self._lock = threading.RLock()
        self._activations: dict[str, _Activation] = {}
        self._pending: dict[str, _PendingInvocation] = {}
        self._seen_calls: dict[tuple[str, str], set[str]] = {}
        self._journal: deque[DeviceUseInvocationJournalRecord] = deque(
            maxlen=MAX_JOURNAL_RECORDS
        )

    def create_activation(
        self,
        *,
        owner_user_id: str,
        auth_session_id: str,
        workspace_id: str,
        session_generation: str,
    ) -> tuple[dict[str, object], str]:
        """Create one short-lived, single-use native connection ticket."""
        owner = _bounded_identifier(owner_user_id, "owner_user_id")
        auth_session = _bounded_identifier(auth_session_id, "auth_session_id")
        workspace = _bounded_identifier(workspace_id, "workspace_id")
        generation = _bounded_identifier(session_generation, "session_generation")
        activation_id = str(uuid4())
        ticket = secrets.token_urlsafe(48)
        created_at = self._now()
        activation = _Activation(
            activation_id=activation_id,
            ticket_digest=_ticket_digest(ticket),
            owner_user_id=owner,
            auth_session_id=auth_session,
            workspace_id=workspace,
            session_generation=generation,
            status="awaiting_device",
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=ACTIVATION_TTL_SECONDS),
        )
        with self._lock:
            self._expire_locked()
            # One user/workspace/login generation controls at most one Mac.
            for existing in self._activations.values():
                if (
                    existing.owner_user_id == owner
                    and existing.workspace_id == workspace
                    and existing.auth_session_id == auth_session
                    and existing.status not in {"stopped", "expired", "offline"}
                ):
                    self._stop_locked(existing, "superseded")
            self._activations[activation_id] = activation
        return self.public_activation(activation_id, owner_user_id=owner, workspace_id=workspace), ticket

    def connect_executor(
        self,
        *,
        ticket: str,
        protocol_version: str,
        executor_contract: str,
        tool_contract_digest: str,
        mode: str,
        initial_app: str,
        approved_apps: list[str] | tuple[str, ...],
        outbound: queue.Queue[dict[str, object] | None],
    ) -> dict[str, object]:
        """Redeem a ticket and bind one compatible native executor."""
        with self._lock:
            self._expire_locked()
            activation = self._activation_for_ticket_locked(ticket)
            if activation.status != "awaiting_device" or activation.outbound is not None:
                raise DeviceUseAuthorizationError("device_use_ticket_already_used")
            if (
                protocol_version != DEVICE_USE_PROTOCOL_VERSION
                or executor_contract != DEVICE_USE_EXECUTOR_CONTRACT
                or tool_contract_digest != DEVICE_USE_TOOL_CONTRACT_DIGEST
            ):
                self._stop_locked(activation, "device_use_contract_mismatch")
                raise DeviceUseUnavailableError("device_use_contract_mismatch")
            access_mode = _device_use_mode(mode)
            apps = _approved_app_ids(approved_apps, unlimited=access_mode == "full")
            selected = _bundle_identifier(initial_app)
            if access_mode == "on" and selected not in apps:
                raise DeviceUseUnavailableError("device_use_initial_app_not_approved")
            activation.ticket_digest = ""
            activation.protocol_version = protocol_version
            activation.executor_contract = executor_contract
            activation.tool_contract_digest = tool_contract_digest
            activation.mode = access_mode
            activation.initial_app = selected
            activation.approved_apps = apps
            activation.outbound = outbound
            activation.status = "ready"
            return self._public_payload_locked(activation)

    def binding_snapshot(
        self,
        activation_id: str,
        *,
        owner_user_id: str,
        workspace_id: str,
        auth_session_id: str | None = None,
        bound_session_id: str | None = None,
    ) -> DeviceUseSessionBinding:
        """Return immutable activation authority for session preflight."""
        with self._lock:
            activation = self._owned_activation_locked(
                activation_id,
                owner_user_id=owner_user_id,
                workspace_id=workspace_id,
            )
            self._require_auth_session_locked(activation, auth_session_id)
            valid_unbound = activation.status == "ready" and bound_session_id is None
            valid_bound = (
                activation.status == "bound"
                and bound_session_id is not None
                and activation.bound_session_id == bound_session_id
            )
            if (not valid_unbound and not valid_bound) or activation.outbound is None:
                if activation.status == "bound":
                    raise DeviceUseAuthorizationError(
                        "device_use_activation_already_bound"
                    )
                raise DeviceUseUnavailableError("device_use_executor_not_ready")
            return DeviceUseSessionBinding(
                activation_id=activation.activation_id,
                workspace_id=activation.workspace_id,
                owner_user_id=activation.owner_user_id,
                protocol_version=activation.protocol_version,
                executor_contract=activation.executor_contract,
                tool_contract_digest=activation.tool_contract_digest,
                mode=activation.mode,  # type: ignore[arg-type]
                initial_app=activation.initial_app,
                approved_apps=activation.approved_apps,
                created_at=activation.created_at,
            )

    def bind_session(self, binding: DeviceUseSessionBinding, *, session_id: str) -> None:
        """Commit an activation lease to exactly one persisted runtime session."""
        with self._lock:
            activation = self._owned_activation_locked(
                binding.activation_id,
                owner_user_id=binding.owner_user_id,
                workspace_id=binding.workspace_id,
            )
            if self._binding_for_activation_locked(activation) != binding:
                raise DeviceUseAuthorizationError("device_use_binding_changed")
            if activation.status not in {"ready", "bound"} or activation.outbound is None:
                raise DeviceUseUnavailableError("device_use_executor_not_ready")
            if activation.bound_session_id not in {None, session_id}:
                raise DeviceUseAuthorizationError("device_use_activation_already_bound")
            activation.bound_session_id = _bounded_identifier(session_id, "session_id")
            activation.status = "bound"

    def public_activation(
        self,
        activation_id: str,
        *,
        owner_user_id: str,
        workspace_id: str,
        auth_session_id: str | None = None,
    ) -> dict[str, object]:
        """Return the redaction-safe browser status for an owned activation."""
        with self._lock:
            self._expire_locked()
            activation = self._owned_activation_locked(
                activation_id,
                owner_user_id=owner_user_id,
                workspace_id=workspace_id,
            )
            self._require_auth_session_locked(activation, auth_session_id)
            return self._public_payload_locked(activation)

    def stop_activation(
        self,
        activation_id: str,
        *,
        owner_user_id: str | None = None,
        workspace_id: str | None = None,
        auth_session_id: str | None = None,
        reason: str = "stopped",
    ) -> None:
        """Revoke a lease and wake every pending invocation without retry."""
        with self._lock:
            activation = self._activations.get(activation_id)
            if activation is None:
                return
            if owner_user_id is not None and activation.owner_user_id != owner_user_id:
                raise DeviceUseAuthorizationError("device_use_activation_forbidden")
            if workspace_id is not None and activation.workspace_id != workspace_id:
                raise DeviceUseAuthorizationError("device_use_activation_forbidden")
            self._require_auth_session_locked(activation, auth_session_id)
            self._stop_locked(activation, reason)

    def stop_auth_session(self, auth_session_id: str) -> None:
        """Revoke every device lease minted by one browser login."""
        with self._lock:
            for activation in self._activations.values():
                if activation.auth_session_id == auth_session_id:
                    self._stop_locked(activation, "authentication_ended")

    def disconnect_executor(self, activation_id: str) -> None:
        """Fail closed after a native socket disconnect."""
        with self._lock:
            activation = self._activations.get(activation_id)
            if activation is None or activation.status in {"stopped", "expired"}:
                return
            activation.outbound = None
            activation.status = "offline"
            activation.stopped_reason = "device_use_executor_disconnected"
            self._fail_pending_locked(
                activation.activation_id,
                "device_use_execution_unknown",
                execution_unknown=True,
            )

    def invoke(
        self,
        *,
        binding: DeviceUseSessionBinding,
        runtime_session_id: str,
        turn_id: str,
        provider_thread_id: str,
        provider_turn_id: str,
        call_id: str,
        tool_name: str,
        arguments: dict[str, object],
        task_text: str,
        timeout_seconds: float = DEFAULT_INVOCATION_TIMEOUT_SECONDS,
    ) -> DeviceUseResult:
        """Dispatch one physical operation and block only its dedicated worker."""
        tool = str(tool_name or "").strip()
        if tool not in DEVICE_USE_TOOL_NAMES:
            raise DeviceUseAuthorizationError("device_use_tool_not_allowed")
        call = _bounded_identifier(call_id, "call_id")
        session_id = _bounded_identifier(runtime_session_id, "runtime_session_id")
        turn = _bounded_identifier(turn_id, "turn_id")
        provider_thread = _bounded_identifier(provider_thread_id, "provider_thread_id")
        provider_turn = _bounded_identifier(provider_turn_id, "provider_turn_id")
        try:
            serialized_arguments = _canonical_json_bytes(arguments)
        except (TypeError, ValueError) as error:
            raise DeviceUseAuthorizationError(
                "device_use_arguments_invalid"
            ) from error
        if len(serialized_arguments) > DEVICE_USE_MAX_ARGUMENT_BYTES:
            raise DeviceUseAuthorizationError("device_use_arguments_too_large")
        arguments_digest = hashlib.sha256(serialized_arguments).hexdigest()
        action = str(arguments.get("action") or "").strip()[:64]
        if not action:
            raise DeviceUseAuthorizationError("device_use_action_required")
        invocation_id = str(uuid4())
        dispatched_at = self._now()
        record = DeviceUseInvocationJournalRecord(
            invocation_id=invocation_id,
            activation_id=binding.activation_id,
            runtime_session_id=session_id,
            turn_id=turn,
            call_id=call,
            tool_name=tool,
            action=action,
            arguments_digest=arguments_digest,
            effect_class=device_use_effect_class(tool, arguments),  # type: ignore[arg-type]
            status="dispatched",
            dispatched_at=dispatched_at,
            updated_at=dispatched_at,
        )
        pending = _PendingInvocation(record=record)
        with self._lock:
            activation = self._activation_for_binding_locked(binding, session_id=session_id)
            seen_key = (activation.activation_id, turn)
            seen = self._seen_calls.setdefault(seen_key, set())
            if call in seen or (
                binding.mode == "on" and len(seen) >= MAX_CALLS_PER_TURN
            ):
                raise DeviceUseAuthorizationError("device_use_duplicate_or_exhausted_call")
            seen.add(call)
            self._pending[invocation_id] = pending
            self._append_journal_locked(record)
            outbound = activation.outbound
            if outbound is None:
                self._pending.pop(invocation_id, None)
                raise DeviceUseUnavailableError("device_use_executor_not_ready")
            try:
                outbound.put_nowait(
                    {
                        "type": "device_use.invoke.v1",
                        "activation_id": activation.activation_id,
                        "runtime_session_id": session_id,
                        "turn_id": turn,
                        "provider_thread_id": provider_thread,
                        "provider_turn_id": provider_turn,
                        "invocation_id": invocation_id,
                        "call_id": call,
                        "tool": tool,
                        "arguments_json": serialized_arguments.decode("utf-8"),
                        "arguments_digest": arguments_digest,
                        "contract_digest": binding.tool_contract_digest,
                        "task_text": str(task_text or "")[:MAX_TASK_TEXT_CHARACTERS],
                        "deadline_ms": max(1, int(timeout_seconds * 1000)),
                        "attempt": 1,
                    }
                )
            except queue.Full as error:
                self._pending.pop(invocation_id, None)
                self._update_journal_locked(
                    pending,
                    status="execution_unknown",
                    failure_reason_code="device_use_transport_backpressure",
                )
                self._stop_locked(activation, "device_use_transport_backpressure")
                raise DeviceUseExecutionUnknownError(
                    "device_use_transport_backpressure"
                ) from error
        started = self._monotonic()
        if not pending.completed.wait(max(0.01, timeout_seconds)):
            with self._lock:
                if self._pending.pop(invocation_id, None) is not None:
                    self._update_journal_locked(
                        pending,
                        status="execution_unknown",
                        failure_reason_code="device_use_execution_timeout",
                    )
                    activation = self._activations.get(binding.activation_id)
                    if activation is not None:
                        self._stop_locked(
                            activation,
                            "device_use_execution_timeout",
                        )
            raise DeviceUseExecutionUnknownError("device_use_execution_timeout")
        elapsed_ms = max(0.0, (self._monotonic() - started) * 1000)
        with self._lock:
            self._pending.pop(invocation_id, None)
            if pending.failure_reason_code:
                raise DeviceUseExecutionUnknownError(pending.failure_reason_code)
            if pending.result is None:
                raise DeviceUseUnavailableError("device_use_result_missing")
            self._update_journal_locked(
                pending,
                status="completed",
                image_bytes=len(pending.image_jpeg or b""),
            )
            return DeviceUseResult(
                invocation_id=invocation_id,
                call_id=call,
                result=pending.result,
                image_jpeg=pending.image_jpeg,
                image_sha256=pending.expected_image_sha256,
                native_duration_ms=(
                    pending.native_duration_ms
                    if pending.native_duration_ms is not None
                    else elapsed_ms
                ),
            )

    def accept_invocation(self, activation_id: str, frame: dict[str, object]) -> None:
        """Record native acceptance without granting a duplicate execution."""
        with self._lock:
            pending = self._pending_for_frame_locked(activation_id, frame)
            if pending.record.status != "dispatched":
                raise DeviceUseAuthorizationError("device_use_duplicate_acceptance")
            self._update_journal_locked(pending, status="accepted")

    def end_turn(
        self,
        binding: DeviceUseSessionBinding,
        *,
        runtime_session_id: str,
        turn_id: str,
    ) -> None:
        """Release native per-turn state after the provider reaches a terminal turn."""
        session_id = _bounded_identifier(runtime_session_id, "runtime_session_id")
        turn = _bounded_identifier(turn_id, "turn_id")
        with self._lock:
            activation = self._activation_for_binding_locked(binding, session_id=session_id)
            try:
                activation.outbound.put_nowait({
                    "type": "device_use.turn_end.v1",
                    "activation_id": activation.activation_id,
                    "runtime_session_id": session_id,
                    "turn_id": turn,
                })
            except queue.Full:
                self._stop_locked(activation, "device_use_transport_backpressure")
                raise DeviceUseExecutionUnknownError(
                    "device_use_transport_backpressure"
                )

    def deliver_result(self, activation_id: str, frame: dict[str, object]) -> None:
        """Admit a bounded text tool result and wait for a declared image if any."""
        with self._lock:
            pending = self._pending_for_frame_locked(activation_id, frame)
            if pending.record.status != "accepted" or pending.result is not None:
                raise DeviceUseAuthorizationError("device_use_duplicate_result")
            result = frame.get("result")
            if not isinstance(result, dict):
                raise DeviceUseAuthorizationError("device_use_result_invalid")
            _validate_text_result(result)
            if frame.get("arguments_digest") != pending.record.arguments_digest:
                raise DeviceUseAuthorizationError("device_use_arguments_digest_mismatch")
            duration = frame.get("native_duration_ms")
            if duration is not None and (
                not isinstance(duration, (int, float))
                or isinstance(duration, bool)
                or not math.isfinite(float(duration))
                or duration < 0
                or duration > 3_600_000
            ):
                raise DeviceUseAuthorizationError("device_use_native_duration_invalid")
            has_image = frame.get("has_image") is True
            image_sha256 = str(frame.get("image_sha256") or "").strip()
            if has_image:
                if (
                    (pending.record.tool_name, pending.record.action)
                    not in {
                        ("mac_computer", "observe"),
                        ("mac_peekaboo", "observe"),
                        ("mac_peekaboo", "observe_app"),
                    }
                    or result.get("success") is not True
                    or not _is_sha256(image_sha256)
                ):
                    raise DeviceUseAuthorizationError("device_use_image_digest_invalid")
                pending.expected_image_sha256 = image_sha256
            elif image_sha256:
                raise DeviceUseAuthorizationError("device_use_unexpected_image_digest")
            pending.result = dict(result)
            pending.native_duration_ms = float(duration) if duration is not None else None
            self._update_journal_locked(pending, status="result_received")
            if not has_image:
                pending.completed.set()

    def deliver_image(self, activation_id: str, payload: bytes) -> None:
        """Admit the exact binary JPEG declared by a pending result."""
        header, jpeg = decode_image_frame(payload)
        with self._lock:
            pending = self._pending_for_frame_locked(activation_id, header)
            if pending.record.status != "result_received" or pending.image_jpeg is not None:
                raise DeviceUseAuthorizationError("device_use_duplicate_image")
            if pending.result is None or pending.expected_image_sha256 is None:
                raise DeviceUseAuthorizationError("device_use_image_not_declared")
            actual_digest = hashlib.sha256(jpeg).hexdigest()
            if not hmac.compare_digest(actual_digest, pending.expected_image_sha256):
                raise DeviceUseAuthorizationError("device_use_image_digest_mismatch")
            pending.image_jpeg = jpeg
            self._update_journal_locked(
                pending,
                status="image_received",
                image_bytes=len(jpeg),
            )
            pending.completed.set()

    def journal(self, *, runtime_session_id: str | None = None) -> list[DeviceUseInvocationJournalRecord]:
        """Return redaction-safe evidence, never arguments, text, or image bytes."""
        with self._lock:
            records = list(self._journal)
        if runtime_session_id is None:
            return records
        return [item for item in records if item.runtime_session_id == runtime_session_id]

    def activation_metrics(
        self,
        activation_id: str,
        *,
        owner_user_id: str,
        workspace_id: str,
        auth_session_id: str | None = None,
    ) -> dict[str, object]:
        """Return bounded, content-free bridge timings for A/B benchmarking."""
        with self._lock:
            self._expire_locked()
            activation = self._owned_activation_locked(
                activation_id,
                owner_user_id=owner_user_id,
                workspace_id=workspace_id,
            )
            self._require_auth_session_locked(activation, auth_session_id)
            records = [
                item
                for item in self._journal
                if item.activation_id == activation.activation_id
            ]
            return {
                "activation_id": activation.activation_id,
                "status": activation.status,
                "invocation_count": len(records),
                "completed_count": sum(item.status == "completed" for item in records),
                "execution_unknown_count": sum(
                    item.status == "execution_unknown" for item in records
                ),
                "summary": _metric_summary(records),
                "invocations": [_metric_payload(item) for item in records],
            }

    def activation_id_for_ticket(self, ticket: str) -> str:
        """Authorize a WebSocket before it is accepted without consuming its ticket."""
        with self._lock:
            self._expire_locked()
            return self._activation_for_ticket_locked(ticket).activation_id

    def _activation_for_ticket_locked(self, ticket: str) -> _Activation:
        digest = _ticket_digest(ticket)
        if not digest:
            raise DeviceUseAuthorizationError("device_use_ticket_invalid")
        for activation in self._activations.values():
            if activation.ticket_digest and hmac.compare_digest(
                activation.ticket_digest, digest
            ):
                return activation
        raise DeviceUseAuthorizationError("device_use_ticket_invalid")

    def _owned_activation_locked(
        self,
        activation_id: str,
        *,
        owner_user_id: str,
        workspace_id: str,
    ) -> _Activation:
        activation = self._activations.get(str(activation_id or "").strip())
        if activation is None:
            raise DeviceUseUnavailableError("device_use_activation_not_found")
        if (
            activation.owner_user_id != owner_user_id
            or activation.workspace_id != workspace_id
        ):
            raise DeviceUseAuthorizationError("device_use_activation_forbidden")
        return activation

    def _binding_for_activation_locked(
        self, activation: _Activation
    ) -> DeviceUseSessionBinding:
        return DeviceUseSessionBinding(
            activation_id=activation.activation_id,
            workspace_id=activation.workspace_id,
            owner_user_id=activation.owner_user_id,
            protocol_version=activation.protocol_version,
            executor_contract=activation.executor_contract,
            tool_contract_digest=activation.tool_contract_digest,
            mode=activation.mode,  # type: ignore[arg-type]
            initial_app=activation.initial_app,
            approved_apps=activation.approved_apps,
            created_at=activation.created_at,
        )

    @staticmethod
    def _require_auth_session_locked(
        activation: _Activation,
        auth_session_id: str | None,
    ) -> None:
        if (
            auth_session_id is not None
            and activation.auth_session_id != auth_session_id
        ):
            raise DeviceUseAuthorizationError("device_use_activation_forbidden")

    def _activation_for_binding_locked(
        self,
        binding: DeviceUseSessionBinding,
        *,
        session_id: str,
    ) -> _Activation:
        activation = self._owned_activation_locked(
            binding.activation_id,
            owner_user_id=binding.owner_user_id,
            workspace_id=binding.workspace_id,
        )
        if (
            activation.status != "bound"
            or activation.bound_session_id != session_id
            or activation.outbound is None
            or self._binding_for_activation_locked(activation) != binding
        ):
            raise DeviceUseUnavailableError("device_use_session_not_connected")
        return activation

    def _pending_for_frame_locked(
        self, activation_id: str, frame: dict[str, object]
    ) -> _PendingInvocation:
        invocation_id = str(frame.get("invocation_id") or "").strip()
        pending = self._pending.get(invocation_id)
        if (
            pending is None
            or pending.record.activation_id != activation_id
            or str(frame.get("call_id") or "").strip() != pending.record.call_id
        ):
            raise DeviceUseAuthorizationError("device_use_invocation_mismatch")
        return pending

    def _stop_locked(self, activation: _Activation, reason: str) -> None:
        outbound = activation.outbound
        activation.outbound = None
        activation.status = "stopped"
        activation.stopped_reason = str(reason or "stopped")[:120]
        if outbound is not None:
            # Revocation outranks queued work. Dropped invocations are already
            # terminalized as execution-unknown below and are never retried.
            while True:
                try:
                    outbound.get_nowait()
                except queue.Empty:
                    break
            outbound.put_nowait(
                {"type": "device_use.stop.v1", "reason": activation.stopped_reason}
            )
            try:
                outbound.put_nowait(None)
            except queue.Full:
                # The stop frame itself makes the peer close the socket.
                pass
        self._fail_pending_locked(
            activation.activation_id,
            "device_use_execution_unknown",
            execution_unknown=True,
        )
        for key in [item for item in self._seen_calls if item[0] == activation.activation_id]:
            self._seen_calls.pop(key, None)

    def _fail_pending_locked(
        self,
        activation_id: str,
        reason: str,
        *,
        execution_unknown: bool,
    ) -> None:
        for pending in self._pending.values():
            if pending.record.activation_id != activation_id:
                continue
            pending.failure_reason_code = reason
            self._update_journal_locked(
                pending,
                status="execution_unknown" if execution_unknown else "failed",
                failure_reason_code=reason,
            )
            pending.completed.set()

    def _append_journal_locked(self, record: DeviceUseInvocationJournalRecord) -> None:
        self._journal.append(record)

    def _update_journal_locked(
        self,
        pending: _PendingInvocation,
        *,
        status: str,
        image_bytes: int | None = None,
        failure_reason_code: str | None = None,
    ) -> None:
        timestamp = self._now()
        updated = replace(
            pending.record,
            status=status,  # type: ignore[arg-type]
            updated_at=timestamp,
            accepted_at=(
                pending.record.accepted_at
                or (timestamp if status == "accepted" else None)
            ),
            result_received_at=(
                pending.record.result_received_at
                or (timestamp if status == "result_received" else None)
            ),
            completed_at=(
                pending.record.completed_at
                or (timestamp if status in {"completed", "failed", "execution_unknown"} else None)
            ),
            native_duration_ms=pending.native_duration_ms,
            image_bytes=(
                pending.record.image_bytes if image_bytes is None else image_bytes
            ),
            failure_reason_code=failure_reason_code,
        )
        pending.record = updated
        for index in range(len(self._journal) - 1, -1, -1):
            if self._journal[index].invocation_id == updated.invocation_id:
                self._journal[index] = updated
                return
        self._journal.append(updated)

    def _expire_locked(self) -> None:
        now = self._now()
        for activation in self._activations.values():
            if activation.status == "awaiting_device" and activation.expires_at <= now:
                activation.ticket_digest = ""
                activation.status = "expired"
                activation.stopped_reason = "device_use_activation_expired"
        cutoff = now - timedelta(seconds=TERMINAL_ACTIVATION_RETENTION_SECONDS)
        removable = [
            activation_id
            for activation_id, activation in self._activations.items()
            if activation.status in {"stopped", "expired", "offline"}
            and activation.created_at <= cutoff
            and not any(
                pending.record.activation_id == activation_id
                for pending in self._pending.values()
            )
        ]
        for activation_id in removable:
            self._activations.pop(activation_id, None)

    @staticmethod
    def _public_payload_locked(activation: _Activation) -> dict[str, object]:
        return {
            "activation_id": activation.activation_id,
            "status": activation.status,
            "protocol_version": DEVICE_USE_PROTOCOL_VERSION,
            "executor_contract": DEVICE_USE_EXECUTOR_CONTRACT,
            "tool_contract_digest": DEVICE_USE_TOOL_CONTRACT_DIGEST,
            "model_id": DEVICE_USE_MODEL_ID,
            "reasoning_effort": DEVICE_USE_REASONING_EFFORT,
            "mode": activation.mode or None,
            "ready": activation.status in {"ready", "bound"},
            "approved_app_count": len(activation.approved_apps),
            "bound": bool(activation.bound_session_id),
            "reason": activation.stopped_reason,
            "expires_at": activation.expires_at,
        }


def encode_image_frame(
    *, invocation_id: str, call_id: str, jpeg: bytes
) -> bytes:
    """Encode one self-identifying binary image frame for protocol tests/clients."""
    _validate_jpeg(jpeg)
    header = _canonical_json_bytes(
        {
            "type": "device_use.image.v1",
            "invocation_id": _bounded_identifier(invocation_id, "invocation_id"),
            "call_id": _bounded_identifier(call_id, "call_id"),
        }
    )
    if len(header) > MAX_BINARY_HEADER_BYTES:
        raise DeviceUseAuthorizationError("device_use_image_header_too_large")
    return len(header).to_bytes(4, "big") + header + jpeg


def decode_image_frame(payload: bytes) -> tuple[dict[str, object], bytes]:
    """Decode and validate one binary image envelope."""
    if len(payload) < 5:
        raise DeviceUseAuthorizationError("device_use_image_frame_invalid")
    header_size = int.from_bytes(payload[:4], "big")
    if header_size < 2 or header_size > MAX_BINARY_HEADER_BYTES:
        raise DeviceUseAuthorizationError("device_use_image_header_invalid")
    split = 4 + header_size
    if split >= len(payload):
        raise DeviceUseAuthorizationError("device_use_image_frame_invalid")
    try:
        header = json.loads(payload[4:split])
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DeviceUseAuthorizationError("device_use_image_header_invalid") from error
    if not isinstance(header, dict) or header.get("type") != "device_use.image.v1":
        raise DeviceUseAuthorizationError("device_use_image_header_invalid")
    jpeg = payload[split:]
    _validate_jpeg(jpeg)
    return header, jpeg


def _validate_text_result(result: dict[str, object]) -> None:
    try:
        encoded = _canonical_json_bytes(result)
    except (TypeError, ValueError) as error:
        raise DeviceUseAuthorizationError("device_use_result_invalid") from error
    items = result.get("contentItems")
    if (
        len(encoded) > DEVICE_USE_MAX_RESULT_BYTES
        or set(result) != {"success", "contentItems"}
        or not isinstance(result.get("success"), bool)
        or not isinstance(items, list)
        or len(items) != 1
        or not isinstance(items[0], dict)
        or set(items[0]) != {"type", "text"}
        or items[0].get("type") != "inputText"
        or not isinstance(items[0].get("text"), str)
        or "data:image" in items[0]["text"]
    ):
        raise DeviceUseAuthorizationError("device_use_result_invalid")


def _validate_jpeg(jpeg: bytes) -> None:
    if (
        not isinstance(jpeg, bytes)
        or not jpeg
        or len(jpeg) >= DEVICE_USE_MAX_JPEG_BYTES
        or not jpeg.startswith(b"\xff\xd8")
        or not jpeg.endswith(b"\xff\xd9")
    ):
        raise DeviceUseAuthorizationError("device_use_image_invalid")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _ticket_digest(ticket: str) -> str:
    normalized = str(ticket or "").strip()
    if len(normalized) < 32 or len(normalized) > 256:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _bounded_identifier(value: object, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 256 or any(
        character in normalized for character in "\r\n\0"
    ):
        raise DeviceUseAuthorizationError(f"device_use_{name}_invalid")
    return normalized


def _bundle_identifier(value: object) -> str:
    normalized = _bounded_identifier(value, "bundle_id")
    if not all(
        character.isalnum() or character in {".", "-", "_"}
        for character in normalized
    ):
        raise DeviceUseAuthorizationError("device_use_bundle_id_invalid")
    return normalized


def _approved_app_ids(
    values: list[str] | tuple[str, ...], *, unlimited: bool = False
) -> tuple[str, ...]:
    if (
        not isinstance(values, (list, tuple))
        or not values
        or (not unlimited and len(values) > MAX_APPROVED_APPS)
    ):
        raise DeviceUseAuthorizationError("device_use_approved_apps_invalid")
    apps = tuple(sorted({_bundle_identifier(item) for item in values}))
    if not apps:
        raise DeviceUseAuthorizationError("device_use_approved_apps_invalid")
    return apps


def _device_use_mode(value: object) -> str:
    mode = str(value or "").strip()
    if mode not in {"on", "full"}:
        raise DeviceUseAuthorizationError("device_use_mode_invalid")
    return mode


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _elapsed_ms(start: datetime, end: datetime | None) -> float | None:
    if end is None:
        return None
    return round(max(0.0, (end - start).total_seconds() * 1000), 3)


def _metric_payload(record: DeviceUseInvocationJournalRecord) -> dict[str, object]:
    end_to_end_ms = _elapsed_ms(record.dispatched_at, record.completed_at)
    relay_overhead_ms = None
    if end_to_end_ms is not None and record.native_duration_ms is not None:
        relay_overhead_ms = round(
            max(0.0, end_to_end_ms - record.native_duration_ms),
            3,
        )
    return {
        "invocation_id": record.invocation_id,
        "runtime_session_id": record.runtime_session_id,
        "turn_id": record.turn_id,
        "call_id": record.call_id,
        "tool_name": record.tool_name,
        "action": record.action,
        "arguments_digest": record.arguments_digest,
        "effect_class": record.effect_class,
        "status": record.status,
        "dispatch_to_accept_ms": _elapsed_ms(
            record.dispatched_at,
            record.accepted_at,
        ),
        "dispatch_to_result_ms": _elapsed_ms(
            record.dispatched_at,
            record.result_received_at,
        ),
        "bridge_end_to_end_ms": end_to_end_ms,
        "native_duration_ms": record.native_duration_ms,
        "relay_overhead_ms": relay_overhead_ms,
        "image_bytes": record.image_bytes,
        "failure_reason_code": record.failure_reason_code,
    }


def _metric_summary(
    records: list[DeviceUseInvocationJournalRecord],
) -> dict[str, object]:
    payloads = [_metric_payload(record) for record in records]

    def timings(name: str) -> dict[str, object]:
        values = sorted(
            float(payload[name])
            for payload in payloads
            if isinstance(payload.get(name), (int, float))
            and not isinstance(payload.get(name), bool)
        )
        if not values:
            return {"count": 0, "total_ms": 0.0, "p50_ms": None, "p95_ms": None}

        def percentile(fraction: float) -> float:
            index = max(0, math.ceil(len(values) * fraction) - 1)
            return round(values[index], 3)

        return {
            "count": len(values),
            "total_ms": round(sum(values), 3),
            "p50_ms": percentile(0.50),
            "p95_ms": percentile(0.95),
        }

    return {
        "tool_counts": dict(sorted(Counter(record.tool_name for record in records).items())),
        "action_counts": dict(sorted(Counter(
            f"{record.tool_name}.{record.action}" for record in records
        ).items())),
        "image_count": sum(record.image_bytes > 0 for record in records),
        "image_bytes": sum(record.image_bytes for record in records),
        "dispatch_to_accept_ms": timings("dispatch_to_accept_ms"),
        "bridge_end_to_end_ms": timings("bridge_end_to_end_ms"),
        "native_duration_ms": timings("native_duration_ms"),
        "relay_overhead_ms": timings("relay_overhead_ms"),
    }
