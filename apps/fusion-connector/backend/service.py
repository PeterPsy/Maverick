"""Fusion Connector app-owned service logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import socket
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse


APP_ID = "fusion-connector"
DEFAULT_ENDPOINT = "http://127.0.0.1:27182/mcp"
MCP_PROTOCOL_VERSION = "2025-03-26"
CLIENT_INFO = {"name": "maverick-fusion-connector", "version": "0.1.0"}
MAX_HTTP_RESPONSE_BYTES = 5_000_000
MAX_AUDIT_ITEMS = 100

READ_ONLY_PREFIXES = (
    "describe",
    "find",
    "get",
    "inspect",
    "list",
    "query",
    "read",
    "search",
    "status",
    "version",
)
MUTATING_HINTS = (
    "add",
    "create",
    "delete",
    "edit",
    "export",
    "insert",
    "modify",
    "move",
    "remove",
    "rename",
    "save",
    "set",
    "update",
    "write",
)
DEFAULT_DENYLIST = [
    "eval",
    "execute",
    "filesystem",
    "open_url",
    "python",
    "script",
    "shell",
    "terminal",
]


class FusionConnectorError(Exception):
    """Expected connector failure with a platform-facing status code."""

    def __init__(self, message: str, *, status_code: int = 400, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


@dataclass(frozen=True)
class InvocationContext:
    """Redaction-safe context values used for audit records."""

    surface: str
    workspace_id: str | None = None
    user_id: str | None = None
    runtime_session_id: str | None = None
    effective_mode: str | None = None


def handle_action(
    data_root: Path,
    action: str,
    arguments: dict[str, Any] | None = None,
    *,
    context: InvocationContext | None = None,
) -> tuple[int, dict[str, Any]]:
    """Handle one CLI or MCP action."""

    service = FusionConnectorService(data_root)
    try:
        return service.handle(action, arguments or {}, context=context or InvocationContext(surface="unknown"))
    except FusionConnectorError as exc:
        return exc.status_code, {"ok": False, "error": str(exc), **exc.details}


class FusionConnectorService:
    """App-owned service for talking to Autodesk Fusion's local MCP server."""

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.state_path = data_root / "state.json"

    def handle(
        self,
        action: str,
        arguments: dict[str, Any],
        *,
        context: InvocationContext,
    ) -> tuple[int, dict[str, Any]]:
        normalized = _normalize_action(action)
        if normalized == "status":
            return self.status(arguments)
        if normalized == "list_tools":
            return self.list_tools(arguments)
        if normalized == "call_tool":
            return self.call_tool(arguments, context=context)
        if normalized == "config_get":
            return 200, {"ok": True, "config": _public_config(self._state()["config"])}
        if normalized == "config_set":
            return self.config_set(arguments, context=context)
        if normalized == "audit_recent":
            return self.audit_recent(arguments)
        if normalized in {"operations_manifest", "manifest"}:
            return 200, {"ok": True, "operations": operations_manifest()}
        if normalized == "reference_manifest":
            return 200, {"ok": True, "reference_manifest": {"entity_types": []}}
        raise FusionConnectorError(f"Unsupported Fusion Connector action `{action}`.", status_code=400)

    def status(self, arguments: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        config = self._state()["config"]
        client = _client_for_config(config, arguments)
        try:
            tools = client.list_tools(limit=25)
        except FusionConnectorError as exc:
            return exc.status_code, {
                "ok": False,
                "connected": False,
                "endpoint": client.endpoint,
                "error": str(exc),
                "hint": "Fusion must be open on the same host as Maverick, with Fusion MCP Server enabled.",
            }
        return 200, {
            "ok": True,
            "connected": True,
            "endpoint": client.endpoint,
            "protocol_version": MCP_PROTOCOL_VERSION,
            "tool_count": len(tools),
            "tools_preview": [_tool_summary(tool) for tool in tools[:10]],
        }

    def list_tools(self, arguments: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        config = self._state()["config"]
        client = _client_for_config(config, arguments)
        limit = _bounded_int(arguments.get("limit"), default=100, minimum=1, maximum=500)
        tools = client.list_tools(limit=limit)
        return 200, {
            "ok": True,
            "endpoint": client.endpoint,
            "tool_count": len(tools),
            "tools": [_tool_summary(tool) for tool in tools],
        }

    def call_tool(self, arguments: dict[str, Any], *, context: InvocationContext) -> tuple[int, dict[str, Any]]:
        config = self._state()["config"]
        client = _client_for_config(config, arguments)
        fusion_tool_name = str(arguments.get("fusion_tool_name") or arguments.get("external_tool_name") or "").strip()
        if not fusion_tool_name:
            raise FusionConnectorError("`fusion_tool_name` is required.", status_code=400)
        tool_arguments = arguments.get("tool_arguments", {})
        if not isinstance(tool_arguments, dict):
            raise FusionConnectorError("`tool_arguments` must be an object.", status_code=400)
        policy_error = _policy_error(config, fusion_tool_name, bool(arguments.get("confirm")))
        if policy_error is not None:
            return policy_error

        started_at = _utc_now()
        try:
            result = client.call_tool(fusion_tool_name, tool_arguments)
        except FusionConnectorError as exc:
            self._append_audit(
                {
                    "timestamp": started_at,
                    "action": "call_tool",
                    "fusion_tool_name": fusion_tool_name,
                    "ok": False,
                    "status_code": exc.status_code,
                    "error": str(exc),
                    **_context_audit_fields(context),
                }
            )
            return exc.status_code, {"ok": False, "fusion_tool_name": fusion_tool_name, "error": str(exc), **exc.details}

        self._append_audit(
            {
                "timestamp": started_at,
                "action": "call_tool",
                "fusion_tool_name": fusion_tool_name,
                "ok": True,
                "status_code": 200,
                "arguments_preview": _truncate_json(tool_arguments, limit=1200),
                **_context_audit_fields(context),
            }
        )
        return 200, {
            "ok": True,
            "endpoint": client.endpoint,
            "fusion_tool_name": fusion_tool_name,
            "result": result,
        }

    def config_set(self, arguments: dict[str, Any], *, context: InvocationContext) -> tuple[int, dict[str, Any]]:
        if not arguments.get("confirm"):
            return 428, {
                "ok": False,
                "confirmation_required": True,
                "error": "Config changes require `confirm: true`.",
            }

        state = self._state()
        config = dict(state["config"])
        if arguments.get("reset_defaults"):
            config = default_config()
        if "endpoint" in arguments:
            config["endpoint"] = _validated_endpoint(str(arguments["endpoint"]))
        if "request_timeout_seconds" in arguments:
            config["request_timeout_seconds"] = _bounded_float(
                arguments["request_timeout_seconds"], default=10.0, minimum=0.5, maximum=30.0
            )
        if "tool_allowlist" in arguments:
            config["tool_allowlist"] = _string_list(arguments["tool_allowlist"], field_name="tool_allowlist")
        if "tool_denylist" in arguments:
            config["tool_denylist"] = _string_list(arguments["tool_denylist"], field_name="tool_denylist")
        if "mutating_requires_confirm" in arguments:
            config["mutating_requires_confirm"] = bool(arguments["mutating_requires_confirm"])
        if "unknown_requires_confirm" in arguments:
            config["unknown_requires_confirm"] = bool(arguments["unknown_requires_confirm"])

        state["config"] = _normalize_config(config)
        self._write_state(state)
        self._append_audit(
            {
                "timestamp": _utc_now(),
                "action": "config_set",
                "ok": True,
                "status_code": 200,
                "changed_fields": sorted(
                    key
                    for key in arguments
                    if key
                    in {
                        "endpoint",
                        "request_timeout_seconds",
                        "tool_allowlist",
                        "tool_denylist",
                        "mutating_requires_confirm",
                        "unknown_requires_confirm",
                        "reset_defaults",
                    }
                ),
                **_context_audit_fields(context),
            }
        )
        return 200, {"ok": True, "config": _public_config(state["config"])}

    def audit_recent(self, arguments: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        limit = _bounded_int(arguments.get("limit"), default=20, minimum=1, maximum=MAX_AUDIT_ITEMS)
        audit = self._state().get("audit", [])
        if not isinstance(audit, list):
            audit = []
        return 200, {"ok": True, "items": list(reversed(audit[-limit:]))}

    def _state(self) -> dict[str, Any]:
        self.data_root.mkdir(parents=True, exist_ok=True)
        if not self.state_path.exists():
            state = default_state()
            self._write_state(state)
            return state
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        state = default_state()
        if isinstance(raw.get("config"), dict):
            state["config"] = _normalize_config({**state["config"], **raw["config"]})
        if isinstance(raw.get("audit"), list):
            state["audit"] = raw["audit"][-MAX_AUDIT_ITEMS:]
        return state

    def _write_state(self, state: dict[str, Any]) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "1",
            "config": _normalize_config(state.get("config", {})),
            "audit": state.get("audit", [])[-MAX_AUDIT_ITEMS:]
            if isinstance(state.get("audit"), list)
            else [],
        }
        self.state_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _append_audit(self, item: dict[str, Any]) -> None:
        state = self._state()
        audit = state.get("audit", [])
        if not isinstance(audit, list):
            audit = []
        audit.append(_json_safe(item))
        state["audit"] = audit[-MAX_AUDIT_ITEMS:]
        self._write_state(state)


class FusionMcpHttpClient:
    """Minimal MCP Streamable HTTP client for Autodesk Fusion's local server."""

    def __init__(self, endpoint: str, *, timeout_seconds: float) -> None:
        self.endpoint = _validated_endpoint(endpoint)
        self.timeout_seconds = timeout_seconds
        self._next_id = 1
        self._session_id: str | None = None

    def list_tools(self, *, limit: int) -> list[dict[str, Any]]:
        self._initialize()
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(20):
            params = {"cursor": cursor} if cursor else {}
            result = self._json_rpc_result("tools/list", params=params)
            page_tools = result.get("tools", [])
            if isinstance(page_tools, list):
                tools.extend(tool for tool in page_tools if isinstance(tool, dict))
            cursor_value = result.get("nextCursor")
            cursor = str(cursor_value) if cursor_value else None
            if not cursor or len(tools) >= limit:
                break
        return tools[:limit]

    def call_tool(self, tool_name: str, tool_arguments: dict[str, Any]) -> dict[str, Any]:
        self._initialize()
        return self._json_rpc_result(
            "tools/call",
            params={
                "name": tool_name,
                "arguments": tool_arguments,
            },
        )

    def _initialize(self) -> None:
        if self._session_id:
            return
        request_id = self._id()
        response, session_id = self._post_json(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": CLIENT_INFO,
                },
            }
        )
        if session_id:
            self._session_id = session_id
        self._raise_for_rpc_error(response)
        self._post_json({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, allow_empty=True)

    def _json_rpc_result(self, method: str, *, params: dict[str, Any]) -> dict[str, Any]:
        response, _session_id = self._post_json(
            {
                "jsonrpc": "2.0",
                "id": self._id(),
                "method": method,
                "params": params,
            }
        )
        self._raise_for_rpc_error(response)
        result = response.get("result")
        if not isinstance(result, dict):
            raise FusionConnectorError(f"Fusion MCP returned an invalid `{method}` result.", status_code=502)
        return result

    def _id(self) -> int:
        current = self._next_id
        self._next_id += 1
        return current

    def _post_json(self, payload: dict[str, Any], *, allow_empty: bool = False) -> tuple[dict[str, Any], str | None]:
        data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        req = urlrequest.Request(self.endpoint, data=data, headers=headers, method="POST")
        opener = urlrequest.build_opener(urlrequest.ProxyHandler({}))
        try:
            with opener.open(req, timeout=self.timeout_seconds) as response:
                session_id = response.headers.get("Mcp-Session-Id") or response.headers.get("MCP-Session-Id")
                body = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
                content_type = response.headers.get("Content-Type", "")
        except urlerror.HTTPError as exc:
            body = exc.read(MAX_HTTP_RESPONSE_BYTES + 1)
            detail = _decode_body_preview(body)
            raise FusionConnectorError(
                f"Fusion MCP HTTP error {exc.code}.",
                status_code=502,
                details={"http_status": exc.code, "response_preview": detail},
            ) from exc
        except (urlerror.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise FusionConnectorError(
                "Fusion MCP is not reachable from this Maverick host.",
                status_code=503,
                details={"endpoint": self.endpoint, "reason": str(exc)},
            ) from exc
        if len(body) > MAX_HTTP_RESPONSE_BYTES:
            raise FusionConnectorError("Fusion MCP response exceeded the app safety limit.", status_code=502)
        if not body and allow_empty:
            return {}, session_id
        parsed = _parse_mcp_response(body, content_type=content_type)
        return parsed, session_id

    @staticmethod
    def _raise_for_rpc_error(response: dict[str, Any]) -> None:
        error = response.get("error")
        if not error:
            return
        if isinstance(error, dict):
            message = str(error.get("message") or "Fusion MCP JSON-RPC error.")
            code = error.get("code")
            raise FusionConnectorError(message, status_code=502, details={"rpc_error_code": code})
        raise FusionConnectorError("Fusion MCP JSON-RPC error.", status_code=502)


def operations_manifest() -> list[dict[str, Any]]:
    return [
        {"action": "status", "description": "Check whether Fusion MCP is reachable from Maverick."},
        {"action": "list_tools", "description": "List tools exposed by the active Fusion MCP server."},
        {"action": "call_tool", "description": "Call one discovered Fusion MCP tool after policy checks."},
        {"action": "config_get", "description": "Read redaction-safe Fusion Connector configuration."},
        {"action": "config_set", "description": "Update endpoint or tool policy. Requires confirm=true."},
        {"action": "audit_recent", "description": "Return recent Fusion Connector audit records."},
        {"action": "reference_manifest", "description": "Return the empty reference manifest for this headless connector."},
    ]


def default_config() -> dict[str, Any]:
    return {
        "endpoint": DEFAULT_ENDPOINT,
        "request_timeout_seconds": 10.0,
        "tool_allowlist": [],
        "tool_denylist": list(DEFAULT_DENYLIST),
        "mutating_requires_confirm": True,
        "unknown_requires_confirm": True,
    }


def default_state() -> dict[str, Any]:
    return {"schema_version": "1", "config": default_config(), "audit": []}


def _normalize_action(action: str) -> str:
    value = str(action or "status").strip().lower().replace("-", "_").replace(".", "_")
    aliases = {
        "tools": "list_tools",
        "tool_list": "list_tools",
        "call": "call_tool",
        "config": "config_get",
        "audit": "audit_recent",
    }
    return aliases.get(value, value)


def _normalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    defaults = default_config()
    config = {**defaults, **(raw or {})}
    config["endpoint"] = _validated_endpoint(str(config.get("endpoint") or DEFAULT_ENDPOINT))
    config["request_timeout_seconds"] = _bounded_float(
        config.get("request_timeout_seconds"), default=10.0, minimum=0.5, maximum=30.0
    )
    config["tool_allowlist"] = _string_list(config.get("tool_allowlist", []), field_name="tool_allowlist")
    config["tool_denylist"] = _string_list(config.get("tool_denylist", DEFAULT_DENYLIST), field_name="tool_denylist")
    config["mutating_requires_confirm"] = bool(config.get("mutating_requires_confirm", True))
    config["unknown_requires_confirm"] = bool(config.get("unknown_requires_confirm", True))
    return config


def _public_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "endpoint": config["endpoint"],
        "request_timeout_seconds": config["request_timeout_seconds"],
        "tool_allowlist": config["tool_allowlist"],
        "tool_denylist": config["tool_denylist"],
        "mutating_requires_confirm": config["mutating_requires_confirm"],
        "unknown_requires_confirm": config["unknown_requires_confirm"],
    }


def _validated_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint.strip())
    if parsed.scheme not in {"http", "https"}:
        raise FusionConnectorError("Fusion MCP endpoint must use http or https.", status_code=400)
    if not parsed.hostname:
        raise FusionConnectorError("Fusion MCP endpoint must include a host.", status_code=400)
    if not _is_loopback_host(parsed.hostname):
        raise FusionConnectorError(
            "Fusion MCP endpoint must be loopback-only for v1.",
            status_code=400,
            details={"allowed_examples": [DEFAULT_ENDPOINT]},
        )
    if parsed.username or parsed.password:
        raise FusionConnectorError("Fusion MCP endpoint must not include credentials.", status_code=400)
    if not parsed.path:
        raise FusionConnectorError("Fusion MCP endpoint must include a path, usually `/mcp`.", status_code=400)
    return endpoint.strip()


def _is_loopback_host(hostname: str) -> bool:
    normalized = hostname.strip().strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _client_for_config(config: dict[str, Any], arguments: dict[str, Any]) -> FusionMcpHttpClient:
    endpoint = str(arguments.get("endpoint") or config["endpoint"])
    timeout = _bounded_float(
        arguments.get("request_timeout_seconds", config["request_timeout_seconds"]),
        default=float(config["request_timeout_seconds"]),
        minimum=0.5,
        maximum=30.0,
    )
    return FusionMcpHttpClient(endpoint, timeout_seconds=timeout)


def _policy_error(config: dict[str, Any], fusion_tool_name: str, confirmed: bool) -> tuple[int, dict[str, Any]] | None:
    normalized = _policy_token(fusion_tool_name)
    allowlist = set(config.get("tool_allowlist") or [])
    if allowlist and fusion_tool_name not in allowlist:
        return 403, {
            "ok": False,
            "blocked": True,
            "error": "Fusion tool is not in the configured allowlist.",
            "fusion_tool_name": fusion_tool_name,
        }
    denylist = [str(item).lower() for item in config.get("tool_denylist") or []]
    for denied in denylist:
        if denied and denied in normalized:
            return 403, {
                "ok": False,
                "blocked": True,
                "error": "Fusion tool is blocked by the configured denylist.",
                "fusion_tool_name": fusion_tool_name,
                "matched_policy": denied,
            }
    if not config.get("mutating_requires_confirm", True):
        return None
    if _looks_read_only(normalized):
        return None
    if not config.get("unknown_requires_confirm", True) and not _looks_mutating(normalized):
        return None
    if confirmed:
        return None
    return 428, {
        "ok": False,
        "confirmation_required": True,
        "fusion_tool_name": fusion_tool_name,
        "error": "Calling this Fusion tool requires explicit user confirmation. Retry with `confirm: true` only after the user agrees.",
    }


def _policy_token(tool_name: str) -> str:
    return tool_name.strip().lower().replace("-", "_").replace(" ", "_").replace(".", "_")


def _looks_read_only(normalized_tool_name: str) -> bool:
    return normalized_tool_name.startswith(READ_ONLY_PREFIXES) or any(
        f"_{prefix}_" in normalized_tool_name for prefix in READ_ONLY_PREFIXES
    )


def _looks_mutating(normalized_tool_name: str) -> bool:
    return normalized_tool_name.startswith(MUTATING_HINTS) or any(
        f"_{hint}_" in normalized_tool_name for hint in MUTATING_HINTS
    )


def _parse_mcp_response(body: bytes, *, content_type: str) -> dict[str, Any]:
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        raise FusionConnectorError("Fusion MCP returned an empty response.", status_code=502)
    try:
        if "text/event-stream" in content_type.lower() or text.startswith("event:") or "\ndata:" in text:
            for event_data in _event_stream_data_items(text):
                if event_data == "[DONE]":
                    continue
                parsed = json.loads(event_data)
                if isinstance(parsed, dict):
                    return parsed
            raise FusionConnectorError("Fusion MCP event stream did not include a JSON response.", status_code=502)
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FusionConnectorError(
            "Fusion MCP returned malformed JSON.",
            status_code=502,
            details={"response_preview": text[:1000]},
        ) from exc
    if not isinstance(parsed, dict):
        raise FusionConnectorError("Fusion MCP returned a non-object JSON response.", status_code=502)
    return parsed


def _event_stream_data_items(text: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            if current:
                items.append("\n".join(current))
                current = []
            continue
        if line.startswith("data:"):
            current.append(line[5:].lstrip())
    if current:
        items.append("\n".join(current))
    return items


def _tool_summary(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("inputSchema") or tool.get("input_schema")
    return {
        "name": str(tool.get("name") or ""),
        "description": str(tool.get("description") or ""),
        "input_schema": schema if isinstance(schema, dict) else {"type": "object"},
    }


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _bounded_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise FusionConnectorError(f"`{field_name}` must be a list of strings.", status_code=400)
    result = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text)
    return result[:200]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _context_audit_fields(context: InvocationContext) -> dict[str, Any]:
    return {
        "surface": context.surface,
        "workspace_id": context.workspace_id,
        "user_id": context.user_id,
        "runtime_session_id": context.runtime_session_id,
        "effective_mode": context.effective_mode,
    }


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=True)
        return value
    except (TypeError, ValueError):
        return str(value)


def _truncate_json(value: Any, *, limit: int) -> str:
    text = json.dumps(_json_safe(value), ensure_ascii=True, sort_keys=True)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _decode_body_preview(body: bytes) -> str:
    text = body[:2000].decode("utf-8", errors="replace")
    return text.strip()
