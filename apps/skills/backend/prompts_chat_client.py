"""Minimal public read-only MCP transport for prompts.chat."""

from __future__ import annotations

from collections.abc import Callable
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROMPTS_CHAT_MCP_URL = "https://prompts.chat/api/mcp"
READ_ONLY_TOOLS = {"search_skills", "get_skill"}
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

HttpTransport = Callable[[Request], bytes]


class PromptsChatError(ValueError):
    """A safe public-catalog error suitable for an app response."""

    def __init__(self, code: str, detail: str, *, status_code: int = 502) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class PublicPromptsChatMcpClient:
    """Call only public Agent Skill reads with a bounded response."""

    def __init__(self, transport: HttpTransport | None = None) -> None:
        self._transport = transport or _urlopen_bytes

    def call(self, tool_name: str, arguments: dict) -> dict:
        if tool_name not in READ_ONLY_TOOLS:
            raise PromptsChatError(
                "prompts_chat_tool_denied",
                "Only public read operations are allowed.",
                status_code=400,
            )
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            PROMPTS_CHAT_MCP_URL,
            data=body,
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "User-Agent": "Maverick-Skills/0.1",
            },
            method="POST",
        )
        try:
            raw = self._transport(request)
        except HTTPError as error:
            raise PromptsChatError("prompts_chat_unavailable", f"prompts.chat returned HTTP {error.code}.") from None
        except (URLError, TimeoutError, OSError):
            raise PromptsChatError("prompts_chat_unavailable", "prompts.chat is unavailable.") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise PromptsChatError("prompts_chat_response_too_large", "prompts.chat returned too much data.")
        return _mcp_result(raw)


def _urlopen_bytes(request: Request) -> bytes:
    with urlopen(request, timeout=15) as response:
        return response.read(MAX_RESPONSE_BYTES + 1)


def _mcp_result(raw: bytes) -> dict:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise PromptsChatError("prompts_chat_response_invalid", "prompts.chat returned invalid text.") from None
    candidates = [line[6:] for line in text.splitlines() if line.startswith("data: ") and line[6:] != "[DONE]"]
    serialized = candidates[-1] if candidates else text
    try:
        envelope = json.loads(serialized)
    except json.JSONDecodeError:
        raise PromptsChatError("prompts_chat_response_invalid", "prompts.chat returned invalid JSON.") from None
    if not isinstance(envelope, dict) or isinstance(envelope.get("error"), dict):
        raise PromptsChatError("prompts_chat_request_failed", "prompts.chat rejected the request.")
    result = envelope.get("result")
    if not isinstance(result, dict) or result.get("isError") is True:
        raise PromptsChatError("prompts_chat_request_failed", "prompts.chat could not complete the request.")
    content = result.get("content")
    if not isinstance(content, list):
        raise PromptsChatError("prompts_chat_response_invalid", "prompts.chat returned no result content.")
    text_item = next(
        (
            item.get("text")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ),
        None,
    )
    if not isinstance(text_item, str):
        raise PromptsChatError("prompts_chat_response_invalid", "prompts.chat returned no text result.")
    try:
        payload = json.loads(text_item)
    except json.JSONDecodeError:
        raise PromptsChatError(
            "prompts_chat_response_invalid",
            "prompts.chat returned malformed result content.",
        ) from None
    if not isinstance(payload, dict):
        raise PromptsChatError("prompts_chat_response_invalid", "prompts.chat returned an invalid result.")
    return payload
