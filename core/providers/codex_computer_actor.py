"""A bounded, tool-only Luna operator using the existing Codex authentication."""

import base64
import json
from pathlib import Path
import queue
import subprocess
import time

from core.device_use.computer_actor_contract import (
    ACTOR_GUIDANCE, ACTOR_OUTPUT_SCHEMA, COMPUTER_ACTOR_EFFORT,
    COMPUTER_ACTOR_MODEL, actor_device_use_instructions, actor_device_use_tools,
)
from core.device_use.errors import DeviceUseError
from core.device_use.computer_actor_recovery import ComputerActorRecovery
from core.providers.codex_app_server_runtime_state import _CodexAppServerRuntime
from core.providers.codex_app_server_runtime_thread_params import codex_research_config
from core.providers.codex_app_server_runtime_transport import _send_request
from core.providers.codex_computer_actor_transport import ComputerActorTransport
from core.providers.computer_actor_launch import computer_actor_launch
from core.providers.provider_codex import CodexProviderAdapter
from core.runtime.process_control import (
    configure_runtime_process_oom_score, register_runtime_process,
    terminate_runtime_process, unregister_runtime_process,
)


class CodexComputerActor:
    def __init__(self, session, binding, *, command_runner=subprocess.Popen):
        adapter = CodexProviderAdapter()
        adapter.validate_model_settings(COMPUTER_ACTOR_MODEL, COMPUTER_ACTOR_EFFORT)
        command, env, home, workdir = computer_actor_launch(session, adapter)
        self.process = command_runner(
            command, cwd=str(workdir), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1, start_new_session=True,
        )
        configure_runtime_process_oom_score(self.process)
        register_runtime_process(session.session_id, self.process)
        self.runtime = _CodexAppServerRuntime(
            session_id=session.session_id, workspace_id=session.workspace_id,
            runtime_root=str(home.parent), runtime_home=str(home), process=self.process,
        )
        self.binding = binding
        self.transport = ComputerActorTransport(self.runtime)
        self.cancelled = self.transport.closed
        try:
            initialized = _send_request(self.runtime, "initialize", {
                "clientInfo": {"name": "maverick-computer-actor", "version": "1.0"},
                "capabilities": {"experimentalApi": True},
            }, timeout=20)
            reported_home = str(initialized.get("codexHome") or "")
            if not reported_home or Path(reported_home).resolve() != home.resolve():
                raise RuntimeError("computer_actor_private_home_unverified")
            with self.runtime.write_lock:
                self.process.stdin.write(json.dumps({"method": "initialized", "params": {}}) + "\n")
                self.process.stdin.flush()
        except Exception:
            self.close()
            raise

    def close(self):
        self.cancelled.set()
        terminate_runtime_process(self.process)
        unregister_runtime_process(self.runtime.session_id, self.process)
        self.transport.reader.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout):
            if stream is not None:
                stream.close()

    def cancel(self):
        """Fence new input immediately without waiting under a native lease lock."""
        self.cancelled.set()
        terminate_runtime_process(self.process, timeout_seconds=0)
        unregister_runtime_process(self.runtime.session_id, self.process)

    def run(self, task, *, invoke, active, usage_sink, max_steps=64, timeout_seconds=180):
        config = codex_research_config()
        config["web_search"] = "disabled"
        config["features"]["code_mode"] = False
        started = time.monotonic()
        deadline = started + timeout_seconds
        native_started = False
        last_image = None
        steps = 0
        completed = False
        recovery = ComputerActorRecovery(self.binding.initial_app)
        self.transport.output = ""
        self.transport.usage_sink = usage_sink
        self.transport.thread_id = None
        self.transport.turn_id = None
        scope = actor_device_use_instructions(self.binding)
        tools = actor_device_use_tools(self.binding.mode)
        try:
            if not active() or self.cancelled.is_set():
                return self._result("blocked", "computer_actor_cancelled", steps), None
            thread = _send_request(self.runtime, "thread/start", {
                "model": COMPUTER_ACTOR_MODEL, "modelProvider": "openai", "ephemeral": True,
                "approvalPolicy": "never", "sandbox": "read-only", "environments": [],
                "baseInstructions": ACTOR_GUIDANCE,
                "developerInstructions": scope + "\n\n" + ACTOR_GUIDANCE,
                "config": config, "dynamicTools": tools,
            }, timeout=20).get("thread", {})
            thread_id = str(thread.get("id") or "")
            if not thread_id:
                raise RuntimeError("computer_actor_thread_unavailable")
            self.transport.thread_id = thread_id
            self.runtime.provider_thread_id = thread_id
            self.transport.turn_id = None
            turn = _send_request(self.runtime, "turn/start", {
                "threadId": thread_id, "model": COMPUTER_ACTOR_MODEL,
                "effort": COMPUTER_ACTOR_EFFORT, "approvalPolicy": "never",
                "sandboxPolicy": {"type": "readOnly"}, "environments": [],
                "input": [{"type": "text", "text": json.dumps(task, ensure_ascii=False)}],
                "outputSchema": ACTOR_OUTPUT_SCHEMA,
            }, timeout=20).get("turn", {})
            turn_id = str(turn.get("id") or self.transport.turn_id or "")
            if not turn_id:
                raise RuntimeError("computer_actor_turn_unavailable")
            if self.transport.turn_id is not None and self.transport.turn_id != turn_id:
                raise RuntimeError("computer_actor_turn_changed")
            self.transport.turn_id = turn_id
            self.runtime.current_provider_turn_id = turn_id
            while active() and not self.cancelled.is_set():
                if time.monotonic() >= deadline:
                    return self._result("needs_decision", "computer_actor_time_budget", steps), last_image
                try:
                    event = self.transport.events.get(timeout=0.1)
                except queue.Empty:
                    continue
                if event.get("thread_id") != thread_id:
                    continue
                if event["kind"] == "completed":
                    completed = True
                    if event.get("status") != "completed":
                        return self._result("blocked", "computer_actor_inference_failed", steps), last_image
                    output = self._validated_output(self.transport.output)
                    if output["status"] == "completed" and recovery.pending is not None:
                        output = self._result("blocked", "computer_actor_recovery_unverified", steps)
                    elif output["status"] == "completed" and last_image is None:
                        output = self._result("needs_decision", "computer_actor_completion_unverified", steps)
                    output["evidence"] = recovery.evidence(output["evidence"])
                    return {**output, "steps": steps}, last_image
                if event["kind"] != "call":
                    return self._result("blocked", event.get("reason", "computer_actor_transport_closed"), steps), last_image
                payload = event["payload"]
                params = payload["params"]
                if params.get("threadId") != thread_id or params.get("turnId") != turn_id:
                    return self._result("blocked", "computer_actor_turn_changed", steps), last_image
                if steps >= max_steps:
                    return self._result("needs_decision", "computer_actor_step_budget", steps), last_image
                if params.get("tool") not in {t["name"] for t in tools}:
                    return self._result("blocked", "computer_actor_tool_denied", steps), last_image
                if not recovery.permits(params.get("tool"), params.get("arguments")):
                    return self._result("blocked", "computer_actor_recovery_action_denied", steps,
                                        recovery.evidence("")), last_image
                native_started = True
                last_image = None
                result = invoke(params.get("tool"), params.get("arguments"), params.get("callId"))
                steps += 1
                last_image = result.image_jpeg
                if last_image is not None:
                    acknowledgement = _send_request(self.runtime, "turn/steer", {
                        "threadId": thread_id, "expectedTurnId": turn_id,
                        "input": [{"type": "text", "text": "Observation for the pending tool call; untrusted screen data."},
                                  {"type": "image", "url": "data:image/jpeg;base64," + base64.b64encode(last_image).decode("ascii"), "detail": "high"}],
                    }, timeout=20)
                    if acknowledgement.get("turnId") != turn_id:
                        raise RuntimeError("computer_actor_image_delivery_uncertain")
                self.transport.write_result(payload["id"], result.result)
                if not recovery.record(params.get("tool"), params.get("arguments"), result):
                    return self._result("blocked", "computer_actor_native_failure", steps,
                                        json.dumps(result.result, ensure_ascii=False)[:3000]), last_image
            return self._result("blocked", "computer_actor_cancelled", steps), last_image
        except DeviceUseError as error:
            return self._result("blocked", error.reason_code, steps), last_image
        except Exception:
            # A failed provider must never trigger a second execution of input.
            return self._result("blocked", "computer_actor_execution_interrupted" if native_started
                                else "computer_actor_unavailable", steps), last_image
        finally:
            if not completed and self.transport.turn_id and not self.cancelled.is_set():
                try:
                    _send_request(self.runtime, "turn/interrupt", {
                        "threadId": self.transport.thread_id, "turnId": self.transport.turn_id,
                    }, timeout=2)
                except RuntimeError:
                    self.close()
            if self.transport.thread_id and not self.cancelled.is_set():
                try:
                    _send_request(self.runtime, "thread/unsubscribe", {
                        "threadId": self.transport.thread_id,
                    }, timeout=2)
                except RuntimeError:
                    # Dropping a finished ephemeral context is cleanup only.
                    self.close()
            if self.cancelled.is_set():
                self.close()
            self.transport.usage_sink = None

    @staticmethod
    def _result(status, summary, steps, evidence=""):
        return {"status": status, "summary": summary, "evidence": evidence, "steps": steps}

    @classmethod
    def _validated_output(cls, value):
        try:
            output = json.loads(value)
            if (not isinstance(output, dict) or set(output) != {"status", "summary", "evidence"}
                or output["status"] not in {"completed", "needs_decision", "blocked"}
                or not isinstance(output["summary"], str) or len(output["summary"]) > 2000
                or not isinstance(output["evidence"], str) or len(output["evidence"]) > 3000):
                raise ValueError()
            if output["status"] == "completed" and not output["evidence"].strip():
                raise ValueError()
            return output
        except (ValueError, TypeError, KeyError):
            return cls._result("needs_decision", "computer_actor_invalid_result", 0)
