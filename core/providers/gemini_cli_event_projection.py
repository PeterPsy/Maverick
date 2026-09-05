"""Public event/effect projection for Gemini ACP updates."""

from pathlib import Path

from core.providers.native_acp_transport import NativeAcpError


def project_acp_update(update, workspace_root):
    kind = update.get("sessionUpdate")
    if kind == "agent_message_chunk":
        content = update.get("content", {})
        if not isinstance(content, dict) or content.get("type") != "text" or not isinstance(content.get("text"), str):
            raise NativeAcpError("native_acp_output_invalid")
        return "runtime.output.delta", {"text": content["text"]}
    if kind in {"tool_call", "tool_call_update"}:
        locations = update.get("locations", [])
        if not isinstance(locations, list):
            raise NativeAcpError("native_acp_effect_invalid")
        for location in locations:
            if not isinstance(location, dict) or not isinstance(location.get("path"), str) or not location["path"]:
                raise NativeAcpError("native_acp_effect_invalid")
            path = Path(location["path"])
            resolved = (Path(workspace_root) / path).resolve()
            if not resolved.is_relative_to(Path(workspace_root).resolve()):
                raise NativeAcpError("native_acp_effect_outside_workspace")
        return "provider.lifecycle", {"phase": "native_tool_effect", "update": update}
    return "provider.lifecycle", {"phase": "native_session_update", "update": update}


__all__ = ["project_acp_update"]
