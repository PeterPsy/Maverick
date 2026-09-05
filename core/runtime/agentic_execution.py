"""Provider-neutral execution of one asynchronous agentic adapter turn."""

from __future__ import annotations

import json
from typing import Callable

from core.providers.agentic_adapter import (
    AgenticRuntimeEngineAdapter,
    RuntimePrepareContext,
    RuntimeProviderEvent,
    RuntimeTurnContext,
    RuntimeValidationContext,
)
from core.providers.models import RuntimeBackendLaunchSpec
from core.runtime.execution_events import RuntimeExecutionEvent, RuntimeExecutionEventSink
from core.runtime.provider_state import RuntimeProviderState
from core.runtime.authority import EffectiveRuntimeAuthority
from core.runtime.execution_binding import canonical_digest
from core.runtime.failure_messages import (
    normalized_failure_reason_code,
    runtime_failure_public_message,
)
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT,
    MAVERICK_FEATURE_AGENTIC_PROFILES,
    feature_enabled,
)
from core.skills.models import SkillDefinition


MAX_RUNTIME_PROVIDER_EVENT_BYTES = 1_048_576
_FORBIDDEN_PROVIDER_PRIVATE_FIELDS = {
    "providerprivateenvelope",
    "thoughtsignature",
    "thoughtsignatures",
    "opaquestate",
    "rawproviderstate",
    "rawpayload",
}


async def execute_agentic_runtime_turn(
    *,
    session: RuntimeSessionRecord,
    provider_state: RuntimeProviderState,
    adapter: AgenticRuntimeEngineAdapter,
    input_text: str,
    correlation_id: str,
    effective_authority: EffectiveRuntimeAuthority,
    input_sources: tuple[object, ...] = (),
    invoked_skills: list[SkillDefinition] | None = None,
    timeout_seconds: int | None = None,
    event_sink: RuntimeExecutionEventSink | None = None,
    local_launch_spec: RuntimeBackendLaunchSpec | None = None,
    on_provider_thread_id: Callable[[str], None] | None = None,
    on_provider_state_update: Callable[[dict[str, object]], RuntimeProviderState] | None = None,
    on_provider_startup_event: Callable[[str, dict[str, object]], None] | None = None,
    on_provider_turn_start_sent: Callable[[dict[str, object]], None] | None = None,
    on_provider_accepted: Callable[[dict[str, object]], None] | None = None,
    on_provider_upstream_observed: Callable[[str], None] | None = None,
):
    """Prepare and consume one typed event stream without assuming a process."""
    from core.runtime.execution import RuntimeExecutionResult

    binding = session.execution_binding
    if binding is None:
        raise ValueError("Agentic adapter execution requires a pinned session binding.")
    disabled_reason = None
    if not feature_enabled(MAVERICK_FEATURE_AGENTIC_PROFILES):
        disabled_reason = "agentic_profiles_disabled"
    elif not feature_enabled(MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT):
        disabled_reason = "agentic_adapter_contract_disabled"
    if disabled_reason is not None:
        if event_sink is not None:
            event_sink(RuntimeExecutionEvent("runtime.error", {"reason_code": disabled_reason}))
            event_sink(
                RuntimeExecutionEvent(
                    "provider.execution.completed",
                    {"output_text": "", "exit_code": 1, "reason_code": disabled_reason},
                )
            )
        return RuntimeExecutionResult(
            output_text="",
            exit_code=1,
            failure_reason_code=disabled_reason,
            public_error_message=runtime_failure_public_message(disabled_reason),
            diagnostic_reference=f"turn:{correlation_id}",
        )
    if (
        effective_authority.execution_binding_id != binding.execution_binding_id
        or effective_authority.turn_id != correlation_id
        or effective_authority.authority_digest != canonical_digest(effective_authority)
    ):
        raise ValueError("Effective runtime authority does not match the active turn.")
    health = await adapter.validate(RuntimeValidationContext(session=session, binding=binding))
    if health.status == "unavailable":
        return RuntimeExecutionResult(
            output_text="",
            exit_code=1,
            failure_reason_code="runtime_health_unavailable",
            public_error_message=runtime_failure_public_message(
                "runtime_health_unavailable"
            ),
            diagnostic_reference=f"turn:{correlation_id}",
        )
    prepared = await adapter.prepare(
        RuntimePrepareContext(
            session=session,
            binding=binding,
            provider_state=provider_state,
            local_launch_spec=local_launch_spec,
        )
    )
    if not prepared.ready:
        reason_code = normalized_failure_reason_code(
            prepared.metadata.get("reason_code"),
            fallback="provider_prepare_failed",
        )
        return RuntimeExecutionResult(
            output_text="",
            exit_code=1,
            failure_reason_code=reason_code,
            public_error_message=runtime_failure_public_message(reason_code),
            diagnostic_reference=f"turn:{correlation_id}",
        )
    provider_state = _apply_provider_state_update(
        prepared.provider_state_updates,
        on_provider_thread_id,
        on_provider_state_update,
    ) or provider_state
    context = RuntimeTurnContext(
        session=session,
        binding=binding,
        provider_state=provider_state,
        input_text=input_text,
        correlation_id=correlation_id,
        invoked_skills=tuple(invoked_skills or ()),
        timeout_seconds=timeout_seconds,
        prepared_handle=prepared.prepared_handle,
        effective_authority=effective_authority,
        input_sources=input_sources,
    )
    output_text = ""
    delta_output = ""
    exit_code: int | None = None
    failure_reason_code: str | None = None
    last_ordinal = 0
    async for event in adapter.execute(context):
        _validate_event(event, correlation_id=correlation_id, last_ordinal=last_ordinal)
        last_ordinal = event.ordinal
        if event.event_type == "provider.state.update":
            _apply_provider_state_update(
                event.payload,
                on_provider_thread_id,
                on_provider_state_update,
            )
            continue
        if event.event_type == "provider.accepted":
            upstream_id = str(
                event.payload.get("upstream_id")
                or event.payload.get("provider_upstream_id")
                or ""
            ).strip()
            if upstream_id and on_provider_upstream_observed is not None:
                on_provider_upstream_observed(upstream_id)
            if on_provider_accepted is not None:
                on_provider_accepted(event.payload)
            continue
        if event.event_type == "provider.request.sent":
            if on_provider_turn_start_sent is not None:
                on_provider_turn_start_sent(event.payload)
            continue
        if event.event_type == "provider.lifecycle":
            phase = str(event.payload.get("phase") or "").strip()
            if phase and on_provider_startup_event is not None:
                on_provider_startup_event(
                    phase,
                    {key: value for key, value in event.payload.items() if key != "phase"},
                )
            continue
        if event.event_type == "provider.execution.completed":
            output_text = str(event.payload.get("output_text") or output_text)
            exit_code = int(event.payload.get("exit_code") or 0)
            if exit_code != 0:
                failure_reason_code = normalized_failure_reason_code(
                    event.payload.get("reason_code") or failure_reason_code,
                    fallback="provider_execution_failed",
                )
            delivery_id = event.payload.get("delivery_id")
            if (
                event_sink is not None
                and isinstance(delivery_id, str)
                and 0 < len(delivery_id) <= 128
            ):
                event_sink(
                    RuntimeExecutionEvent(
                        event_type=event.event_type,
                        payload=dict(event.payload),
                    )
                )
            continue
        if event.event_type == "runtime.output.final":
            output_text = str(event.payload.get("text") or output_text)
        elif event.event_type == "runtime.output.delta":
            delta_output += str(event.payload.get("text") or "")
        elif event.event_type == "runtime.error":
            exit_code = 1
            failure_reason_code = normalized_failure_reason_code(
                event.payload.get("reason_code"),
                fallback="provider_execution_failed",
            )
        if event_sink is not None:
            public_payload = dict(event.payload)
            if event.event_type == "provider.usage":
                public_payload.update(
                    {
                        "provider_id": binding.model_provider_id,
                        "model_id": binding.model_id,
                        "source": "hosted_agentic",
                        "semantics": "incremental",
                        "token_accuracy": "exact",
                        "context_accuracy": "estimated",
                    }
                )
            event_sink(RuntimeExecutionEvent(event_type=event.event_type, payload=public_payload))
    final_output = output_text or delta_output
    final_exit_code = exit_code if exit_code is not None else 1
    if final_exit_code == 0 and not final_output.strip():
        final_output = ""
        final_exit_code = 1
        failure_reason_code = "agent_final_output_empty"
    if final_exit_code != 0 and failure_reason_code is None:
        failure_reason_code = "provider_execution_failed"
    return RuntimeExecutionResult(
        output_text=final_output,
        exit_code=final_exit_code,
        failure_reason_code=failure_reason_code,
        public_error_message=(
            runtime_failure_public_message(failure_reason_code)
            if failure_reason_code is not None
            else None
        ),
        diagnostic_reference=(
            f"turn:{correlation_id}" if failure_reason_code is not None else None
        ),
    )


def _validate_event(event: RuntimeProviderEvent, *, correlation_id: str, last_ordinal: int) -> None:
    if event.schema_version != "1":
        raise ValueError(f"Unsupported runtime provider event schema `{event.schema_version}`.")
    if event.correlation_id != correlation_id:
        raise ValueError("Runtime provider event correlation does not match the active turn.")
    if event.ordinal <= last_ordinal:
        raise ValueError("Runtime provider event ordinals must increase monotonically.")
    if _contains_private_field(event.payload):
        raise ValueError("Provider-private state cannot enter public runtime events.")
    try:
        encoded = json.dumps(
            event.payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("Runtime provider event payload must be bounded JSON.") from error
    if len(encoded) > MAX_RUNTIME_PROVIDER_EVENT_BYTES:
        raise ValueError("Runtime provider event payload exceeds the public event bound.")


def _apply_provider_state_update(
    payload: dict[str, object],
    thread_callback: Callable[[str], None] | None,
    state_callback: Callable[[dict[str, object]], RuntimeProviderState] | None,
) -> RuntimeProviderState | None:
    if _contains_private_field(payload):
        raise ValueError("Provider-private state requires the Core private state service.")
    if payload and state_callback is not None:
        return state_callback(payload)
    provider_thread_id = str(payload.get("provider_thread_id") or "").strip()
    if provider_thread_id and thread_callback is not None and state_callback is None:
        thread_callback(provider_thread_id)
    return None


def _contains_private_field(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = "".join(character for character in str(key).lower() if character.isalnum())
            if normalized in _FORBIDDEN_PROVIDER_PRIVATE_FIELDS or _contains_private_field(item):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_private_field(item) for item in value)
    return False
