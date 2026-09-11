"""Executable Antigravity stream-json fixture with real pipes and cleanup."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time


if "--version" in sys.argv:
    print("Antigravity CLI fixture 1.1.27")
    raise SystemExit(0)


def flag_value(name, default=None):
    try:
        return sys.argv[sys.argv.index(name) + 1]
    except (ValueError, IndexError):
        return default


trace = Path(os.environ["ANTIGRAVITY_FIXTURE_TRACE"])
conversation_id = flag_value("--conversation", "fixture-conversation")
model = flag_value("--model")
permission_mode = os.environ.get("ANTIGRAVITY_FIXTURE_PERMISSION", "proceed-in-sandbox")
turns = 0
step_index = 0
input_tokens = 0
output_tokens = 0
thinking_tokens = 0
cache_read_tokens = 0


def record(payload):
    with trace.open("a") as stream:
        stream.write(json.dumps(payload) + "\n")


def send(payload):
    print(json.dumps(payload, separators=(",", ":")), flush=True)


def step(step_type, state="DONE", **payload):
    global step_index
    send(
        {
            "event": "step_update",
            "step_update": {
                "conversation_id": conversation_id,
                "step_index": step_index,
                "state": state,
                "step_type": step_type,
                **payload,
            },
        }
    )
    if state == "DONE":
        step_index += 1


def usage():
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "thinking_tokens": thinking_tokens,
        "cache_read_tokens": cache_read_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def result(response, status="SUCCESS", error=None):
    payload = {
        "conversation_id": conversation_id,
        "status": status,
        "response": response,
        "duration_seconds": 0.01,
        "num_turns": turns,
        "usage": usage(),
    }
    if error is not None:
        payload["error"] = error
    send({"event": "result", "result": payload})


record({"startup": {"argv": sys.argv[1:], "cwd": os.getcwd()}})
if os.environ.get("ANTIGRAVITY_FIXTURE_HOLD_INIT"):
    time.sleep(60)
    raise SystemExit(1)
init_conversation = (
    "different-conversation"
    if os.environ.get("ANTIGRAVITY_FIXTURE_MISMATCH_RESUME")
    else conversation_id
)
send(
    {
        "event": "init",
        "conversation_id": init_conversation,
        "init": {
            "cwd": os.getcwd(),
            "tools": (
                ["ask_permission", "run_command"]
                if os.environ.get("ANTIGRAVITY_FIXTURE_MISSING_TOOL")
                else ["ask_permission", "run_command", "write_to_file"]
            ),
            "permission_mode": permission_mode,
            "model": model,
        },
    }
)


for line in sys.stdin:
    message = json.loads(line)
    record(message)
    text = message["message"]["content"]
    turns += 1
    previous_input = input_tokens
    input_tokens += 10 + len(text)
    cache_read_tokens += previous_input
    if text == "cache-heavy":
        # Antigravity reports cache reads independently from uncached input;
        # the live CLI can therefore report a larger cumulative cache count.
        cache_read_tokens += input_tokens * 2
    step("user_input")
    if text == "malformed":
        print("human terminal text is not stream-json", flush=True)
        time.sleep(60)
    elif text == "oversized":
        print("{" + "x" * 1_048_576, flush=True)
        time.sleep(60)
    elif text == "duplicate-init":
        send(
            {
                "event": "init",
                "conversation_id": conversation_id,
                "init": {
                    "cwd": os.getcwd(),
                    "tools": [],
                    "permission_mode": permission_mode,
                    "model": model,
                },
            }
        )
    elif text in {"hold", "fork"}:
        if text == "fork":
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            trace.with_suffix(".pid").write_text(str(child.pid))
        step("agent_response", state="ACTIVE", text_delta="waiting")
        time.sleep(60)
    elif text == "empty":
        result("")
    elif text == "error":
        result("", status="ERROR", error="fixture failure")
    elif text == "wrong-conversation":
        send(
            {
                "event": "step_update",
                "step_update": {
                    "conversation_id": "wrong",
                    "step_index": step_index,
                    "state": "DONE",
                    "step_type": "agent_response",
                    "text_delta": "wrong",
                },
            }
        )
    elif text == "mismatch-output":
        step("agent_response", text_delta="streamed")
        output_tokens += 2
        result("different")
    elif text == "tool":
        step(
            "tool",
            state="ACTIVE",
            tool_name="run_command",
            tool_info={
                "name": "run_command",
                "parameters": {"CommandLine": "printf fixture"},
            },
        )
        step(
            "tool",
            tool_name="run_command",
            tool_info={
                "name": "run_command",
                "parameters": {"CommandLine": "printf fixture"},
                "output": "fixture",
            },
        )
        step("agent_response", text_delta="tool:fixture")
        output_tokens += 2
        result("tool:fixture")
    elif text == "permission":
        step(
            "tool",
            tool_name="run_command",
            tool_info={
                "name": "run_command",
                "parameters": {"CommandLine": "sudo true"},
                "error": {"type": "permission_denied", "message": "soft denied"},
            },
        )
        step("agent_response", text_delta="Permission denied")
        output_tokens += 2
        result("Permission denied")
    elif text == "tool-error-state":
        step(
            "tool",
            state="ACTIVE",
            tool_name="run_command",
            tool_info={
                "name": "run_command",
                "parameters": {"CommandLine": "false"},
            },
        )
        step(
            "tool",
            state="ERROR",
            tool_name="run_command",
            tool_info={
                "name": "run_command",
                "parameters": {"CommandLine": "false"},
                "error": {"type": "TOOL_ERROR", "message": "fixture failure"},
            },
        )
        step("agent_response", text_delta="Tool failed safely")
        output_tokens += 2
        result("Tool failed safely")
    else:
        response = "answer:" + text
        step("agent_response", state="ACTIVE", text_delta="answer:")
        step("agent_response", text_delta=text)
        output_tokens += 2
        result(response)
