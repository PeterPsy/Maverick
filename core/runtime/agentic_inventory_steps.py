"""Correlate persisted provider steps with durable turn outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field


PROVIDER_REQUEST_EVENT_TYPES = frozenset(
    {"provider.request.sent", "runtime.provider.turn_start_sent"}
)
PROVIDER_ACCEPTANCE_EVENT_TYPES = frozenset(
    {"provider.accepted", "runtime.provider.accepted"}
)
TOOL_PROPOSAL_EVENT_TYPE = "runtime.tool_call.proposed"
FINAL_OUTPUT_EVENT_TYPE = "runtime.output.final"


@dataclass(frozen=True)
class ProviderStepCorrelation:
    """Counts derived from ordered provider-step outcomes, never count subtraction."""

    request_count: int
    acceptance_count: int
    final_output_count: int
    persisted_proposal_ids: tuple[str, ...]
    ambiguous_step_count: int
    unaccounted_acceptance_count: int


@dataclass
class _ProviderStep:
    turn_id: str
    request_id: str
    request_index: int | None = None
    acceptance_index: int | None = None
    persisted_proposal_ids: set[str] = field(default_factory=set)
    has_final_output: bool = False

    @property
    def start_index(self) -> int:
        if self.request_index is not None:
            return self.request_index
        assert self.acceptance_index is not None
        return self.acceptance_index

    @property
    def outcome_start_index(self) -> int:
        return self.acceptance_index if self.acceptance_index is not None else self.start_index


def correlate_provider_steps(events: list, invocations: list) -> ProviderStepCorrelation:
    """Pair each observed provider step with a final output or persisted proposal."""
    steps = _provider_steps(events)
    invocations_by_id = {
        invocation.invocation_id: invocation
        for invocation in invocations
    }
    assigned_invocations: set[str] = set()
    ordered_steps = sorted(steps, key=lambda step: step.start_index)
    for index, step in enumerate(ordered_steps):
        next_step = next(
            (
                candidate
                for candidate in ordered_steps[index + 1:]
                if candidate.turn_id == step.turn_id
            ),
            None,
        )
        end_index = next_step.start_index if next_step is not None else len(events)
        interval = events[step.outcome_start_index:end_index]
        for event in interval:
            if event.turn_id != step.turn_id:
                continue
            if event.event_type == FINAL_OUTPUT_EVENT_TYPE:
                step.has_final_output = True
                continue
            if event.event_type != TOOL_PROPOSAL_EVENT_TYPE:
                continue
            invocation_id = str(event.payload.get("invocation_id") or "").strip()
            invocation = invocations_by_id.get(invocation_id)
            if invocation is None or invocation.turn_id != step.turn_id:
                continue
            step.persisted_proposal_ids.add(invocation_id)
            assigned_invocations.add(invocation_id)

        _assign_unannounced_persisted_proposals(
            step,
            interval=interval,
            invocations=invocations,
            assigned_invocations=assigned_invocations,
            upper_time=(
                events[end_index].created_at
                if end_index < len(events)
                else None
            ),
        )

    ambiguous = [
        step
        for step in ordered_steps
        if not step.has_final_output and not step.persisted_proposal_ids
    ]
    proposal_ids = sorted(
        invocation_id
        for step in ordered_steps
        for invocation_id in step.persisted_proposal_ids
    )
    return ProviderStepCorrelation(
        request_count=sum(step.request_index is not None for step in ordered_steps),
        acceptance_count=sum(step.acceptance_index is not None for step in ordered_steps),
        final_output_count=sum(
            event.event_type == FINAL_OUTPUT_EVENT_TYPE for event in events
        ),
        persisted_proposal_ids=tuple(proposal_ids),
        ambiguous_step_count=len(ambiguous),
        unaccounted_acceptance_count=sum(
            step.acceptance_index is not None for step in ambiguous
        ),
    )


def _provider_steps(events: list) -> list[_ProviderStep]:
    steps: list[_ProviderStep] = []
    for index, event in enumerate(events):
        if event.event_type not in (
            PROVIDER_REQUEST_EVENT_TYPES | PROVIDER_ACCEPTANCE_EVENT_TYPES
        ):
            continue
        turn_id = str(event.turn_id or "")
        request_id = str(event.payload.get("request_id") or "").strip()
        if event.event_type in PROVIDER_REQUEST_EVENT_TYPES:
            pending = (
                next(
                    (
                        step
                        for step in reversed(steps)
                        if step.turn_id == turn_id
                        and step.request_id == request_id
                        and step.acceptance_index is None
                    ),
                    None,
                )
                if request_id
                else None
            )
            if pending is None:
                steps.append(
                    _ProviderStep(
                        turn_id=turn_id,
                        request_id=request_id,
                        request_index=index,
                    )
                )
            elif pending.request_index is None:
                pending.request_index = index
            continue
        pending = next(
            (
                step
                for step in steps
                if step.turn_id == turn_id
                and step.acceptance_index is None
                and (not request_id or step.request_id == request_id)
            ),
            None,
        )
        if pending is None and request_id:
            pending = next(
                (
                    step
                    for step in steps
                    if step.turn_id == turn_id
                    and not step.request_id
                    and step.acceptance_index is None
                ),
                None,
            )
        if pending is None:
            already_accepted = bool(request_id) and any(
                step.turn_id == turn_id
                and step.request_id == request_id
                and step.acceptance_index is not None
                for step in steps
            )
            if already_accepted:
                continue
            pending = _ProviderStep(turn_id=turn_id, request_id=request_id)
            steps.append(pending)
        pending.acceptance_index = index
    return steps


def _assign_unannounced_persisted_proposals(
    step: _ProviderStep,
    *,
    interval: list,
    invocations: list,
    assigned_invocations: set[str],
    upper_time,
) -> None:
    """Cover the crash window after ledger insert but before proposal-event emission."""
    if not interval:
        return
    lower = interval[0].created_at
    for invocation in invocations:
        if (
            invocation.invocation_id in assigned_invocations
            or invocation.turn_id != step.turn_id
            or invocation.created_at < lower
            or (upper_time is not None and invocation.created_at >= upper_time)
        ):
            continue
        step.persisted_proposal_ids.add(invocation.invocation_id)
        assigned_invocations.add(invocation.invocation_id)
