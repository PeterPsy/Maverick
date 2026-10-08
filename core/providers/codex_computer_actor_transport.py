"""Private Codex protocol reader; operator messages never reach Chat."""

import json
import queue
import threading

from core.providers.codex_app_server_runtime_usage import codex_usage_event


class ComputerActorTransport:
    def __init__(self, runtime):
        self.runtime = runtime
        self.events = queue.Queue(maxsize=128)
        self.closed = threading.Event()
        self.thread_id = None
        self.turn_id = None
        self.usage_sink = None
        self.output = ""
        self.reader = threading.Thread(target=self._read, daemon=True,
                                       name=f"computer-actor-{runtime.session_id}")
        self.reader.start()

    def write_result(self, request_id, result):
        with self.runtime.write_lock:
            self.runtime.process.stdin.write(json.dumps({
                "jsonrpc": "2.0", "id": request_id, "result": result,
            }) + "\n")
            self.runtime.process.stdin.flush()

    def _queue(self, event):
        event.setdefault("thread_id", self.thread_id)
        try:
            self.events.put_nowait(event)
        except queue.Full:
            self.closed.set()

    def _read(self):
        try:
            for line in self.runtime.process.stdout:
                try:
                    payload = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(payload, dict):
                    continue
                if "id" in payload and "method" not in payload:
                    with self.runtime.request_lock:
                        waiter = self.runtime.response_waiters.pop(payload["id"], None)
                    if waiter is not None:
                        waiter.put_nowait(payload)
                    continue
                self.handle(payload)
        except (OSError, ValueError):
            pass
        finally:
            self.closed.set()
            with self.runtime.request_lock:
                waiters = list(self.runtime.response_waiters.values())
                self.runtime.response_waiters.clear()
            for waiter in waiters:
                try:
                    waiter.put_nowait({"_transport_error": "computer_actor_transport_closed"})
                except queue.Full:
                    pass
            self._queue({"kind": "closed"})
            with self.runtime.write_lock:
                for stream in (self.runtime.process.stdin, self.runtime.process.stdout):
                    if stream is not None:
                        stream.close()

    def handle(self, payload):
        method = payload.get("method")
        params = payload.get("params")
        if not isinstance(params, dict):
            return
        if params.get("threadId") != self.thread_id:
            # Unknown requests are rejected, never auto-approved by the host.
            if "id" in payload:
                self.write_result(payload["id"], {"success": False, "contentItems": [
                    {"type": "inputText", "text": "computer_actor_authority_mismatch"},
                ]})
            return
        if method == "turn/started":
            turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
            if self.turn_id is not None and turn.get("id") != self.turn_id:
                self._queue({"kind": "error", "reason": "computer_actor_turn_changed"})
                return
            self.turn_id = turn.get("id")
            self.runtime.current_provider_turn_id = self.turn_id
            return
        if method == "thread/tokenUsage/updated":
            self._usage(params)
            return
        if method == "turn/completed":
            turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
            if turn.get("id") != self.turn_id:
                return
            if isinstance(turn.get("tokenUsage"), dict):
                self._usage({"threadId": self.thread_id, "turnId": self.turn_id,
                             "tokenUsage": turn["tokenUsage"]})
            self._queue({"kind": "completed", "status": turn.get("status")})
            return
        if params.get("turnId") != self.turn_id:
            if "id" in payload:
                self.write_result(payload["id"], {"success": False, "contentItems": [
                    {"type": "inputText", "text": "computer_actor_turn_changed"}]})
            return
        if "id" in payload:
            if method == "item/tool/call":
                self._queue({"kind": "call", "payload": payload})
            else:
                self.write_result(payload["id"], {"action": "decline", "answers": {}})
                self._queue({"kind": "error", "reason": "computer_actor_unexpected_request"})
        elif method == "item/completed":
            item = params.get("item") if isinstance(params.get("item"), dict) else {}
            if item.get("type") in {"agentMessage", "AgentMessage"}:
                value = item.get("text")
                if isinstance(value, str):
                    self.output = value[:8000]
            elif item.get("type") not in {"dynamicToolCall", "reasoning", "userMessage", "contextCompaction"}:
                self._queue({"kind": "error", "reason": "computer_actor_disallowed_item"})
        elif method == "error" and not params.get("willRetry"):
            self._queue({"kind": "error", "reason": "computer_actor_inference_failed"})

    def _usage(self, params):
        if self.usage_sink is None:
            return
        event = codex_usage_event(self.runtime, params)
        if event is not None:
            self.usage_sink({**event.payload, "model_id": "gpt-6-luna",
                             "source": "codex_computer_actor:" + str(self.thread_id),
                             "usage_worker": "computer_actor", "context_tokens": None,
                             "context_window_tokens": None, "context_accuracy": "unavailable"})
