"""Redaction-safe inventory of persisted remote agentic session ambiguity."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from core.runtime.execution_binding import canonical_digest
from core.runtime.errors import RuntimeProviderStateError
from core.runtime.agentic_inventory_steps import correlate_provider_steps
from core.runtime.remote_agentic_admission import is_remote_agentic_identity
from core.runtime.public_status import public_runtime_recovery_reason_code
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.store import RuntimeStore


_TERMINAL_TURN_STATUSES = frozenset({"completed", "failed", "cancelled", "timed-out"})
_PENDING_TOOL_STATES = frozenset(
    {
        "proposed",
        "validating",
        "validated",
        "awaiting_confirmation",
        "authorized",
        "executing",
    }
)
_QUARANTINE_REASONS = frozenset(
    {
        "provider_step_outcome_ambiguous",
        "terminal_turn_running_session",
        "provider_state_missing",
        "provider_state_pending",
        "provider_state_uncommitted",
        "provider_state_generation_mismatch",
        "staged_committed_mismatch",
        "tool_execution_unknown",
        "tool_invocation_pending",
        "legacy_synthetic_classification_present",
    }
)


@dataclass(frozen=True)
class RemoteAgenticSessionInventoryItem:
    """Safe inventory row for one pinned remote session."""

    session_id: str
    workspace_id: str
    session_status: str
    recovery_reason_code: str | None
    runtime_engine_id: str
    model_provider_id: str
    model_id: str
    profile_definition_id: str
    profile_definition_revision: str
    workspace_binding_id: str
    workspace_binding_revision: int
    terminal_turn_ids: tuple[str, ...]
    provider_request_count: int
    provider_acceptance_count: int
    ledger_proposal_count: int
    final_output_count: int
    ambiguous_provider_step_count: int
    unaccounted_provider_acceptance_count: int
    pending_tool_invocation_count: int
    execution_unknown_count: int
    provider_state_revision: int | None
    provider_state_turn_generation: str | None
    legacy_synthetic_classification: bool
    reason_codes: tuple[str, ...]
    quarantine_required: bool
    inventory_digest: str = ""


def inventory_remote_agentic_sessions(
    store: RuntimeStore,
) -> tuple[RemoteAgenticSessionInventoryItem, ...]:
    """Inspect all pinned remote sessions without reading private payloads."""
    items: list[RemoteAgenticSessionInventoryItem] = []
    for session in store.list_all_sessions():
        binding = session.execution_binding
        if binding is None or not is_remote_agentic_identity(binding):
            continue
        turns = store.list_turns(session.session_id)
        events = _all_session_events(store, session.session_id)
        invocations = store.list_tool_invocations(session_id=session.session_id)
        terminal_turns = sorted(
            (turn for turn in turns if turn.status in _TERMINAL_TURN_STATUSES),
            key=_turn_sort_key,
        )
        step_correlation = correlate_provider_steps(events, invocations)
        request_count = step_correlation.request_count
        acceptance_count = step_correlation.acceptance_count
        final_output_count = step_correlation.final_output_count
        ledger_proposal_count = len(invocations)
        unaccounted = step_correlation.unaccounted_acceptance_count
        ambiguous_step_count = step_correlation.ambiguous_step_count
        pending_count = sum(
            1 for invocation in invocations if invocation.state in _PENDING_TOOL_STATES
        )
        execution_unknown_count = sum(
            1 for invocation in invocations if invocation.state == "execution_unknown"
        )
        reason_codes: set[str] = set()
        if session.status == "running" and terminal_turns:
            reason_codes.add("terminal_turn_running_session")
        if ambiguous_step_count:
            reason_codes.add("provider_step_outcome_ambiguous")
        if pending_count:
            reason_codes.add("tool_invocation_pending")
        if execution_unknown_count:
            reason_codes.add("tool_execution_unknown")
        legacy_synthetic = session.declared_remote_data_class == "workspace_internal_fake"
        if legacy_synthetic:
            reason_codes.add("legacy_synthetic_classification_present")

        provider_state = _provider_state_or_none(store, session.session_id)
        provider_state_revision = None if provider_state is None else provider_state.revision
        turn_generation = None if provider_state is None else provider_state.turn_generation
        completed_turn_ids = {turn.turn_id for turn in terminal_turns if turn.status == "completed"}
        final_turn_ids = {
            event.turn_id
            for event in events
            if event.event_type == "runtime.output.final" and event.turn_id
        }
        provider_state_has_state_identity = bool(
            provider_state is not None
            and (
                provider_state.continuation_id
                or provider_state.provider_thread_id
                or provider_state.provider_request_id
                or provider_state.provider_private_envelope is not None
                or provider_state.turn_generation
            )
        )
        if provider_state is None:
            reason_codes.add("provider_state_missing")
        if provider_state_has_state_identity and turn_generation not in completed_turn_ids:
            reason_codes.add("provider_state_pending")
        provider_state_committed = bool(
            provider_state is not None
            and (
                not provider_state_has_state_identity
                or (
                    turn_generation in completed_turn_ids
                    and turn_generation in final_turn_ids
                    and not ambiguous_step_count
                    and not pending_count
                    and not execution_unknown_count
                )
            )
        )
        if provider_state is not None and not provider_state_committed:
            reason_codes.add("provider_state_uncommitted")
        if (
            terminal_turns
            and (
                pending_count
                or execution_unknown_count
                or (provider_state is not None and not provider_state_committed)
            )
        ) or ambiguous_step_count:
            reason_codes.add("staged_committed_mismatch")
        turn_ids = {turn.turn_id for turn in turns}
        if turn_generation and turn_generation not in turn_ids:
            reason_codes.add("provider_state_generation_mismatch")

        quarantine_required = (
            session.status != "recovery_required"
            and session.status not in {"stopped"}
            and bool(reason_codes & _QUARANTINE_REASONS)
        )
        item = RemoteAgenticSessionInventoryItem(
            session_id=session.session_id,
            workspace_id=session.workspace_id,
            session_status=session.status,
            recovery_reason_code=public_runtime_recovery_reason_code(
                status=session.status,
                reason_code=session.recovery_reason_code,
            ),
            runtime_engine_id=binding.runtime_engine_id,
            model_provider_id=binding.model_provider_id,
            model_id=binding.model_id,
            profile_definition_id=binding.profile_definition_id,
            profile_definition_revision=binding.profile_definition_revision,
            workspace_binding_id=binding.workspace_binding_id,
            workspace_binding_revision=binding.workspace_binding_revision,
            terminal_turn_ids=tuple(turn.turn_id for turn in terminal_turns),
            provider_request_count=request_count,
            provider_acceptance_count=acceptance_count,
            ledger_proposal_count=ledger_proposal_count,
            final_output_count=final_output_count,
            ambiguous_provider_step_count=ambiguous_step_count,
            unaccounted_provider_acceptance_count=unaccounted,
            pending_tool_invocation_count=pending_count,
            execution_unknown_count=execution_unknown_count,
            provider_state_revision=provider_state_revision,
            provider_state_turn_generation=turn_generation,
            legacy_synthetic_classification=legacy_synthetic,
            reason_codes=tuple(sorted(reason_codes)),
            quarantine_required=quarantine_required,
        )
        items.append(replace(item, inventory_digest=canonical_digest(asdict(item))))
    items.sort(key=lambda item: (item.workspace_id, item.session_id))
    return tuple(items)


def _all_session_events(store: RuntimeStore, session_id: str) -> list:
    """Read the immutable archive so ambiguity cannot age out of the hot tail."""
    pages: list[tuple] = []
    before_position = None
    snapshot_position = None
    snapshot_event_id = None
    while True:
        page = store.list_event_archive_page(
            session_id,
            before_position=before_position,
            snapshot_position=snapshot_position,
            snapshot_event_id=snapshot_event_id,
            limit=500,
        )
        pages.append(tuple(page.events))
        if not page.has_more_before or page.oldest_position is None:
            break
        if before_position == page.oldest_position:
            raise RuntimeError("runtime_event_archive_pagination_stalled")
        before_position = page.oldest_position
        snapshot_position = page.snapshot_position
        snapshot_event_id = page.snapshot_event_id
    ordered: list = []
    seen_ids: set[str] = set()
    for page_events in reversed(pages):
        for event in page_events:
            if event.event_id in seen_ids:
                continue
            seen_ids.add(event.event_id)
            ordered.append(event)
    return ordered


def _provider_state_or_none(store: RuntimeStore, session_id: str):
    try:
        return store.get_provider_state(session_id)
    except RuntimeProviderStateError:
        return None


def _turn_sort_key(turn: RuntimeTurnRecord) -> tuple[str, str]:
    return turn.updated_at.isoformat(), turn.turn_id
