"""Executable ACP fixture: exercises real pipes, cancellation and process cleanup."""

import json
import os
from pathlib import Path
import subprocess
import sys

if "--version" in sys.argv:
    print("Gemini CLI fixture")
    raise SystemExit(0)

trace = Path(os.environ["ACP_FIXTURE_TRACE"])
pending = None
permission_pending = None
session_id = "fixture-session"


def send(payload):
    print(json.dumps({"jsonrpc": "2.0", **payload}), flush=True)


def update(kind, **payload):
    send({"method": "session/update", "params": {
        "sessionId": session_id, "update": {"sessionUpdate": kind, **payload},
    }})


for line in sys.stdin:
    message = json.loads(line)
    with trace.open("a") as stream:
        stream.write(json.dumps(message) + "\n")
    method, params = message.get("method"), message.get("params", {})
    request_id = message.get("id")
    if method == "initialize":
        if not os.environ.get("ACP_FIXTURE_HOLD_INIT"):
            send({"id": request_id, "result": {"protocolVersion": 1, "agentCapabilities": {"loadSession": True}}})
    elif method == "session/new":
        send({"id": request_id, "result": {"sessionId": session_id}})
    elif method == "session/load":
        update("agent_message_chunk", content={"type": "text", "text": "history-replay"})
        send({"id": request_id, "result": None})
    elif method == "session/cancel":
        if pending is not None:
            send({"id": pending, "result": {"stopReason": "cancelled"}})
            pending = None
    elif method == "session/prompt":
        if pending is not None:
            send({"id": pending, "result": {"stopReason": "cancelled"}})
            pending = None
        text = params["prompt"][0]["text"]
        if text == "malformed":
            print("human terminal text is not ACP", flush=True)
        elif text in {"hold", "fork"}:
            if text == "fork":
                child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
                trace.with_suffix(".pid").write_text(str(child.pid))
            pending = request_id
            update("agent_message_chunk", content={"type": "text", "text": "waiting"})
        elif text == "escape":
            update("tool_call", toolCallId="outside", locations=[{"path": "/outside-workspace"}])
            send({"id": request_id, "result": {"stopReason": "end_turn"}})
        elif text == "empty":
            send({"id": request_id, "result": {"stopReason": "end_turn"}})
        elif text == "permission":
            permission_pending = request_id
            update("tool_call", toolCallId="permission", status="pending", locations=[])
            send({"id": "permission", "method": "session/request_permission", "params": {
                "sessionId": session_id, "options": [{"optionId": "allow", "kind": "allow_once"}],
            }})
        else:
            update("agent_message_chunk", content={"type": "text", "text": "answer:"})
            update("agent_message_chunk", content={"type": "text", "text": text})
            send({"id": request_id, "result": {"stopReason": "end_turn"}})
    elif request_id == "permission":
        assert message["result"]["outcome"]["outcome"] == "cancelled"
        update("tool_call_update", toolCallId="permission", status="failed", locations=[])
        update("agent_message_chunk", content={"type": "text", "text": "Permission denied"})
        send({"id": permission_pending, "result": {"stopReason": "end_turn"}})
