"""Normalize provider execution output into provider-agnostic runtime events."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable


@dataclass(frozen=True)
class RuntimeExecutionEvent:
    """Provider-agnostic progress event emitted while one turn executes."""

    event_type: str
    payload: dict[str, Any]
    plane: str = "turn"


RuntimeExecutionEventSink = Callable[[RuntimeExecutionEvent], None]

_NOISY_PROVIDER_EVENT_TOKENS = (
    "account ratelimits",
    "thread tokenusage",
    "thread status",
)


def is_internal_provider_noise(raw_value: str) -> bool:
    """Return true for provider lifecycle lines that must not become runtime events."""
    normalized = (
        raw_value.replace("\u001b", "")
        .replace("\u2026", "...")
        .replace("_", " ")
        .replace(".", " ")
        .strip()
        .lower()
    )
    normalized = " ".join(normalized.split())
    return (
        "reading additional input from stdin" in normalized
        or normalized
        in {
            "thread started",
            "thread completed",
            "turn started",
            "turn completed",
            "turn diff updated",
            "turn plan updated",
            "hook started",
            "hook completed",
            "item started",
            "item completed",
        }
        or any(token in normalized for token in _NOISY_PROVIDER_EVENT_TOKENS)
    )


def parse_provider_json_event(raw_line: str) -> RuntimeExecutionEvent | None:
    """Parse one provider JSONL line into a generic runtime event."""
    line = raw_line.strip()
    if not line:
        return None
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        if is_internal_provider_noise(line):
            return None
        return RuntimeExecutionEvent(event_type="runtime.output.delta", payload={"text": line, "source": "stdout"})
    if not isinstance(payload, dict):
        return RuntimeExecutionEvent(event_type="runtime.step.updated", payload={"label": "Runtime update", "raw": payload})

    event_type = str(payload.get("type") or payload.get("event_type") or "provider.event")
    item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
    if is_non_chat_facing_provider_event(event_type):
        return None
    tool_payload = _tool_payload(event_type=event_type, payload=payload, item=item)
    if tool_payload is not None:
        return tool_payload

    text = _text_from_payload(payload, item)
    if text:
        if is_internal_provider_noise(text):
            return None
        return RuntimeExecutionEvent(event_type="runtime.output.delta", payload={"text": text, "provider_event_type": event_type})

    label = _step_label(event_type=event_type, payload=payload, item=item)
    if is_internal_provider_noise(label) or is_internal_provider_noise(event_type):
        return None
    return RuntimeExecutionEvent(event_type="runtime.step.updated", payload={"label": label, "provider_event_type": event_type, "raw": _compact_raw(payload)})


def is_non_chat_facing_provider_event(event_type: str) -> bool:
    """Return true for provider deltas that are too noisy for chat-facing event history."""
    normalized = _normalize_provider_event_type(event_type)
    return normalized in {"item command execution output delta", "item command execution terminal interaction"}


def _normalize_provider_event_type(value: str) -> str:
    with_separators = "".join(f" {char.lower()}" if char.isupper() else char for char in str(value))
    for separator in ("/", ".", "_", "-"):
        with_separators = with_separators.replace(separator, " ")
    return " ".join(with_separators.split()).strip().lower()


def _tool_payload(*, event_type: str, payload: dict[str, Any], item: dict[str, Any]) -> RuntimeExecutionEvent | None:
    codex_item_tool = _codex_item_tool_payload(event_type=event_type, payload=payload, item=item)
    if codex_item_tool is not None:
        return codex_item_tool

    name = _tool_name(payload, item)
    item_type = str(item.get("type") or payload.get("item_type") or payload.get("kind") or "")
    normalized_event_type = event_type.lower()
    looks_like_tool = (
        bool(name)
        or any(token in normalized_event_type for token in ("tool", "exec", "command", "search", "browser", "fetch"))
        or item_type in {"command_execution", "tool_call", "function_call"}
    )
    if not looks_like_tool:
        return None
    status = _tool_status(event_type)
    return RuntimeExecutionEvent(
        event_type=f"runtime.tool_call.{status}",
        payload={
            "name": name or item_type or "tool",
            "status": status,
            "tool_call_id": _tool_call_id(payload, item),
            "provider_event_type": event_type,
            "command": item.get("command") or payload.get("command"),
            "exit_code": _first_present(item, payload, "exit_code"),
            "output": _first_present(item, payload, "aggregated_output") or _first_present(item, payload, "output"),
            "stdout": _first_present(item, payload, "stdout"),
            "stderr": _first_present(item, payload, "stderr"),
            "summary": _text_from_payload(payload, item),
            "raw": _compact_raw(payload),
        },
    )


def _codex_item_tool_payload(*, event_type: str, payload: dict[str, Any], item: dict[str, Any]) -> RuntimeExecutionEvent | None:
    item_type = str(item.get("type") or "").strip()
    if event_type == "item.fileChange.outputDelta":
        return _codex_file_change_output_delta_payload(event_type=event_type, payload=payload, item=item)
    if item_type == "commandExecution":
        return _codex_command_execution_payload(event_type=event_type, payload=payload, item=item)
    if item_type == "fileChange":
        return _codex_file_change_payload(event_type=event_type, payload=payload, item=item)
    if item_type == "webSearch":
        return _codex_web_search_payload(event_type=event_type, payload=payload, item=item)
    return None


def _codex_command_execution_payload(*, event_type: str, payload: dict[str, Any], item: dict[str, Any]) -> RuntimeExecutionEvent:
    command = _command_string(item.get("command"))
    exit_code = item.get("exitCode")
    if not isinstance(exit_code, int):
        exit_code = item.get("exit_code")
    status = "failed" if isinstance(exit_code, int) and exit_code != 0 else _tool_status(event_type)
    output = _optional_string(item.get("aggregatedOutput")) or _optional_string(item.get("aggregated_output"))
    return RuntimeExecutionEvent(
        event_type=f"runtime.tool_call.{status}",
        payload={
            "name": "command",
            "tool_kind": "command",
            "status": status,
            "tool_call_id": _tool_call_id(payload, item),
            "provider_event_type": event_type,
            "summary": _short_command_summary(command),
            "command": command or None,
            "exit_code": exit_code if isinstance(exit_code, int) else None,
            "output": output,
            "stdout": _optional_string(item.get("stdout")),
            "stderr": _optional_string(item.get("stderr")),
            "raw": _compact_raw(payload),
        },
    )


def _codex_file_change_payload(*, event_type: str, payload: dict[str, Any], item: dict[str, Any]) -> RuntimeExecutionEvent:
    status = _tool_status(event_type)
    changes = _file_change_records(item)
    summary = "Applying file changes" if status == "started" else "Applied file changes"
    return RuntimeExecutionEvent(
        event_type=f"runtime.tool_call.{status}",
        payload={
            "name": "file_change",
            "tool_kind": "file_change",
            "status": status,
            "tool_call_id": _tool_call_id(payload, item),
            "provider_event_type": event_type,
            "summary": summary,
            "changes": changes,
            "patch": _file_change_patch(changes),
            "raw": _compact_raw(payload),
        },
    )


def _codex_file_change_output_delta_payload(*, event_type: str, payload: dict[str, Any], item: dict[str, Any]) -> RuntimeExecutionEvent:
    output = _text_from_payload(payload, item)
    return RuntimeExecutionEvent(
        event_type="runtime.tool_call.updated",
        payload={
            "name": "file_change",
            "tool_kind": "file_change",
            "status": "updated",
            "tool_call_id": _tool_call_id(payload, item),
            "provider_event_type": event_type,
            "summary": "File changes updated",
            "output": output or None,
            "raw": _compact_raw(payload),
        },
    )


def _codex_web_search_payload(*, event_type: str, payload: dict[str, Any], item: dict[str, Any]) -> RuntimeExecutionEvent:
    status = _tool_status(event_type)
    query = _web_search_query(item)
    summary = "Searching the web" if status == "started" else query or "Web search completed"
    return RuntimeExecutionEvent(
        event_type=f"runtime.tool_call.{status}",
        payload={
            "name": "web_search",
            "tool_kind": "web_search",
            "status": status,
            "tool_call_id": _tool_call_id(payload, item),
            "provider_event_type": event_type,
            "summary": summary,
            "query": query or None,
            "results": _web_search_results(item),
            "raw": _compact_raw(payload),
        },
    )


def _command_string(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(part) for part in value).strip()
    if isinstance(value, str):
        return value.strip()
    return ""


def _short_command_summary(command: str) -> str:
    if not command:
        return "Command"
    return command.splitlines()[0][:96]


def _file_change_records(item: dict[str, Any]) -> list[dict[str, str | None]]:
    changes = item.get("changes")
    if not isinstance(changes, list):
        return []
    formatted: list[dict[str, str | None]] = []
    for change in changes:
        if not isinstance(change, dict):
            continue
        kind = change.get("kind") if isinstance(change.get("kind"), dict) else {}
        kind_type = str(kind.get("type") or "update").strip().lower()
        formatted.append(
            {
                "path": _optional_string(change.get("path")) or "",
                "changeType": _file_change_type(kind_type),
                "diff": _optional_string(change.get("diff")),
                "movePath": _optional_string(kind.get("move_path")),
            }
        )
    return formatted


def _file_change_type(kind_type: str) -> str:
    if kind_type == "create":
        return "add"
    if kind_type == "delete":
        return "delete"
    if kind_type == "move":
        return "move"
    return "edit"


def _file_change_patch(changes: list[dict[str, str | None]]) -> str | None:
    diffs = [str(change["diff"]) for change in changes if change.get("diff")]
    if not diffs:
        return None
    return "\n".join(diffs)


def _web_search_query(item: dict[str, Any]) -> str:
    action = item.get("action") if isinstance(item.get("action"), dict) else {}
    for value in (action.get("query"), item.get("query")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    queries = action.get("queries")
    if isinstance(queries, list):
        for value in queries:
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _web_search_results(item: dict[str, Any]) -> list[dict[str, str | None]]:
    results = item.get("results")
    if not isinstance(results, list):
        return []
    formatted: list[dict[str, str | None]] = []
    for result in results[:5]:
        if not isinstance(result, dict):
            continue
        formatted.append(
            {
                "title": _optional_string(result.get("title")) or "Untitled result",
                "url": _optional_string(result.get("url")),
                "snippet": _optional_string(result.get("snippet")),
            }
        )
    return formatted


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _tool_call_id(payload: dict[str, Any], item: dict[str, Any]) -> str | None:
    for value in (
        item.get("id"),
        item.get("item_id"),
        item.get("call_id"),
        item.get("tool_call_id"),
        payload.get("item_id"),
        payload.get("call_id"),
        payload.get("tool_call_id"),
        payload.get("id"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_present(first: dict[str, Any], second: dict[str, Any], key: str) -> Any:
    if key in first:
        return first[key]
    return second.get(key)


def _tool_status(event_type: str) -> str:
    normalized = event_type.lower()
    if any(token in normalized for token in ("failed", "error")):
        return "failed"
    if any(token in normalized for token in ("completed", "finished", "end", "exited")):
        return "completed"
    if any(token in normalized for token in ("started", "begin", "created")):
        return "started"
    return "completed"


def _tool_name(payload: dict[str, Any], item: dict[str, Any]) -> str:
    value = payload.get("name") or payload.get("tool_name") or payload.get("tool") or item.get("name") or item.get("tool_name")
    if isinstance(value, str) and value.strip():
        return value.strip()
    command = item.get("command") or payload.get("command")
    if isinstance(command, list) and command:
        return " ".join(str(part) for part in command[:3])
    if isinstance(command, str) and command.strip():
        return command.strip().splitlines()[0][:96]
    return ""


def _text_from_payload(payload: dict[str, Any], item: dict[str, Any]) -> str:
    candidates = [
        payload.get("delta"),
        payload.get("text"),
        payload.get("message"),
        payload.get("content"),
        item.get("delta"),
        item.get("text"),
        item.get("message"),
        item.get("content"),
        item.get("output"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _step_label(*, event_type: str, payload: dict[str, Any], item: dict[str, Any]) -> str:
    for value in (payload.get("label"), payload.get("message"), item.get("label"), item.get("title")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return event_type.replace("_", " ").replace(".", " ")


def _compact_raw(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in ("type", "event_type", "item", "message", "text", "delta", "command", "exit_code"):
        if key in payload:
            compact[key] = payload[key]
    return compact or payload
