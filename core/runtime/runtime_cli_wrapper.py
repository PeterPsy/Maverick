"""Runtime-local Maverick CLI wrapper management for agentic sessions."""

from __future__ import annotations

from pathlib import Path


def refresh_runtime_maverick_wrappers(repository_root: Path) -> list[Path]:
    """Refresh existing runtime-local Maverick CLI wrappers in workspace sessions."""
    refreshed: list[Path] = []
    sessions_root = Path(repository_root) / "workspaces"
    if not sessions_root.is_dir():
        return refreshed
    for wrapper in sessions_root.glob("*/runtime/sessions/*/bin/maverick"):
        try:
            current = wrapper.read_text(encoding="utf-8") if wrapper.is_file() else ""
            source = runtime_maverick_wrapper_source()
            if current == source:
                continue
            write_runtime_maverick_wrapper(wrapper)
            refreshed.append(wrapper)
        except OSError:
            continue
    return refreshed


def write_runtime_maverick_wrapper(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(runtime_maverick_wrapper_source(), encoding="utf-8")
    path.chmod(0o755)


def write_runtime_device_use_mcp_wrapper(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(runtime_device_use_mcp_wrapper_source(), encoding="utf-8")
    path.chmod(0o755)


def refresh_runtime_device_use_mcp_wrappers(repository_root: Path) -> list[Path]:
    """Refresh existing runtime-local Device Use MCP wrappers in workspace sessions."""
    refreshed: list[Path] = []
    sessions_root = Path(repository_root) / "workspaces"
    if not sessions_root.is_dir():
        return refreshed
    for wrapper in sessions_root.glob("*/runtime/sessions/*/bin/maverick-device-use-mcp"):
        try:
            current = wrapper.read_text(encoding="utf-8") if wrapper.is_file() else ""
            source = runtime_device_use_mcp_wrapper_source()
            if current == source:
                continue
            write_runtime_device_use_mcp_wrapper(wrapper)
            refreshed.append(wrapper)
        except OSError:
            continue
    return refreshed


def runtime_maverick_wrapper_source() -> str:
    """Return the workspace-local Maverick CLI wrapper installed into runtime/bin."""
    return """#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.request


def main(argv):
    if not argv or argv in (["--help"], ["-h"]):
        print("Usage: maverick {apps|core|app|sdk} ...")
        print("       maverick apps list --json")
        print("       maverick core cli list --json")
        print("       maverick app <app_id> frontend build --json")
        print("       maverick core cli run core.app-sdk.create --app-id <app_id> --template-id <id> --json")
        return 0
    if argv[:2] == ["sdk", "templates"]:
        return call_sdk({"action": "templates"})
    if argv[:2] == ["sdk", "docs"]:
        return call_sdk({"action": "docs"}, text_field="content")
    return call_cli(argv)


def runtime_auth_headers():
    token = os.environ.get("MAVERICK_RUNTIME_API_TOKEN", "")
    if not token:
        print("maverick: MAVERICK_RUNTIME_API_TOKEN is not set", file=sys.stderr)
        return None
    return {"Content-Type": "application/json", "Authorization": "Bearer " + token}


def call_sdk(payload, text_field=None):
    base_url = os.environ.get("MAVERICK_API_BASE", "http://127.0.0.1:8014").rstrip("/")
    headers = runtime_auth_headers()
    if headers is None:
        return 1
    request = urllib.request.Request(
        base_url + "/api/app-sdk",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    return print_response(request, text_field=text_field)


def call_cli(argv):
    base_url = os.environ.get("MAVERICK_API_BASE", "http://127.0.0.1:8014").rstrip("/")
    headers = runtime_auth_headers()
    if headers is None:
        return 1
    output_profile = os.environ.get("MAVERICK_RUNTIME_CLI_OUTPUT_PROFILE", "provider_compact").strip() or "provider_compact"
    request = urllib.request.Request(
        base_url + "/api/runtime/cli",
        data=json.dumps({
            "argv": argv,
            "effective_mode": os.environ.get("MAVERICK_EFFECTIVE_MODE", "sandbox"),
            "output_profile": output_profile,
        }).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    return print_response(request)


def print_response(request, text_field=None):
    try:
        with urllib.request.urlopen(request) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        sys.stderr.write(error.read().decode("utf-8") + "\\n")
        return 1
    if text_field:
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError:
            print(body)
            return 0
        print(decoded.get(text_field, ""))
        return response_exit_code(body)
    print(body)
    return response_exit_code(body)


def response_exit_code(body):
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError:
        return 0
    status_code = decoded.get("status_code")
    if isinstance(status_code, int) and status_code >= 400:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
"""


def runtime_device_use_mcp_wrapper_source() -> str:
    """Return the workspace-local Device Use MCP stdio wrapper installed into runtime/bin."""
    from core.device_use.contract import device_use_dynamic_tools
    from core.device_use.invocation_deadline import (
        DEFAULT_INVOCATION_TIMEOUT_SECONDS,
        RESULT_DELIVERY_GRACE_SECONDS,
        invocation_timeout_seconds,
    )

    tools = [
        {
            "name": tool["name"],
            "description": tool["description"],
            "inputSchema": tool["inputSchema"],
        }
        for tool in device_use_dynamic_tools()
    ]
    tools_repr = repr(tools)
    timeouts = {
        (tool["name"], action): invocation_timeout_seconds(tool["name"], action)
        for tool in tools
        for action in tool["inputSchema"]["properties"]["action"]["enum"]
    }
    return f"""#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.request

FALLBACK_TOOLS = {tools_repr}
INVOCATION_TIMEOUTS = {timeouts!r}
DEFAULT_TIMEOUT = {DEFAULT_INVOCATION_TIMEOUT_SECONDS!r}
DELIVERY_GRACE = {RESULT_DELIVERY_GRACE_SECONDS!r}


def send_response(resp):
    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\\n")
    sys.stdout.flush()


def get_tools():
    base_url = os.environ.get("MAVERICK_API_BASE", "http://127.0.0.1:8014").rstrip("/")
    token = os.environ.get("MAVERICK_RUNTIME_API_TOKEN", "")
    req = urllib.request.Request(
        base_url + "/api/device-use/tools",
        headers={{"Authorization": "Bearer " + token}} if token else {{}},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tools = data.get("tools")
            if isinstance(tools, list) and tools:
                return [
                    {{
                        "name": str(t.get("name") or ""),
                        "description": str(t.get("description") or ""),
                        "inputSchema": t.get("inputSchema") or {{"type": "object"}},
                    }}
                    for t in tools
                ]
    except Exception:
        pass
    return FALLBACK_TOOLS


def call_tool(name, arguments):
    base_url = os.environ.get("MAVERICK_API_BASE", "http://127.0.0.1:8014").rstrip("/")
    token = os.environ.get("MAVERICK_RUNTIME_API_TOKEN", "")
    session_id = os.environ.get("MAVERICK_RUNTIME_SESSION_ID", "")
    payload = {{
        "tool": name,
        "arguments": arguments,
        "session_id": session_id,
    }}
    req = urllib.request.Request(
        base_url + "/api/device-use/invoke",
        data=json.dumps(payload).encode("utf-8"),
        headers={{
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
        }},
        method="POST",
    )
    try:
        timeout = INVOCATION_TIMEOUTS.get((name, str(arguments.get("action") or "")), DEFAULT_TIMEOUT)
        with urllib.request.urlopen(req, timeout=timeout + DELIVERY_GRACE + 10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            invoke_result = data.get("result") or {{}}
            image_b64 = data.get("image_base64")
            is_error = bool(data.get("is_error", False))
            content = []
            text = ""
            if isinstance(invoke_result, dict):
                items = invoke_result.get("contentItems")
                if isinstance(items, list) and items and isinstance(items[0], dict) and isinstance(items[0].get("text"), str):
                    text = items[0]["text"]
                else:
                    text = json.dumps(invoke_result, ensure_ascii=False)
            else:
                text = str(data.get("error") or "Success")
            content.append({{"type": "text", "text": text}})
            if image_b64:
                content.append({{
                    "type": "image",
                    "data": image_b64,
                    "mimeType": "image/jpeg",
                }})
            return {{"content": content, "isError": is_error}}
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read().decode("utf-8"))
            msg = body.get("error") or str(error)
        except Exception:
            msg = str(error)
        return {{
            "content": [{{"type": "text", "text": f"Error: {{msg}}"}}],
            "isError": True,
        }}
    except Exception as error:
        return {{
            "content": [{{"type": "text", "text": f"Error: {{error}}"}}],
            "isError": True,
        }}


def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if not isinstance(msg, dict):
            continue
        req_id = msg.get("id")
        method = msg.get("method")
        if not method:
            continue
        if method == "initialize":
            params = msg.get("params") or {{}}
            send_response({{
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {{
                    "protocolVersion": params.get("protocolVersion") or "2024-11-05",
                    "capabilities": {{"tools": {{}}}},
                    "serverInfo": {{
                        "name": "maverick-device-use-mcp",
                        "version": "1.0.0",
                    }},
                }},
            }})
        elif method == "notifications/initialized":
            pass
        elif method == "ping":
            if req_id is not None:
                send_response({{"jsonrpc": "2.0", "id": req_id, "result": {{}}}})
        elif method == "tools/list":
            if req_id is not None:
                tools = get_tools()
                send_response({{"jsonrpc": "2.0", "id": req_id, "result": {{"tools": tools}}}})
        elif method == "tools/call":
            if req_id is not None:
                params = msg.get("params") or {{}}
                name = str(params.get("name") or "")
                arguments = params.get("arguments") or {{}}
                result = call_tool(name, arguments)
                send_response({{"jsonrpc": "2.0", "id": req_id, "result": result}})
        else:
            if req_id is not None:
                send_response({{
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {{"code": -32601, "message": f"Method not found: {{method}}"}},
                }})


if __name__ == "__main__":
    main()
"""
