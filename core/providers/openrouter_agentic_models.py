"""Private models for the certified OpenRouter Chat Completions codec."""

from __future__ import annotations

from dataclasses import dataclass


OPENROUTER_AGENTIC_MODEL_ID = "deepseek/deepseek-v4-flash"
OPENROUTER_AGENTIC_RESOLVED_MODEL_ID = "deepseek/deepseek-v4-flash-20260423"
OPENROUTER_AGENTIC_UPSTREAM_ID = "deepinfra/fp8"
OPENROUTER_AGENTIC_PROVIDER_NAME = "DeepInfra"
OPENROUTER_AGENTIC_ENDPOINT_ID = "openrouter-chat-completions-v1"
OPENROUTER_AGENTIC_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_AGENTIC_CODEC_ID = "openrouter-chat-completions"
OPENROUTER_AGENTIC_CODEC_VERSION = "1"
OPENROUTER_AGENTIC_SCHEMA_VERSION = "1"
OPENROUTER_AGENTIC_CONTENT_TYPE = "application/vnd.maverick.openrouter-chat-state+json"


@dataclass(frozen=True)
class OpenRouterPendingToolCall:
    call_id: str
    name: str


@dataclass(frozen=True)
class OpenRouterChatState:
    """Exact message continuation retained only in provider-private storage."""

    schema_version: str
    history: tuple[dict[str, object], ...]
    pending_tool_call: OpenRouterPendingToolCall | None
    consumed_tool_call_ids: tuple[str, ...]


class OpenRouterAgenticProtocolError(RuntimeError):
    """Normalized codec or transport error safe to cross the provider boundary."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def openrouter_error_reason(payload: dict[str, object]) -> str:
    error = payload.get("error")
    error_data = error if isinstance(error, dict) else {}
    metadata = error_data.get("metadata")
    metadata_data = metadata if isinstance(metadata, dict) else {}
    error_type = str(metadata_data.get("error_type") or "").strip().lower()
    raw_code = error_data.get("code")
    code = int(raw_code) if isinstance(raw_code, str) and raw_code.isdigit() else raw_code
    if code in {401, 403} or error_type in {"invalid_api_key", "permission_denied"}:
        return "provider_authentication_failed"
    if code == 404 or error_type == "no_available_provider":
        return "provider_no_eligible_endpoint"
    if code == 429 or error_type in {"rate_limit_exceeded", "provider_rate_limit"}:
        return "provider_rate_limited"
    if code in {408, 504} or error_type in {"request_timeout", "provider_timeout"}:
        return "provider_timeout"
    if isinstance(code, int) and 400 <= code < 500:
        return "provider_request_rejected"
    return "provider_unavailable"
