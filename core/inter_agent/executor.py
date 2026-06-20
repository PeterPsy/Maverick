"""Native MVP executor for core-owned inter-agent runs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
import re
from threading import Lock
from typing import Any
import time
import uuid

from core.inter_agent.errors import InterAgentOperationError
from core.inter_agent.models import InterAgentParticipantRecord, InterAgentRunRecord
from core.inter_agent.service import InterAgentService, RUNTIME_CHILD_EXECUTION_MODE
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.service import record_runtime_event


EXECUTABLE_MODES = {"manager_tools", "sequential", "concurrent"}
SCHEMA_ONLY_MODES = {"handoff", "group_chat", "magentic_like"}
TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}
TERMINAL_PARTICIPANT_STATUSES = {"completed", "failed", "cancelled"}
TERMINAL_RUNTIME_TURN_STATUSES = {"completed", "failed", "cancelled", "timed-out"}
ASYNC_RUNTIME_TURN_WAIT_TIMEOUT_SECONDS = 6 * 60 * 60
ASYNC_RUNTIME_TURN_POLL_SECONDS = 0.1


@dataclass(frozen=True)
class ControlledParticipantOutput:
    """Deterministic participant output used by tests and controlled MVP runs."""

    output_text: str = ""
    summary: str = ""
    partial_output: str = ""
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    status: str = "completed"
    error: str | None = None


@dataclass(frozen=True)
class ParticipantExecutionResult:
    """Executor-facing result for one participant task."""

    participant_id: str
    label: str
    status: str
    synthetic: bool = False
    synthetic_source: str | None = None
    output_text: str = ""
    summary: str = ""
    partial_output: str = ""
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    runtime_session_id: str | None = None
    runtime_turn_id: str | None = None


@dataclass(frozen=True)
class InterAgentExecutionResult:
    """Result returned by native executor surfaces."""

    run: InterAgentRunRecord
    participant_results: list[ParticipantExecutionResult]
    root_runtime_events: list[RuntimeEventRecord]
    final_answer: str = ""


@dataclass(frozen=True)
class FinalAnswerProjection:
    """Executor-local projection for the root orchestrator's terminal answer."""

    text: str = ""
    source_participant_ids: list[str] = field(default_factory=list)
    strategy: str = ""


def execute_inter_agent_run(
    service: InterAgentService,
    state: Any,
    *,
    workspace_id: str,
    run_id: str,
    input_text: str = "",
    participant_inputs: dict[str, str] | None = None,
    controlled_participants: dict[str, Any] | None = None,
    allow_synthetic_participants: bool = False,
    project_summaries: bool = True,
    async_runtime_turns: bool = False,
    now: datetime | None = None,
) -> InterAgentExecutionResult:
    """Execute one F3-native inter-agent run without external adapters."""
    clock = _clock(now)
    run = service.store.get_run(run_id, workspace_id=workspace_id)
    if run.status in TERMINAL_RUN_STATUSES:
        return InterAgentExecutionResult(run=run, participant_results=[], root_runtime_events=[], final_answer="")
    if run.mode == "single_agent":
        raise InterAgentOperationError("single_agent runs execute through the normal runtime turn path.")
    if run.mode in SCHEMA_ONLY_MODES:
        raise InterAgentOperationError(f"{run.mode} execution is schema/event-only before F7.")
    if run.mode not in EXECUTABLE_MODES:
        raise InterAgentOperationError(f"Unsupported inter-agent executor mode `{run.mode}`.")

    participants = service.store.list_participants(run.run_id, workspace_id=workspace_id)
    participant_by_id = {participant.participant_id: participant for participant in participants}
    orchestrator = participant_by_id.get(run.orchestrator_participant_id)
    if orchestrator is None:
        raise InterAgentOperationError("Inter-agent run has no materialized root orchestrator participant.")

    controlled = _controlled_outputs(controlled_participants)
    if controlled and not allow_synthetic_participants:
        raise InterAgentOperationError("Controlled inter-agent participant output is available only for operator/test synthetic execution.")
    planned_synthetic, planned_synthetic_source = _planned_synthetic_metadata(
        run,
        participants,
        controlled,
        allow_synthetic_participants=allow_synthetic_participants,
    )

    started_at = clock()
    run = replace(run, status="planning", updated_at=started_at)
    service.store.save_run(run)
    plan_summary = _plan_summary(run, participants)
    service.record_event(
        run,
        event_type="inter_agent.plan.summary_created",
        participant_id=orchestrator.participant_id,
        visibility_plane="summary",
        correlation_id=f"{run.run_id}:plan",
        idempotency_key=f"{run.run_id}:executor.plan.summary",
        payload={
            "summary": plan_summary,
            "mode": run.mode,
            "synthetic": planned_synthetic,
            "synthetic_source": planned_synthetic_source,
        },
        now=started_at,
    )
    root_runtime_events: list[RuntimeEventRecord] = []
    if project_summaries:
        root_runtime_events.append(
            _project_root_summary(
                state,
                run,
                text=plan_summary,
                summary_kind="plan",
                synthetic=planned_synthetic,
                synthetic_source=planned_synthetic_source,
                now=started_at,
            )
        )

    run = replace(run, status="running", updated_at=clock())
    service.store.save_run(run)
    inputs = {str(key): str(value) for key, value in dict(participant_inputs or {}).items()}

    try:
        if run.mode == "concurrent":
            participant_results = _execute_concurrent(
                service,
                state,
                run=run,
                participants=participants,
                input_text=input_text,
                participant_inputs=inputs,
                controlled_participants=controlled,
                allow_synthetic_participants=allow_synthetic_participants,
                async_runtime_turns=async_runtime_turns,
                clock=clock,
            )
        elif run.mode == "sequential":
            participant_results = _execute_sequential(
                service,
                state,
                run=run,
                participants=_work_participants(run, participants),
                input_text=input_text,
                participant_inputs=inputs,
                controlled_participants=controlled,
                allow_synthetic_participants=allow_synthetic_participants,
                async_runtime_turns=async_runtime_turns,
                clock=clock,
            )
        else:
            participant_results = _execute_manager_tools(
                service,
                state,
                run=run,
                participants=_work_participants(run, participants),
                input_text=input_text,
                participant_inputs=inputs,
                controlled_participants=controlled,
                allow_synthetic_participants=allow_synthetic_participants,
                async_runtime_turns=async_runtime_turns,
                clock=clock,
            )
    except Exception as error:
        failed_at = clock()
        latest_run = service.store.get_run(run.run_id, workspace_id=workspace_id)
        if latest_run.status == "cancelled":
            return InterAgentExecutionResult(run=latest_run, participant_results=[], root_runtime_events=root_runtime_events, final_answer="")
        failed = replace(latest_run, status="failed", updated_at=failed_at, ended_at=failed_at)
        service.store.save_run(failed)
        service.record_event(
            failed,
            event_type="inter_agent.run.failed",
            participant_id=orchestrator.participant_id,
            visibility_plane="summary",
            correlation_id=failed.run_id,
            idempotency_key=f"{failed.run_id}:executor.run.failed",
            payload={
                "error": str(error),
                "status": "failed",
                "synthetic": planned_synthetic,
                "synthetic_source": planned_synthetic_source,
            },
            now=failed_at,
        )
        if project_summaries:
            root_runtime_events.append(
                _project_root_summary(
                    state,
                    failed,
                    text=f"Multi-agent run failed: {str(error)}",
                    summary_kind="failed",
                    synthetic=planned_synthetic,
                    synthetic_source=planned_synthetic_source,
                    now=failed_at,
                )
            )
        if isinstance(error, InterAgentOperationError):
            raise
        raise InterAgentOperationError(str(error)) from error

    final_status = _final_run_status(participant_results)
    edges = service.store.list_edges(run.run_id, workspace_id=workspace_id)
    final_projection = _final_answer_projection(
        run=run,
        final_status=final_status,
        participant_results=participant_results,
        edges=edges,
    )
    final_answer = final_projection.text
    final_summary = _final_summary(
        final_status=final_status,
        participant_results=participant_results,
        final_projection=final_projection,
    )
    final_synthetic, final_synthetic_source = _result_synthetic_metadata(participant_results)
    ended_at = clock()
    latest_run = service.store.get_run(run.run_id, workspace_id=workspace_id)
    if latest_run.status == "cancelled":
        return InterAgentExecutionResult(
            run=latest_run,
            participant_results=participant_results,
            root_runtime_events=root_runtime_events,
            final_answer=final_answer,
        )
    completed_run = replace(latest_run, status=final_status, updated_at=ended_at, ended_at=ended_at)
    service.store.save_run(completed_run)
    _complete_orchestrator_synthesis(
        service,
        completed_run,
        orchestrator_id=orchestrator.participant_id,
        final_status=final_status,
        final_projection=final_projection,
        synthetic=final_synthetic,
        synthetic_source=final_synthetic_source,
        now=ended_at,
    )
    service.record_event(
        completed_run,
        event_type="inter_agent.summary.updated",
        participant_id=orchestrator.participant_id,
        visibility_plane="summary",
        correlation_id=f"{completed_run.run_id}:final-summary",
        idempotency_key=f"{completed_run.run_id}:executor.summary.final",
        payload={
            "summary": final_summary,
            "status": final_status,
            "final_answer": final_answer,
            "final_answer_strategy": final_projection.strategy,
            "source_participant_ids": final_projection.source_participant_ids,
            "synthetic": final_synthetic,
            "synthetic_source": final_synthetic_source,
        },
        now=ended_at,
    )
    terminal_event_type = {
        "completed": "inter_agent.run.completed",
        "failed": "inter_agent.run.failed",
        "cancelled": "inter_agent.run.cancelled",
    }[final_status]
    service.record_event(
        completed_run,
        event_type=terminal_event_type,  # type: ignore[arg-type]
        participant_id=orchestrator.participant_id,
        visibility_plane="summary",
        correlation_id=completed_run.run_id,
        idempotency_key=f"{completed_run.run_id}:executor.run.{final_status}",
        payload={
            "summary": final_summary,
            "status": final_status,
            "final_answer": final_answer,
            "synthetic": final_synthetic,
            "synthetic_source": final_synthetic_source,
        },
        now=ended_at,
    )
    if project_summaries:
        root_runtime_events.append(
            _project_root_summary(
                state,
                completed_run,
                text=final_summary,
                summary_kind=final_status,
                synthetic=final_synthetic,
                synthetic_source=final_synthetic_source,
                now=ended_at,
            )
        )
    return InterAgentExecutionResult(
        run=completed_run,
        participant_results=participant_results,
        root_runtime_events=root_runtime_events,
        final_answer=final_answer,
    )


def _execute_manager_tools(
    service: InterAgentService,
    state: Any,
    *,
    run: InterAgentRunRecord,
    participants: list[InterAgentParticipantRecord],
    input_text: str,
    participant_inputs: dict[str, str],
    controlled_participants: dict[str, ControlledParticipantOutput],
    allow_synthetic_participants: bool,
    async_runtime_turns: bool,
    clock,
) -> list[ParticipantExecutionResult]:
    results: list[ParticipantExecutionResult] = []
    for index, participant in enumerate(participants):
        result = _execute_one_participant(
            service,
            state,
            run=run,
            participant=participant,
            task_index=index,
            input_text=_manager_tools_participant_input(
                participant,
                base_input=input_text,
                participant_inputs=participant_inputs,
            ),
            controlled=controlled_participants.get(participant.participant_id),
            allow_synthetic_participants=allow_synthetic_participants,
            async_runtime_turns=async_runtime_turns,
            clock=clock,
        )
        results.append(result)
    return results


def _execute_sequential(
    service: InterAgentService,
    state: Any,
    *,
    run: InterAgentRunRecord,
    participants: list[InterAgentParticipantRecord],
    input_text: str,
    participant_inputs: dict[str, str],
    controlled_participants: dict[str, ControlledParticipantOutput],
    allow_synthetic_participants: bool,
    async_runtime_turns: bool,
    clock,
) -> list[ParticipantExecutionResult]:
    results: list[ParticipantExecutionResult] = []
    previous_output = ""
    for index, participant in enumerate(participants):
        participant_input = _participant_input(
            participant,
            base_input=input_text,
            participant_inputs=participant_inputs,
            previous_output=previous_output,
        )
        result = _execute_one_participant(
            service,
            state,
            run=run,
            participant=participant,
            task_index=index,
            input_text=participant_input,
            controlled=controlled_participants.get(participant.participant_id),
            allow_synthetic_participants=allow_synthetic_participants,
            async_runtime_turns=async_runtime_turns,
            clock=clock,
        )
        results.append(result)
        if result.status == "failed":
            break
        previous_output = result.output_text or result.summary
    return results


def _execute_concurrent(
    service: InterAgentService,
    state: Any,
    *,
    run: InterAgentRunRecord,
    participants: list[InterAgentParticipantRecord],
    input_text: str,
    participant_inputs: dict[str, str],
    controlled_participants: dict[str, ControlledParticipantOutput],
    allow_synthetic_participants: bool,
    async_runtime_turns: bool,
    clock,
) -> list[ParticipantExecutionResult]:
    aggregator_id = run.aggregator_participant_id or run.orchestrator_participant_id
    fanout = [
        participant
        for participant in _work_participants(run, participants)
        if participant.participant_id != aggregator_id
    ]
    max_workers = max(1, min(_max_concurrent_participants(service, run), len(fanout) or 1))
    results_by_id: dict[str, ParticipantExecutionResult] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _execute_one_participant,
                service,
                state,
                run=run,
                participant=participant,
                task_index=index,
                input_text=_participant_input(
                    participant,
                    base_input=input_text,
                    participant_inputs=participant_inputs,
                ),
                controlled=controlled_participants.get(participant.participant_id),
                allow_synthetic_participants=allow_synthetic_participants,
                async_runtime_turns=async_runtime_turns,
                clock=clock,
            ): participant.participant_id
            for index, participant in enumerate(fanout)
        }
        for future in as_completed(futures):
            result = future.result()
            results_by_id[result.participant_id] = result
    results = [results_by_id[participant.participant_id] for participant in fanout if participant.participant_id in results_by_id]
    aggregator = _participant_by_id(participants, aggregator_id)
    if aggregator is not None and aggregator.participant_id != run.orchestrator_participant_id:
        merged_input = _merge_input_for_aggregator(input_text=input_text, fanout_results=results)
        results.append(
            _execute_one_participant(
                service,
                state,
                run=run,
                participant=aggregator,
                task_index=len(results),
                input_text=_participant_input(
                    aggregator,
                    base_input=merged_input,
                    participant_inputs=participant_inputs,
                ),
                controlled=controlled_participants.get(aggregator.participant_id),
                allow_synthetic_participants=allow_synthetic_participants,
                async_runtime_turns=async_runtime_turns,
                clock=clock,
            )
        )
    return results


def _execute_one_participant(
    service: InterAgentService,
    state: Any,
    *,
    run: InterAgentRunRecord,
    participant: InterAgentParticipantRecord,
    task_index: int,
    input_text: str,
    controlled: ControlledParticipantOutput | None,
    allow_synthetic_participants: bool,
    async_runtime_turns: bool,
    clock,
) -> ParticipantExecutionResult:
    task_id = f"task:{run.mode}:{task_index}:{participant.participant_id}"
    started_at = clock()
    service.record_event(
        run,
        event_type="inter_agent.task.created",
        participant_id=participant.participant_id,
        visibility_plane="detail",
        correlation_id=task_id,
        idempotency_key=f"{run.run_id}:executor.task.created:{task_id}",
        payload={"task_id": task_id, "participant_id": participant.participant_id, "mode": run.mode},
        now=started_at,
    )
    service.record_event(
        run,
        event_type="inter_agent.task.started",
        participant_id=participant.participant_id,
        visibility_plane="detail",
        correlation_id=task_id,
        idempotency_key=f"{run.run_id}:executor.task.started:{task_id}",
        payload={"task_id": task_id, "participant_id": participant.participant_id},
        now=started_at,
    )
    if controlled is not None or participant.execution_mode != RUNTIME_CHILD_EXECUTION_MODE:
        if not allow_synthetic_participants:
            raise InterAgentOperationError("Synthetic inter-agent participant execution requires an operator/test allowance.")
        return _execute_controlled_participant(
            service,
            run,
            participant=participant,
            task_id=task_id,
            input_text=input_text,
            controlled=controlled or _default_controlled_output(participant),
            controlled_supplied=controlled is not None,
            clock=clock,
        )
    return _execute_runtime_participant(
        service,
        state,
        run,
        participant=participant,
        task_id=task_id,
        input_text=input_text,
        async_runtime_turns=async_runtime_turns,
        clock=clock,
    )


def _execute_controlled_participant(
    service: InterAgentService,
    run: InterAgentRunRecord,
    *,
    participant: InterAgentParticipantRecord,
    task_id: str,
    input_text: str,
    controlled: ControlledParticipantOutput,
    controlled_supplied: bool,
    clock,
) -> ParticipantExecutionResult:
    running_reservation_id = f"executor.running:{participant.participant_id}:{task_id}"
    turn_reservation_id = f"executor.turn:{participant.participant_id}:{task_id}"
    synthetic_source = "controlled_payload" if controlled_supplied else "default_test_output"
    service.reserve_budget(
        run,
        reservation_id=running_reservation_id,
        participant_id=participant.participant_id,
        running_participants=1,
        now=clock(),
    )
    try:
        service.reserve_budget(
            run,
            reservation_id=turn_reservation_id,
            participant_id=participant.participant_id,
            turns=1,
            now=clock(),
        )
    except Exception:
        service.release_budget(run, reservation_id=running_reservation_id, now=clock())
        raise
    started = replace(participant, status="running", current_task_id=task_id, updated_at=clock())
    service.store.save_participant(started)
    service.record_event(
        run,
        event_type="inter_agent.participant.started",
        participant_id=participant.participant_id,
        visibility_plane="detail",
        correlation_id=task_id,
        idempotency_key=f"{run.run_id}:executor.participant.started:{participant.participant_id}:{task_id}",
        payload={
            "participant_id": participant.participant_id,
            "execution_mode": participant.execution_mode,
            "synthetic": True,
            "synthetic_source": synthetic_source,
            "controlled": controlled_supplied,
        },
        now=clock(),
    )
    service.record_event(
        run,
        event_type="inter_agent.message.sent",
        participant_id=participant.participant_id,
        visibility_plane="detail",
        correlation_id=task_id,
        idempotency_key=f"{run.run_id}:executor.message.sent:{participant.participant_id}:{task_id}",
        payload={
            "participant_id": participant.participant_id,
            "delivery_mode": "synthetic_controlled" if controlled_supplied else "synthetic_default",
            "synthetic": True,
            "synthetic_source": synthetic_source,
            "input_text": input_text,
        },
        now=clock(),
    )
    if controlled.artifact_refs or controlled.partial_output:
        _record_artifacts(
            service,
            run,
            participant=participant,
            task_id=task_id,
            artifact_refs=controlled.artifact_refs,
            partial_output=controlled.partial_output,
            synthetic=True,
            synthetic_source=synthetic_source,
            clock=clock,
        )
    status = "failed" if controlled.status == "failed" else "completed"
    output_text = controlled.output_text if status == "completed" else controlled.partial_output or controlled.output_text
    summary = controlled.summary or _compact_summary(output_text) or f"{participant.label} {status}."
    _finish_participant(
        service,
        run,
        participant=started,
        status=status,
        task_id=task_id,
        summary=summary,
        output_text=output_text,
        error=controlled.error,
        reservation_id=running_reservation_id,
        runtime_session_id=None,
        runtime_turn_id=None,
        synthetic=True,
        synthetic_source=synthetic_source,
        clock=clock,
    )
    return ParticipantExecutionResult(
        participant_id=participant.participant_id,
        label=participant.label,
        status=status,
        synthetic=True,
        synthetic_source=synthetic_source,
        output_text=controlled.output_text,
        summary=summary,
        partial_output=controlled.partial_output,
        artifact_refs=controlled.artifact_refs,
        error=controlled.error,
    )


def _execute_runtime_participant(
    service: InterAgentService,
    state: Any,
    run: InterAgentRunRecord,
    *,
    participant: InterAgentParticipantRecord,
    task_id: str,
    input_text: str,
    async_runtime_turns: bool,
    clock,
) -> ParticipantExecutionResult:
    runtime_session_id: str | None = None
    try:
        latest_run = service.store.get_run(run.run_id, workspace_id=run.workspace_id)
        if latest_run.status in TERMINAL_RUN_STATUSES:
            return ParticipantExecutionResult(
                participant_id=participant.participant_id,
                label=participant.label,
                status=latest_run.status,
                error=f"Inter-agent run is {latest_run.status}.",
            )
        spawned, session, _created = service.spawn_participant_runtime_session(
            state.runtime_store,
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            participant_id=participant.participant_id,
            now=clock(),
        )
        runtime_session_id = session.session_id
        _participant, turn, events = service.send_runtime_message(
            state,
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            participant_id=spawned.participant_id,
            input_text=input_text,
            client_message_id=f"inter-agent:{run.run_id}:{task_id}",
            async_requested=async_runtime_turns,
            now=clock(),
        )
        if async_runtime_turns and turn.status not in TERMINAL_RUNTIME_TURN_STATUSES:
            turn = _wait_for_runtime_turn(state, turn.turn_id)
            events = _runtime_events_for_turn(state, session_id=session.session_id, turn_id=turn.turn_id)
    except Exception as error:
        latest_run = service.store.get_run(run.run_id, workspace_id=run.workspace_id)
        latest = service.store.get_participant(participant.participant_id, workspace_id=run.workspace_id, run_id=run.run_id)
        if latest.runtime_session_id:
            runtime_session_id = latest.runtime_session_id
        if latest_run.status == "cancelled" or latest.status == "cancelled":
            return ParticipantExecutionResult(
                participant_id=participant.participant_id,
                label=participant.label,
                status="cancelled",
                error=str(error),
                runtime_session_id=runtime_session_id,
            )
        _finish_participant(
            service,
            run,
            participant=latest,
            status="failed",
            task_id=task_id,
            summary=f"{participant.label} failed before completing runtime work.",
            output_text="",
            error=str(error),
            reservation_id=_participant_spawn_reservation_id(participant.participant_id),
            runtime_session_id=runtime_session_id,
            runtime_turn_id=None,
            synthetic=False,
            synthetic_source=None,
            clock=clock,
        )
        raise
    latest_run = service.store.get_run(run.run_id, workspace_id=run.workspace_id)
    latest_participant = service.store.get_participant(participant.participant_id, workspace_id=run.workspace_id, run_id=run.run_id)
    runtime_session_id = latest_participant.runtime_session_id or session.session_id
    if latest_run.status == "cancelled" or latest_participant.status == "cancelled":
        return ParticipantExecutionResult(
            participant_id=participant.participant_id,
            label=participant.label,
            status="cancelled",
            error=turn.failure_reason,
            runtime_session_id=runtime_session_id,
            runtime_turn_id=turn.turn_id,
        )
    output_text = _runtime_output_text(events)
    partial_output = _runtime_partial_output_text(events)
    artifact_refs = _runtime_artifact_refs(events)
    if turn.status == "cancelled":
        summary = _runtime_participant_summary(participant.label, "cancelled", output_text=output_text)
        if artifact_refs or partial_output:
            _record_artifacts(
                service,
                run,
                participant=latest_participant,
                task_id=task_id,
                artifact_refs=artifact_refs,
                partial_output=partial_output,
                synthetic=False,
                synthetic_source=None,
                clock=clock,
            )
        _finish_participant(
            service,
            run,
            participant=latest_participant,
            status="cancelled",
            task_id=task_id,
            summary=summary,
            output_text=output_text,
            error=turn.failure_reason,
            reservation_id=_participant_spawn_reservation_id(participant.participant_id),
            runtime_session_id=runtime_session_id,
            runtime_turn_id=turn.turn_id,
            synthetic=False,
            synthetic_source=None,
            clock=clock,
        )
        return ParticipantExecutionResult(
            participant_id=participant.participant_id,
            label=participant.label,
            status="cancelled",
            synthetic=False,
            synthetic_source=None,
            output_text=output_text,
            summary=summary,
            partial_output=partial_output,
            artifact_refs=artifact_refs,
            error=turn.failure_reason,
            runtime_session_id=runtime_session_id,
            runtime_turn_id=turn.turn_id,
        )
    status = "completed" if turn.status == "completed" else "failed"
    if status == "failed" and (artifact_refs or partial_output):
        _record_artifacts(
            service,
            run,
            participant=participant,
            task_id=task_id,
            artifact_refs=artifact_refs,
            partial_output=partial_output,
            synthetic=False,
            synthetic_source=None,
            clock=clock,
        )
    summary = _runtime_participant_summary(
        participant.label,
        status,
        output_text=output_text,
        error=turn.failure_reason,
    )
    _finish_participant(
        service,
        run,
        participant=latest_participant,
        status=status,
        task_id=task_id,
        summary=summary,
        output_text=output_text,
        error=turn.failure_reason,
        reservation_id=_participant_spawn_reservation_id(participant.participant_id),
        runtime_session_id=session.session_id,
        runtime_turn_id=turn.turn_id,
        synthetic=False,
        synthetic_source=None,
        clock=clock,
    )
    return ParticipantExecutionResult(
        participant_id=participant.participant_id,
        label=participant.label,
        status=status,
        synthetic=False,
        synthetic_source=None,
        output_text=output_text,
        summary=summary,
        partial_output=partial_output,
        artifact_refs=artifact_refs,
        error=turn.failure_reason,
        runtime_session_id=session.session_id,
        runtime_turn_id=turn.turn_id,
    )


def _wait_for_runtime_turn(state: Any, turn_id: str) -> Any:
    deadline = time.monotonic() + ASYNC_RUNTIME_TURN_WAIT_TIMEOUT_SECONDS
    while True:
        turn = state.runtime_store.get_turn(turn_id)
        if turn.status in TERMINAL_RUNTIME_TURN_STATUSES:
            return turn
        if time.monotonic() >= deadline:
            raise InterAgentOperationError("Timed out waiting for async participant runtime turn.")
        time.sleep(ASYNC_RUNTIME_TURN_POLL_SECONDS)


def _runtime_events_for_turn(state: Any, *, session_id: str, turn_id: str) -> list[RuntimeEventRecord]:
    return [event for event in state.runtime_store.list_events(session_id) if event.turn_id == turn_id]


def _finish_participant(
    service: InterAgentService,
    run: InterAgentRunRecord,
    *,
    participant: InterAgentParticipantRecord,
    status: str,
    task_id: str,
    summary: str,
    output_text: str,
    error: str | None,
    reservation_id: str,
    runtime_session_id: str | None,
    runtime_turn_id: str | None,
    synthetic: bool,
    synthetic_source: str | None,
    clock,
) -> None:
    finished_at = clock()
    updated = replace(participant, status=status, current_task_id=None, updated_at=finished_at)
    service.store.save_participant(updated)
    service.record_event(
        run,
        event_type="inter_agent.task.completed",
        participant_id=participant.participant_id,
        runtime_session_id=runtime_session_id,
        runtime_turn_id=runtime_turn_id,
        visibility_plane="detail",
        correlation_id=task_id,
        idempotency_key=f"{run.run_id}:executor.task.completed:{task_id}",
        payload={
            "task_id": task_id,
            "participant_id": participant.participant_id,
            "status": status,
            "summary": summary,
            "output_text": output_text,
            "error": error,
            "synthetic": synthetic,
            "synthetic_source": synthetic_source,
        },
        now=finished_at,
    )
    service.record_event(
        run,
        event_type="inter_agent.participant.status_changed",
        participant_id=participant.participant_id,
        runtime_session_id=runtime_session_id,
        runtime_turn_id=runtime_turn_id,
        visibility_plane="detail",
        correlation_id=participant.participant_id,
        idempotency_key=f"{run.run_id}:executor.participant.{status}:{participant.participant_id}:{task_id}",
        payload={
            "participant_id": participant.participant_id,
            "status": status,
            "error": error,
            "synthetic": synthetic,
            "synthetic_source": synthetic_source,
        },
        now=finished_at,
    )
    service.record_event(
        run,
        event_type="inter_agent.summary.updated",
        participant_id=participant.participant_id,
        runtime_session_id=runtime_session_id,
        runtime_turn_id=runtime_turn_id,
        visibility_plane="summary",
        correlation_id=task_id,
        idempotency_key=f"{run.run_id}:executor.participant.summary:{participant.participant_id}:{task_id}",
        payload={
            "participant_id": participant.participant_id,
            "label": participant.label,
            "summary": summary,
            "status": status,
            "synthetic": synthetic,
            "synthetic_source": synthetic_source,
        },
        now=finished_at,
    )
    service.release_budget(run, reservation_id=reservation_id, now=finished_at)


def _record_artifacts(
    service: InterAgentService,
    run: InterAgentRunRecord,
    *,
    participant: InterAgentParticipantRecord,
    task_id: str,
    artifact_refs: list[dict[str, Any]],
    partial_output: str,
    clock,
    synthetic: bool = False,
    synthetic_source: str | None = None,
) -> None:
    service.record_event(
        run,
        event_type="inter_agent.artifact.created",
        participant_id=participant.participant_id,
        visibility_plane="detail",
        correlation_id=task_id,
        idempotency_key=f"{run.run_id}:executor.artifact:{participant.participant_id}:{task_id}",
        payload={
            "participant_id": participant.participant_id,
            "artifact_refs": artifact_refs,
            "partial_output": partial_output,
            "status": "partial" if partial_output else "created",
            "synthetic": synthetic,
            "synthetic_source": synthetic_source,
        },
        now=clock(),
    )


def _project_root_summary(
    state: Any,
    run: InterAgentRunRecord,
    *,
    text: str,
    summary_kind: str,
    synthetic: bool,
    synthetic_source: str | None,
    now: datetime,
) -> RuntimeEventRecord:
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid.uuid4()),
        session_id=run.root_runtime_session_id,
        plane="runtime",
        event_type="runtime.step.updated",
        payload={
            "label": text,
            "summary": text,
            "step_kind": "inter_agent_summary",
            "inter_agent_run_id": run.run_id,
            "summary_kind": summary_kind,
            "synthetic": synthetic,
            "synthetic_source": synthetic_source,
        },
        now=now,
        event_bus=getattr(state, "runtime_event_bus", None),
    )


def _controlled_outputs(payload: dict[str, Any] | None) -> dict[str, ControlledParticipantOutput]:
    outputs: dict[str, ControlledParticipantOutput] = {}
    for participant_id, value in dict(payload or {}).items():
        participant_key = str(participant_id).strip()
        if not participant_key:
            continue
        outputs[participant_key] = _controlled_output(value)
    return outputs


def _controlled_output(value: Any) -> ControlledParticipantOutput:
    if isinstance(value, ControlledParticipantOutput):
        return value
    if isinstance(value, str):
        return ControlledParticipantOutput(output_text=value, summary=_compact_summary(value))
    if not isinstance(value, dict):
        return ControlledParticipantOutput()
    status = str(value.get("status") or "").strip() or ("failed" if bool(value.get("fail")) else "completed")
    if status not in {"completed", "failed"}:
        status = "failed" if status in {"error", "cancelled"} else "completed"
    artifact_refs = [
        dict(item)
        for item in value.get("artifact_refs", [])
        if isinstance(item, dict)
    ] if isinstance(value.get("artifact_refs"), list) else []
    output_text = str(value.get("output_text") or value.get("output") or "").strip()
    partial_output = str(value.get("partial_output") or "").strip()
    summary = str(value.get("summary") or "").strip()
    error = str(value.get("error") or "").strip() or None
    return ControlledParticipantOutput(
        output_text=output_text,
        summary=summary,
        partial_output=partial_output,
        artifact_refs=artifact_refs,
        status=status,
        error=error,
    )


def _default_controlled_output(participant: InterAgentParticipantRecord) -> ControlledParticipantOutput:
    output = f"{participant.label} completed controlled MVP work."
    return ControlledParticipantOutput(output_text=output, summary=output)


def _planned_synthetic_metadata(
    run: InterAgentRunRecord,
    participants: list[InterAgentParticipantRecord],
    controlled_participants: dict[str, ControlledParticipantOutput],
    *,
    allow_synthetic_participants: bool,
) -> tuple[bool, str | None]:
    if not allow_synthetic_participants:
        return False, None
    sources = [
        source
        for participant in _work_participants(run, participants)
        if (source := _synthetic_source_for_participant(participant, controlled_participants.get(participant.participant_id)))
    ]
    return bool(sources), _combine_synthetic_sources(sources)


def _result_synthetic_metadata(participant_results: list[ParticipantExecutionResult]) -> tuple[bool, str | None]:
    sources = [result.synthetic_source for result in participant_results if result.synthetic and result.synthetic_source]
    return any(result.synthetic for result in participant_results), _combine_synthetic_sources(sources)


def _synthetic_source_for_participant(
    participant: InterAgentParticipantRecord,
    controlled: ControlledParticipantOutput | None,
) -> str | None:
    if controlled is not None:
        return "controlled_payload"
    if participant.execution_mode != RUNTIME_CHILD_EXECUTION_MODE:
        return "default_test_output"
    return None


def _combine_synthetic_sources(sources: list[str | None]) -> str | None:
    unique = sorted({str(source).strip() for source in sources if str(source or "").strip()})
    if not unique:
        return None
    return unique[0] if len(unique) == 1 else "mixed"


def _work_participants(
    run: InterAgentRunRecord,
    participants: list[InterAgentParticipantRecord],
) -> list[InterAgentParticipantRecord]:
    return [
        participant
        for participant in participants
        if participant.participant_id != run.orchestrator_participant_id
        and participant.kind != "orchestrator"
        and participant.status not in TERMINAL_PARTICIPANT_STATUSES
    ]


def _participant_by_id(
    participants: list[InterAgentParticipantRecord],
    participant_id: str | None,
) -> InterAgentParticipantRecord | None:
    if not participant_id:
        return None
    for participant in participants:
        if participant.participant_id == participant_id:
            return participant
    return None


_LEADING_WORKER_DIRECTIVE_RE = re.compile(
    r"^\s*(?:(?:please|per favore)\s+)?"
    r"(?:use|run|create|start|spawn|usa|usare|utilizza|utilizzare|crea|creare|avvia|avviare|esegui|eseguire)\s+"
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|"
    r"uno|una|due|tre|quattro|cinque|sei|sette|otto|nove|dieci|\d+)\s+"
    r"(?:workers?|agents?|agenti|worker)\b\s*(?::[^.!?]*?)?"
    r"(?:,\s*(?:but|and|ma|e)\s+|\s+(?:to|per)\s+)",
    re.IGNORECASE,
)
_ROUTING_DIRECTIVE_TERM_RE = re.compile(
    r"\b(?:workers?|implementers?|reviewers?|orchestrators?|orchestrator[ei]?|"
    r"orchestration|orchestrazione|multi[- ]agent|handoffs?|routing|instradamento)\b",
    re.IGNORECASE,
)
_ROUTING_DIRECTIVE_VERB_RE = re.compile(
    r"\b(?:assign|delegate|handoff|route|routing|orchestrate|spawn|must|should|"
    r"assegna|assegnare|delega|delegare|instrada|instradare|orchestra|orchestrare|deve|dovrebbe)\b"
    r"|^\s*(?:(?:please|per favore)\s+)?"
    r"(?:use|run|create|start|usa|usare|utilizza|utilizzare|crea|creare|avvia|avviare|esegui|eseguire)\b",
    re.IGNORECASE,
)
_ROUTING_ROLE_LABEL_RE = re.compile(
    r"^\s*(?:implementer|reviewer|orchestrator|orchestratore|revisore)\s*:",
    re.IGNORECASE,
)


def _worker_request_context(value: str) -> str:
    """Return user task context with obvious Maverick routing instructions removed."""

    text = " ".join(str(value or "").split())
    if not text:
        return ""
    text = _LEADING_WORKER_DIRECTIVE_RE.sub("", text).strip()
    fragments = [fragment.strip() for fragment in re.split(r"(?<=[.!?])\s+", text) if fragment.strip()]
    kept = [fragment for fragment in fragments if not _looks_like_orchestration_directive(fragment)]
    if not kept and fragments and not _looks_like_orchestration_directive(text):
        kept = [text]
    return " ".join(kept).strip()


def _looks_like_orchestration_directive(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if _ROUTING_ROLE_LABEL_RE.search(text):
        return True
    if not _ROUTING_DIRECTIVE_TERM_RE.search(text):
        return False
    if _ROUTING_DIRECTIVE_VERB_RE.search(text):
        return True
    return "implementer" in text and "reviewer" in text


def _participant_input(
    participant: InterAgentParticipantRecord,
    *,
    base_input: str,
    participant_inputs: dict[str, str],
    previous_output: str = "",
) -> str:
    specific = participant_inputs.get(participant.participant_id, "").strip()
    request_text = _worker_request_context(base_input)
    sections = [
        "You are a delegated worker in a Maverick multi-agent run.",
        f"Participant: {participant.label} ({participant.participant_id}).",
        (
            "Complete only the delegated task below. Do not act as the orchestrator, "
            "do not announce a handoff, do not delegate further, and do not mention "
            "workers, reviewers, orchestration, routing, or internal run mechanics in the user-facing answer."
        ),
    ]
    if specific:
        sections.append(f"Delegated task:\n{specific}")
    elif request_text:
        sections.append(f"Delegated task:\nProduce the user-facing answer for the request content below.")
    else:
        sections.append(f"Delegated task:\nExecute the assigned task for {participant.label}.")
    if request_text:
        sections.append(
            "User request content:\n"
            f"{request_text}\n\n"
            "Use this only as task context. Do not mention internal workers, reviewers, routing, or orchestration."
        )
    if previous_output:
        suffix = f"Previous participant output:\n{previous_output}"
        sections.append(suffix)
    return "\n\n".join(sections)


def _manager_tools_participant_input(
    participant: InterAgentParticipantRecord,
    *,
    base_input: str,
    participant_inputs: dict[str, str],
) -> str:
    specific = participant_inputs.get(participant.participant_id, "").strip()
    user_request = _worker_request_context(base_input)
    if specific:
        sections = [
            "You are a delegated worker in a Maverick multi-agent manager-tools run.",
            f"Participant: {participant.label} ({participant.participant_id}).",
            (
                "Complete only the delegated task below. Do not act as the orchestrator, "
                "do not announce a handoff, and do not delegate further."
            ),
            f"Delegated task:\n{specific}",
        ]
        if user_request and user_request != specific:
            sections.append(f"User request context:\n{user_request}")
        return "\n\n".join(sections)
    if user_request:
        return "\n\n".join(
            [
                "You are a delegated worker in a Maverick multi-agent manager-tools run.",
                f"Participant: {participant.label} ({participant.participant_id}).",
                (
                    "Produce the final answer for the user's request. Do not act as the orchestrator, "
                    "do not announce a handoff, and do not delegate further."
                ),
                f"User request:\n{user_request}",
            ]
        )
    return "\n\n".join(
        [
            "You are a delegated worker in a Maverick multi-agent manager-tools run.",
            f"Participant: {participant.label} ({participant.participant_id}).",
            "Execute the assigned task and return the final answer. Do not act as the orchestrator or delegate further.",
        ]
    )


def _merge_input_for_aggregator(*, input_text: str, fanout_results: list[ParticipantExecutionResult]) -> str:
    sections = [str(input_text or "").strip()] if str(input_text or "").strip() else []
    for result in fanout_results:
        sections.append(f"{result.label}: {result.summary or result.output_text or result.status}")
    return "\n\n".join(sections)


def _plan_summary(run: InterAgentRunRecord, participants: list[InterAgentParticipantRecord]) -> str:
    work_count = len(_work_participants(run, participants))
    worker_nodes = _plural(work_count, "worker node")
    if run.mode == "concurrent":
        return f"Orchestrator started a parallel multi-agent run with {worker_nodes}."
    if run.mode == "sequential":
        return f"Orchestrator started a staged multi-agent run with {worker_nodes}."
    return f"Orchestrator started a delegated multi-agent run with {worker_nodes}."


def _final_summary(
    *,
    final_status: str,
    participant_results: list[ParticipantExecutionResult],
    final_projection: FinalAnswerProjection | None = None,
) -> str:
    projected = _summary_from_final_projection(final_status=final_status, final_projection=final_projection)
    if projected:
        return projected
    if not participant_results:
        return "Multi-agent run completed without participant work."
    if final_status == "completed":
        prefix = "Multi-agent run completed."
    elif final_status == "cancelled":
        prefix = "Multi-agent run cancelled."
    else:
        prefix = "Multi-agent run failed."
    summaries = []
    for result in participant_results:
        text = result.summary or result.output_text or result.partial_output or result.error or result.status
        summaries.append(f"{result.label}: {_compact_summary(text)}")
    return f"{prefix} " + " ".join(summaries)


def _summary_from_final_projection(
    *,
    final_status: str,
    final_projection: FinalAnswerProjection | None,
) -> str:
    if final_projection is None:
        return ""
    text = str(final_projection.text or "").strip()
    if not text:
        return ""
    if final_status == "completed":
        if text.startswith("Multi-agent run completed."):
            return text
        return f"Multi-agent run completed. {text}"
    if final_status == "cancelled":
        if text.startswith("Multi-agent run cancelled."):
            return text
        return f"Multi-agent run cancelled. {text}"
    if text.startswith("Multi-agent run failed"):
        return text
    return f"Multi-agent run failed. {text}"


def _final_run_status(participant_results: list[ParticipantExecutionResult]) -> str:
    if any(result.status == "cancelled" for result in participant_results):
        return "cancelled"
    if any(result.status == "failed" for result in participant_results):
        return "failed"
    return "completed"


def _complete_orchestrator_synthesis(
    service: InterAgentService,
    run: InterAgentRunRecord,
    *,
    orchestrator_id: str,
    final_status: str,
    final_projection: FinalAnswerProjection,
    synthetic: bool,
    synthetic_source: str | None,
    now: datetime,
) -> None:
    if final_status != "completed":
        return
    orchestrator = service.store.get_participant(orchestrator_id, workspace_id=run.workspace_id, run_id=run.run_id)
    participant_status = "completed"
    updated = replace(orchestrator, status=participant_status, current_task_id=None, updated_at=now)
    service.store.save_participant(updated)
    service.record_event(
        run,
        event_type="inter_agent.participant.status_changed",
        participant_id=orchestrator.participant_id,
        visibility_plane="detail",
        correlation_id=f"{run.run_id}:orchestrator-final",
        idempotency_key=f"{run.run_id}:executor.orchestrator.final:{participant_status}",
        payload={
            "participant_id": orchestrator.participant_id,
            "status": participant_status,
            "final_answer_synthesized": bool(final_projection.text),
            "final_answer_strategy": final_projection.strategy,
            "source_participant_ids": final_projection.source_participant_ids,
            "synthetic": synthetic,
            "synthetic_source": synthetic_source,
        },
        now=now,
    )


def _final_answer_projection(
    *,
    run: InterAgentRunRecord,
    final_status: str,
    participant_results: list[ParticipantExecutionResult],
    edges: list[Any],
) -> FinalAnswerProjection:
    if not participant_results:
        return FinalAnswerProjection()
    if final_status == "cancelled":
        return FinalAnswerProjection(strategy="cancelled")
    successful = [result for result in participant_results if result.status == "completed"]
    if len(successful) == 1:
        return FinalAnswerProjection(
            text=_participant_final_text(successful[0]),
            source_participant_ids=[successful[0].participant_id],
            strategy="single_participant",
        )
    if successful:
        successful_by_id = {result.participant_id: result for result in successful}
        for participant_id in _terminal_answer_participant_ids(run, edges, successful_by_id):
            text = _participant_final_text(successful_by_id[participant_id])
            if text:
                return FinalAnswerProjection(
                    text=text,
                    source_participant_ids=[participant_id],
                    strategy="topology_terminal_participant",
                )
        if run.mode == "sequential":
            for result in reversed(successful):
                text = _participant_final_text(result)
                if text:
                    return FinalAnswerProjection(
                        text=text,
                        source_participant_ids=[result.participant_id],
                        strategy="last_successful_participant",
                    )
        summaries = [_compact_summary(_participant_final_text(result), max_chars=140) for result in successful]
        summaries = [summary for summary in summaries if summary]
        if summaries:
            return FinalAnswerProjection(
                text=f"Multi-agent run completed. {' '.join(summaries)}",
                source_participant_ids=[result.participant_id for result in successful],
                strategy="orchestrator_compact_summary",
            )
    failed = [result for result in participant_results if result.status == "failed"]
    if failed:
        details = []
        for result in failed:
            text = str(result.output_text or result.error or result.summary or "").strip()
            if text:
                details.append(f"{result.label}: {text}")
        if details:
            return FinalAnswerProjection(
                text=f"Multi-agent run failed before producing a final answer. {' '.join(details)}",
                source_participant_ids=[result.participant_id for result in failed],
                strategy="failure_summary",
            )
        return FinalAnswerProjection(text="Multi-agent run failed before producing a final answer.", strategy="failure_summary")
    return FinalAnswerProjection()


def _terminal_answer_participant_ids(
    run: InterAgentRunRecord,
    edges: list[Any],
    successful_by_id: dict[str, ParticipantExecutionResult],
) -> list[str]:
    terminal_ids: list[str] = []
    aggregator_id = str(run.aggregator_participant_id or "").strip()
    if aggregator_id and aggregator_id != run.orchestrator_participant_id and aggregator_id in successful_by_id:
        terminal_ids.append(aggregator_id)
    for edge in edges:
        source_id = str(getattr(edge, "source_id", "") or "").strip()
        target_id = str(getattr(edge, "target_id", "") or "").strip()
        kind = str(getattr(edge, "kind", "") or "").strip()
        if kind == "produced" and target_id == run.orchestrator_participant_id and source_id in successful_by_id:
            terminal_ids.append(source_id)
    return list(dict.fromkeys(terminal_ids))


def _participant_final_text(result: ParticipantExecutionResult) -> str:
    return str(result.output_text or result.summary or "").strip()


def _runtime_output_text(events: list[Any]) -> str:
    final_text = ""
    for event in events:
        payload = getattr(event, "payload", {})
        if not isinstance(payload, dict):
            continue
        if getattr(event, "event_type", "") != "runtime.output.final":
            continue
        complete_text = payload.get("complete_text")
        text = payload.get("text")
        if isinstance(complete_text, str) and complete_text.strip():
            text = complete_text
        if isinstance(text, str) and text.strip():
            final_text = text
    return final_text.strip()


def _runtime_partial_output_text(events: list[Any]) -> str:
    deltas: list[str] = []
    for event in events:
        payload = getattr(event, "payload", {})
        if not isinstance(payload, dict):
            continue
        if getattr(event, "event_type", "") == "runtime.output.delta" and isinstance(payload.get("text"), str):
            deltas.append(payload["text"])
    return "".join(deltas).strip()


def _runtime_participant_summary(
    label: str,
    status: str,
    *,
    output_text: str,
    error: str | None = None,
) -> str:
    summary = _compact_summary(output_text)
    if summary:
        return summary
    if status == "completed":
        return f"{label} completed without a final answer."
    if status == "cancelled":
        return f"{label} cancelled."
    error_text = _compact_summary(error or "")
    if error_text:
        return f"{label} failed: {error_text}"
    return f"{label} failed before producing a final answer."


def _runtime_artifact_refs(events: list[Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for event in events:
        payload = getattr(event, "payload", {})
        if not isinstance(payload, dict):
            continue
        for key in ("artifact_refs", "artifacts"):
            value = payload.get(key)
            if isinstance(value, list):
                refs.extend(dict(item) for item in value if isinstance(item, dict))
    return refs


def _compact_summary(value: str, *, max_chars: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 3].rstrip()}..."


def _plural(count: int, singular: str) -> str:
    if count == 1:
        return f"1 {singular}"
    return f"{count} {singular}s"


def _max_concurrent_participants(service: InterAgentService, run: InterAgentRunRecord) -> int:
    policy = service.store.get_budget_policy(run.budget_policy_id, workspace_id=run.workspace_id)
    return max(1, int(policy.max_concurrent_participants))


def _participant_spawn_reservation_id(participant_id: str) -> str:
    return f"spawn:{participant_id}"


def _clock(fixed_start: datetime | None):
    lock = Lock()
    counter = 0
    base = fixed_start or datetime.now(tz=UTC)

    def tick() -> datetime:
        nonlocal counter
        if fixed_start is None:
            return datetime.now(tz=UTC)
        with lock:
            value = base + timedelta(microseconds=counter)
            counter += 1
            return value

    return tick
