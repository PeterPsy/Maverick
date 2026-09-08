"""Public event projection for Antigravity CLI ``step_update`` messages."""

from __future__ import annotations

import hashlib
import json

from core.providers.native_structured_cli_transport import NativeStructuredCliError


_STEP_STATES = frozenset({"ACTIVE", "DONE"})


def project_antigravity_step(update: object) -> tuple[str, dict[str, object]]:
    """Validate one documented step and expose only its public projection."""
    if not isinstance(update, dict):
        raise NativeStructuredCliError("antigravity_step_invalid")
    conversation_id = _required_text(update.get("conversation_id"), "antigravity_conversation_invalid")
    step_index = update.get("step_index")
    if isinstance(step_index, bool) or not isinstance(step_index, int) or step_index < 0:
        raise NativeStructuredCliError("antigravity_step_invalid")
    state = update.get("state")
    step_type = update.get("step_type")
    if state not in _STEP_STATES or not isinstance(step_type, str) or not step_type:
        raise NativeStructuredCliError("antigravity_step_invalid")

    common: dict[str, object] = {
        "provider_conversation_id": conversation_id,
        "provider_step_index": step_index,
        "provider_step_state": state,
        "provider_step_type": step_type,
    }
    if step_type == "agent_response":
        text = update.get("text_delta")
        if text is None:
            return "provider.lifecycle", {"phase": "native_agent_response", **common}
        if not isinstance(text, str):
            raise NativeStructuredCliError("antigravity_output_invalid")
        return "runtime.output.delta", {"text": text}
    if step_type == "tool":
        return _project_tool_step(update, common)
    if step_type == "subagent":
        info = update.get("subagent_info")
        if not isinstance(info, dict) or not isinstance(info.get("subagents"), list):
            raise NativeStructuredCliError("antigravity_subagent_step_invalid")
        return "provider.lifecycle", {
            "phase": "native_subagent_effect",
            **common,
            "subagent_count": len(info["subagents"]),
        }
    return "provider.lifecycle", {"phase": "native_session_update", **common}


def _project_tool_step(
    update: dict[str, object],
    common: dict[str, object],
) -> tuple[str, dict[str, object]]:
    info = update.get("tool_info")
    if not isinstance(info, dict):
        raise NativeStructuredCliError("antigravity_tool_step_invalid")
    tool_name = _required_text(
        update.get("tool_name") or info.get("name"),
        "antigravity_tool_step_invalid",
    )
    if info.get("name") not in {None, tool_name}:
        raise NativeStructuredCliError("antigravity_tool_step_invalid")
    parameters = info.get("parameters", {})
    if not isinstance(parameters, dict):
        raise NativeStructuredCliError("antigravity_tool_step_invalid")
    argument_names = sorted(parameters)
    if len(argument_names) > 128 or any(
        not isinstance(name, str) or not name or len(name) > 256
        for name in argument_names
    ):
        raise NativeStructuredCliError("antigravity_tool_step_invalid")
    call_id = f"{common['provider_conversation_id']}:{common['provider_step_index']}"
    payload: dict[str, object] = {
        **common,
        "provider_tool_call_id": call_id,
        "provider_tool_name": tool_name,
        "argument_names": argument_names,
        "arguments_sha256": _json_digest(parameters),
    }
    if common["provider_step_state"] == "ACTIVE":
        return "runtime.tool_call.started", payload
    error = info.get("error")
    output = info.get("output")
    if output is not None and not isinstance(output, str):
        raise NativeStructuredCliError("antigravity_tool_step_invalid")
    if error is not None:
        if not isinstance(error, dict):
            raise NativeStructuredCliError("antigravity_tool_step_invalid")
        error_type = error.get("type")
        error_message = error.get("message")
        if error_type is not None and (
            not isinstance(error_type, str)
            or not error_type
            or len(error_type) > 128
        ):
            raise NativeStructuredCliError("antigravity_tool_step_invalid")
        if error_message is not None and not isinstance(error_message, str):
            raise NativeStructuredCliError("antigravity_tool_step_invalid")
        payload["error_type"] = error_type or "tool_error"
        return "runtime.tool_call.failed", payload
    encoded_output = (output or "").encode("utf-8")
    payload["output_bytes"] = len(encoded_output)
    payload["output_sha256"] = hashlib.sha256(encoded_output).hexdigest()
    return "runtime.tool_call.completed", payload


def _json_digest(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise NativeStructuredCliError("antigravity_tool_step_invalid") from error
    return hashlib.sha256(encoded).hexdigest()


def _required_text(value: object, reason: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise NativeStructuredCliError(reason)
    return value


__all__ = ["project_antigravity_step"]
