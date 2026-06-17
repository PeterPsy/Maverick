"""Native MVP executor for core-owned inter-agent runs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any
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
    now: datetime | None = None,
) -> InterAgentExecutionResult:
    """Execute one F3-native inter-agent run without external adapters."""
    clock = _clock(now)
    run = service.store.get_run(run_id, workspace_id=workspace_id)
    if run.status in TERMINAL_RUN_STATUSES:
        return InterAgentExecutionResult(run=run, participant_results=[], root_runtime_events=[])
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
                clock=clock,
            )
    except Exception as error:
        failed_at = clock()
        latest_run = service.store.get_run(run.run_id, workspace_id=workspace_id)
        failed = replace(latest_run, status="failed", updated_at=failed_at, ended_at=failed_at)
        service.store.save_run(failed)
        service.record_event(
            failed,
            event_type="inter_agent.run.failed",
            participant_id=orchestrator.participant_id,
            visibility_plane="summary",
            correlation_id=failed.run_id,
            idempotency_key=f"{failed.run_id}:executor.run.failed",
            payload={"error": str(error), "status": "failed"},
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

    final_status = "failed" if any(result.status == "failed" for result in participant_results) else "completed"
    final_summary = _final_summary(final_status=final_status, participant_results=participant_results)
    final_synthetic, final_synthetic_source = _result_synthetic_metadata(participant_results)
    ended_at = clock()
    latest_run = service.store.get_run(run.run_id, workspace_id=workspace_id)
    completed_run = replace(latest_run, status=final_status, updated_at=ended_at, ended_at=ended_at)
    service.store.save_run(completed_run)
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
            "synthetic": final_synthetic,
            "synthetic_source": final_synthetic_source,
        },
        now=ended_at,
    )
    service.record_event(
        completed_run,
        event_type="inter_agent.run.completed" if final_status == "completed" else "inter_agent.run.failed",
        participant_id=orchestrator.participant_id,
        visibility_plane="summary",
        correlation_id=completed_run.run_id,
        idempotency_key=f"{completed_run.run_id}:executor.run.{final_status}",
        payload={
            "summary": final_summary,
            "status": final_status,
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
            input_text=_participant_input(
                participant,
                base_input=input_text,
                participant_inputs=participant_inputs,
            ),
            controlled=controlled_participants.get(participant.participant_id),
            allow_synthetic_participants=allow_synthetic_participants,
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
    clock,
) -> ParticipantExecutionResult:
    runtime_session_id: str | None = None
    try:
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
            async_requested=False,
            now=clock(),
        )
    except Exception as error:
        latest = service.store.get_participant(participant.participant_id, workspace_id=run.workspace_id, run_id=run.run_id)
        if latest.runtime_session_id:
            runtime_session_id = latest.runtime_session_id
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
    output_text = _runtime_output_text(events)
    artifact_refs = _runtime_artifact_refs(events)
    status = "completed" if turn.status == "completed" else "failed"
    if status == "failed" and (artifact_refs or output_text):
        _record_artifacts(
            service,
            run,
            participant=participant,
            task_id=task_id,
            artifact_refs=artifact_refs,
            partial_output=output_text,
            synthetic=False,
            synthetic_source=None,
            clock=clock,
        )
    summary = _compact_summary(output_text) or f"{participant.label} {status}."
    _finish_participant(
        service,
        run,
        participant=service.store.get_participant(participant.participant_id, workspace_id=run.workspace_id, run_id=run.run_id),
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
        partial_output=output_text if status == "failed" else "",
        artifact_refs=artifact_refs,
        error=turn.failure_reason,
        runtime_session_id=session.session_id,
        runtime_turn_id=turn.turn_id,
    )


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


def _participant_input(
    participant: InterAgentParticipantRecord,
    *,
    base_input: str,
    participant_inputs: dict[str, str],
    previous_output: str = "",
) -> str:
    specific = participant_inputs.get(participant.participant_id, "").strip()
    text = specific or str(base_input or "").strip()
    if previous_output:
        suffix = f"Previous participant output:\n{previous_output}"
        text = f"{text}\n\n{suffix}" if text else suffix
    return text or f"Execute the assigned task for {participant.label}."


def _merge_input_for_aggregator(*, input_text: str, fanout_results: list[ParticipantExecutionResult]) -> str:
    sections = [str(input_text or "").strip()] if str(input_text or "").strip() else []
    for result in fanout_results:
        sections.append(f"{result.label}: {result.summary or result.output_text or result.status}")
    return "\n\n".join(sections)


def _plan_summary(run: InterAgentRunRecord, participants: list[InterAgentParticipantRecord]) -> str:
    work_count = len(_work_participants(run, participants))
    if run.mode == "concurrent":
        return f"Orchestrator started a concurrent multi-agent run with {work_count} participant(s)."
    if run.mode == "sequential":
        return f"Orchestrator started a sequential multi-agent run with {work_count} participant(s)."
    return f"Orchestrator started manager-tools mode with {work_count} participant(s)."


def _final_summary(*, final_status: str, participant_results: list[ParticipantExecutionResult]) -> str:
    if not participant_results:
        return "Multi-agent run completed without participant work."
    prefix = "Multi-agent run completed." if final_status == "completed" else "Multi-agent run failed."
    summaries = []
    for result in participant_results:
        text = result.summary or result.output_text or result.partial_output or result.error or result.status
        summaries.append(f"{result.label}: {_compact_summary(text)}")
    return f"{prefix} " + " ".join(summaries)


def _runtime_output_text(events: list[Any]) -> str:
    final_text = ""
    deltas: list[str] = []
    for event in events:
        payload = getattr(event, "payload", {})
        if not isinstance(payload, dict):
            continue
        if getattr(event, "event_type", "") == "runtime.output.final" and isinstance(payload.get("text"), str):
            final_text = payload["text"]
        elif getattr(event, "event_type", "") == "runtime.output.delta" and isinstance(payload.get("text"), str):
            deltas.append(payload["text"])
    return (final_text or "".join(deltas)).strip()


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
