"""Natural loop worker: real composition and observations, no success synthesis."""

import asyncio
from dataclasses import dataclass
from pathlib import Path

from core.certification_lab.errors import LabAuthorizationError
from core.providers.agentic_adapter import RuntimeCloseContext
from core.runtime.agentic_execution import execute_agentic_runtime_turn
from core.runtime.authority import effective_authority_audit_payload
from core.runtime.authority_service import resolve_runtime_authority_snapshot
from core.runtime.provider_input_capture_context import capture_runtime_provider_input
from core.runtime.service import queue_runtime_turn, record_runtime_event, transition_runtime_turn


@dataclass(frozen=True)
class LabObservedTurn:
    result: object
    observation_refs: tuple[dict, ...]


class LabWorker:
    def __init__(self, *, state, session, adapter):
        from core.certification_lab.runtime_context import lab_authorization_for_state

        self.state, self.session, self.adapter = state, session, adapter
        self.lab = lab_authorization_for_state(state, session.execution_binding)
        if self.lab is None:
            raise LabAuthorizationError('lab_permit_required')
        self._running = False

    async def execute(self, *, turn_id: str, task: str) -> LabObservedTurn:
        if self._running:
            raise LabAuthorizationError('lab_worker_already_running')
        self.lab.validate_session(self.session)
        self._running = True
        evidence = self.lab.evidence
        cleanup_error = None
        result = None
        try:
            queue_runtime_turn(self.state.runtime_store, turn_id=turn_id, session_id=self.session.session_id,
                               input_text=task, workspace_store=self.state.workspace_store, lab_authorization=self.lab)
            captured = capture_runtime_provider_input(self.state, session=self.session, turn_id=turn_id,
                                                       input_text=task, app_references=None, attachments=None)
            evidence.record('captured_prompt_and_sources', captured)
            evidence.record('workspace_before', _workspace_observation(Path(self.session.workspace_root)))
            # Snapshot calculation can perform filesystem behavior validation;
            # it stays in the normal sync runtime bridge, never a permissive callback.
            authority = await asyncio.to_thread(resolve_runtime_authority_snapshot, self.state,
                                                 session=self.session, adapter=self.adapter, turn_id=turn_id)
            evidence.record('experimental_authority', effective_authority_audit_payload(authority))
            transition_runtime_turn(self.state.runtime_store, turn_id=turn_id, target_status='active')

            def observe(event):
                evidence.record('runtime_event', event)
                record_runtime_event(self.state.runtime_store, event_id=f'lab-{turn_id}-{len(trace)}',
                                     session_id=self.session.session_id, turn_id=turn_id,
                                     plane='runtime', event_type=event.event_type, payload=event.payload)
                trace.append(event)

            trace = []
            result = await execute_agentic_runtime_turn(
                session=self.session, provider_state=self.state.runtime_store.get_provider_state(self.session.session_id),
                adapter=self.adapter, input_text=captured.input_text, input_sources=captured.sources,
                correlation_id=turn_id, effective_authority=authority, event_sink=observe,
            )
            evidence.record('runtime_result', result)
            transition_runtime_turn(self.state.runtime_store, turn_id=turn_id,
                                    target_status='completed' if result.exit_code == 0 else 'failed')
        except BaseException as error:
            evidence.record('worker_error', {'type': type(error).__name__, 'reason_code': getattr(error, 'reason_code', None)})
            raise
        finally:
            try:
                cleanup = await self.adapter.close(RuntimeCloseContext(
                    self.session, self.session.execution_binding, self.state.runtime_store.get_provider_state(self.session.session_id),
                ))
                live = self.adapter.process_registry.live_process_count(session_id=self.session.session_id)
                evidence.record('cleanup', {'close_result': cleanup, 'live_process_count': live})
                if live:
                    raise LabAuthorizationError('lab_descendants_still_alive')
            except BaseException as error:
                cleanup_error = error
                evidence.record('cleanup_error', {'type': type(error).__name__, 'reason_code': getattr(error, 'reason_code', None)})
            try:
                evidence.record('workspace_after', _workspace_observation(Path(self.session.workspace_root)))
                evidence.record('budget_usage', self.lab.ledger.status())
            finally:
                self._running = False
            if cleanup_error is not None:
                raise cleanup_error
        # A returned result is an observation, not a behavioral check, a review
        # approval, a signed certificate or production release authorization.
        return LabObservedTurn(result, evidence.observations())


def _workspace_observation(root):
    from core.runtime.confined_filesystem import ConfinedWorkspaceFilesystem

    filesystem = ConfinedWorkspaceFilesystem(workspace_id=root.name, workspace_root=root)
    result = []
    for path in sorted(root.rglob('*')):
        if path.is_relative_to(root / 'runtime') or not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        read = filesystem.read_bytes(relative, max_bytes=1_048_576)
        # The confined reader supplies exact observed identity/revision/digest.
        result.append({'path': relative, 'observation': read.payload})
        if len(result) > 1024:
            raise LabAuthorizationError('lab_observation_file_limit')
    return result
