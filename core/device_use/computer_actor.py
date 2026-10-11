"""Parent-authorized UI delegation with no second user-visible session."""

import hashlib
import json
import threading
import time
from dataclasses import replace
from uuid import uuid4

from core.device_use.computer_actor_contract import UI_TOOLS, validate_actor_task
from core.device_use.errors import DeviceUseAuthorizationError, DeviceUseUnavailableError
from core.device_use.models import DeviceUseResult
from core.device_use.computer_task_execution import execute_computer_task
from core.providers.computer_actor_factory import create_computer_actor
from core.providers.computer_actor_settings import computer_actor_selection
from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.turn_submission_service_output_text import _RuntimeTurnOutputRecorder


class ComputerInteraction:
    def __init__(self, state, session_id, activation_id, *, workspace_id=None, client_factory=create_computer_actor):
        self.state = state
        self.session_id = session_id
        self.activation_id = activation_id
        self.client_factory = client_factory
        self.lock = threading.Lock()
        self.client = None
        self.selection_key = None
        self.cancelled = threading.Event()
        self.cancellation_lock = threading.Lock()
        # New-session registration precedes persistence. Pin from the verified
        # binding's workspace instead of reading an as-yet nonexistent session.
        if workspace_id is None:
            workspace_id = state.runtime_store.get_session(session_id).workspace_id
        self.execution_mode = computer_actor_selection(
            getattr(state, "provider_store", None), workspace_id).execution_mode

    def cancel(self, *, close=False):
        with self.cancellation_lock:
            self.cancelled.set()
            client = self.client
        if client is not None and (close or self.lock.locked()):
            client.cancel()

    def run(self, *, binding, turn_id, provider_thread_id, provider_turn_id,
            call_id, task_text, arguments, authority_active=None):
        try:
            task = validate_actor_task(arguments)
        except ValueError as error:
            raise DeviceUseUnavailableError(str(error)) from error
        if binding.activation_id != self.activation_id:
            raise DeviceUseAuthorizationError("computer_actor_activation_changed")
        if not self.lock.acquire(blocking=False):
            raise DeviceUseUnavailableError("computer_actor_busy")
        with self.cancellation_lock:
            cancelled = self.cancelled = threading.Event()
        recorder = _RuntimeTurnOutputRecorder(self.state, session_id=self.session_id, turn_id=turn_id)
        durations = []
        user_waits = []
        task_started = time.monotonic()
        deadline = task_started + 180
        try:
            session = self.state.runtime_store.get_session(self.session_id)
            service = self.state.device_use_service
            if authority_active is None:
                task_text = self.state.runtime_store.get_turn(turn_id).input_text or ""

            def active():
                if cancelled.is_set() or not service.binding_connected(binding, self.session_id):
                    return False
                if authority_active is not None and not authority_active():
                    return False
                current = self.state.runtime_store.get_session(self.session_id)
                turn = self.state.runtime_store.get_turn(turn_id)
                runtime_state = self.state.runtime_store.get_state(self.session_id)
                return (current.device_use_binding == binding
                        and current.status == "running"
                        and current.workspace_id == binding.workspace_id
                        and current.owner_user_id == binding.owner_user_id
                        and turn.session_id == self.session_id
                        and turn.status == "active"
                        and getattr(turn, "cancellation_requested_at", None) is None
                        and runtime_state.current_turn_id == turn_id)

            if not active():
                raise DeviceUseAuthorizationError("computer_actor_parent_not_active")
            selection = computer_actor_selection(getattr(self.state, "provider_store", None), session.workspace_id)
            selection_key = (selection.provider_id, selection.model_id, selection.reasoning_effort)
            if self.client is None or self.client.cancelled.is_set() or self.selection_key != selection_key:
                if self.client is not None:
                    self.client.close()
                try:
                    self.client = self.client_factory(session, binding, selection=selection)
                    self.selection_key = selection_key
                except Exception as error:
                    raise DeviceUseUnavailableError("computer_actor_unavailable") from error
            task_call_prefix = "actor_" + uuid4().hex

            def invoke(tool_name, native_arguments, actor_call_id):
                if (tool_name not in UI_TOOLS or not isinstance(native_arguments, dict)
                    or not isinstance(actor_call_id, str) or not actor_call_id):
                    raise DeviceUseAuthorizationError("computer_actor_tool_denied")
                if not active():
                    raise DeviceUseAuthorizationError("computer_actor_parent_changed")
                if ("text" in native_arguments
                    and native_arguments["text"] not in task["prepared_text"]):
                    raise DeviceUseAuthorizationError("computer_actor_unprepared_text")
                # Keep the exact parent identity and original user task at the
                # native boundary. No child session receives its lease/token.
                result = service.invoke(
                    binding=binding, runtime_session_id=self.session_id, turn_id=turn_id,
                    provider_thread_id=provider_thread_id, provider_turn_id=provider_turn_id,
                    call_id=task_call_prefix + "_" + str(actor_call_id or uuid4().hex)[:80],
                    tool_name=tool_name, arguments=native_arguments, task_text=task_text,
                    timeout_seconds=max(0.1, deadline - time.monotonic()),
                )
                durations.append(result.native_duration_ms)
                user_waits.append(result.native_user_wait_ms)
                return result

            fallback_model = getattr(selection, 'fallback_model_id', None)
            def fallback_factory():
                return self.client_factory(session, binding, selection=replace(selection,
                    model_id=fallback_model, reasoning_effort=selection.fallback_reasoning_effort,
                    fallback_model_id=None, fallback_reasoning_effort=None))

            output, jpeg = execute_computer_task(self.client, task, binding=binding, invoke=invoke, active=active,
                fallback_factory=fallback_factory if fallback_model else None,
                timeout_seconds=max(0.01, deadline - time.monotonic()),
                usage_sink=lambda payload: recorder.record(RuntimeExecutionEvent(
                    event_type="runtime.usage.reported", payload=payload)))
            output['task_elapsed_ms'] = round((time.monotonic() - task_started) * 1000, 3)
            if not active():
                output = {"status": "blocked", "summary": "computer_actor_parent_changed",
                          "evidence": "", "steps": output.get("steps", 0)}
                jpeg = None
            result = {"success": output["status"] != "blocked",
                      "contentItems": [{"type": "inputText", "text": json.dumps(output, ensure_ascii=False)}]}
            return DeviceUseResult(
                invocation_id="computer_interact_" + uuid4().hex, call_id=call_id,
                result=result, image_jpeg=jpeg,
                image_sha256=hashlib.sha256(jpeg).hexdigest() if jpeg else None,
                native_duration_ms=sum(durations) if durations and all(value is not None for value in durations) else None,
                native_user_wait_ms=sum(user_waits) if user_waits and all(value is not None for value in user_waits) else None,
            )
        finally:
            recorder.flush_usage()
            self.lock.release()
