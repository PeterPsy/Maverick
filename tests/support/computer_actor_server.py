"""Deterministic app-server peer for operator protocol tests only."""

import json
import os
import sys


thread_id = ""
turn_id = ""
mode = ""
step = 0
sequence = 0


def send(value):
    print(json.dumps(value), flush=True)


def notify(method, params):
    send({"method": method, "params": {"threadId": thread_id, **params}})


def emit_usage():
    usage = {"total": {"inputTokens": 180, "cachedInputTokens": 80, "outputTokens": 20,
                       "reasoningOutputTokens": 5, "totalTokens": 200},
             "last": {"inputTokens": 180, "cachedInputTokens": 80, "outputTokens": 20,
                      "reasoningOutputTokens": 5, "totalTokens": 200}, "modelContextWindow": 258400}
    notify("thread/tokenUsage/updated", {"turnId": turn_id, "tokenUsage": usage})
    return usage


def next_call():
    global step
    if step >= 3:
        output = {"status": "completed", "summary": "Subtask complete", "evidence": "Latest screen shows the target."}
        if mode == "invalid":
            output["status"] = "invented"
        notify("item/completed", {"turnId": turn_id, "item": {
            "type": "agentMessage", "text": json.dumps(output), "id": "private-final"}})
        usage = emit_usage()
        notify("turn/completed", {"turn": {"id": turn_id, "status": "completed", "tokenUsage": usage}})
        return
    action = "click" if step == 1 else "observe_app"
    tool = "mac_code" if mode == "forbidden" else "mac_peekaboo"
    send({"id": "native-" + str(step), "method": "item/tool/call", "params": {
        "threadId": thread_id, "turnId": turn_id, "callId": "call-" + str(step),
        "tool": tool, "arguments": {"action": action, "bundle_id": "com.apple.Safari"}}})
    step += 1


for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    params = request.get("params", {})
    if method == "initialized":
        continue
    result = {}
    if method == "initialize":
        result = {"codexHome": os.environ["CODEX_HOME"]}
    elif method == "thread/start":
        assert params["model"] == "gpt-6-luna"
        assert params["config"]["features"]["shell_tool"] is False
        assert params["config"]["mcp_servers"] == {}
        sequence += 1
        thread_id = "operator-thread-" + str(sequence)
        result = {"thread": {"id": thread_id}}
    elif method == "turn/start":
        assert params["effort"] == "low"
        assert params["model"] == "gpt-6-luna"
        mode = json.loads(params["input"][0]["text"])["objective"]
        step = 0
        turn_id = "operator-turn-" + str(sequence)
        result = {"turn": {"id": turn_id}}
    elif method == "turn/steer":
        result = {"turnId": turn_id}
    send({"id": request.get("id"), "result": result})
    if method == "turn/interrupt":
        usage = emit_usage()
        notify("turn/completed", {"turn": {"id": turn_id, "status": "interrupted", "tokenUsage": usage}})
    elif method == "turn/start":
        notify("turn/started", {"turn": {"id": turn_id}})
        notify("item/agentMessage/delta", {"turnId": turn_id, "delta": "PRIVATE_ACTOR_COMMENTARY"})
        if mode != "wait":
            next_call()
    elif method is None and str(request.get("id", "")).startswith("native-"):
        next_call()
