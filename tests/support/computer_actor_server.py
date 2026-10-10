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
    actions = ["observe_app", "click", "observe_app"]
    if mode.startswith("browser-close"):
        actions = ["observe", "close_tab", "list_tabs"]
    elif mode.startswith("browser-"):
        actions = ["observe", "keypress", "observe", "scroll", "observe"]
        if mode == "browser-replay":
            actions[3] = "keypress"
    elif mode in {"refresh", "refresh-no-list"}:
        actions = ["observe_app", "list_windows", "observe", "click", "observe_app"]
        if mode == "refresh-no-list":
            actions.pop(1)
    elif mode.startswith("uncertain-replay") or mode in {"uncertain-other-app", "uncertain-other-engine", "uncertain-no-image"}:
        actions = ["observe_app", "click", "observe_app", "click", "observe_app"]
        if mode in {"uncertain-other-app", "uncertain-other-engine"}:
            actions = ["observe_app", "click", "observe_app"]
    if step >= len(actions):
        evidence = "Native tab inventory excludes the closed tab." if mode.startswith("browser-close") else "Latest screen shows the target."
        output = {"status": "completed", "summary": "Subtask complete", "evidence": evidence}
        if mode == "invalid":
            output["status"] = "invented"
        notify("item/completed", {"turnId": turn_id, "item": {
            "type": "agentMessage", "text": json.dumps(output), "id": "private-final"}})
        usage = emit_usage()
        notify("turn/completed", {"turn": {"id": turn_id, "status": "completed", "tokenUsage": usage}})
        return
    action = actions[step]
    tool = "mac_code" if mode == "forbidden" else "mac_peekaboo"
    bundle = "com.apple.Safari"
    if mode == "uncertain-other-app" and step == 2:
        bundle = "com.apple.Notes"
    if mode == "uncertain-other-engine" and step == 2:
        tool, action = "mac_computer", "observe"
    arguments = {"action": action, "bundle_id": bundle, "snapshot": "snapshot-" + str(step)}
    if mode.startswith("browser-"):
        tool = "mac_browser"
        arguments = {"action": action, "tab_id": "other" if mode == "browser-other-tab" and step == 2 else "test-tab",
                     "observation_id": "receipt-" + str(step)}
        if action == "keypress":
            arguments.update(key="Return", observe_after=step == 3)
            if step == 3:
                arguments["shift"] = False
        if action == "scroll":
            arguments.update(direction="down", amount=300)
    if action == "click":
        arguments["element"] = "B1"
    if step == 3:
        if mode == "uncertain-replay-details":
            arguments["details"] = True
        elif mode == "uncertain-replay-image-size":
            arguments["image_max_dimension"] = 3840
        elif mode == "uncertain-replay-observation-options":
            arguments.update(details=False, image_max_dimension=640, observe_after=True)
    send({"id": "native-" + str(step), "method": "item/tool/call", "params": {
        "threadId": thread_id, "turnId": turn_id, "callId": "call-" + str(step),
        "tool": tool, "arguments": arguments}})
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
