"""Hosted text generation client and transports."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import socket
from typing import Iterable, Literal, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request

from core.providers.errors import ProviderError
from core.providers.models import RoutingDecision
from core.providers.provider_authorization import provider_secret_target
from core.providers.store import ProviderStore
from core.secrets.errors import SecretError
from core.secrets.models import SecretResolutionContext
from core.secrets.secret_resolution import resolve_secret_for_runtime
from core.secrets.service import resolve_app_secret_grant
from core.secrets.store import SecretStore


MessageRole = Literal["system", "user", "assistant"]

OPENAI_COMPATIBLE_ENDPOINTS = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
}
BLOCKED_HOSTED_TEXT_MARKERS = (
    "local path:",
    "Referenced app-owned records:",
    "/home/ubuntu/projects/maverick-v3/workspaces/",
    "workspaces/default/",
)


class HostedTextGenerationError(ProviderError):
    """Hosted text generation failure with a stable reason code."""

    def __init__(self, reason_code: str, message: str | None = None, *, reason_codes: list[str] | None = None) -> None:
        super().__init__(message or reason_code)
        self.reason_code = reason_code
        self.reason_codes = list(reason_codes or [reason_code])


@dataclass(frozen=True)
class TextGenerationMessage:
    """One hosted chat message."""

    role: MessageRole
    content: str


@dataclass(frozen=True)
class TextGenerationRequest:
    """Minimal hosted text generation request."""

    messages: list[TextGenerationMessage]
    model_id: str
    system_prompt: str | None = None
    max_output_tokens: int | None = None
    timeout_seconds: int | None = None
    stream: bool = False
    workspace_id: str | None = None
    workspace_root: str | None = None


@dataclass(frozen=True)
class TextGenerationResult:
    """Normalized hosted text generation result."""

    output_text: str
    deltas: list[str]
    provider_id: str
    model_id: str
    reason_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HostedTextTransportResult:
    """Transport response normalized before provider parsing."""

    status_code: int
    payload: dict[str, object] | None = None
    chunks: list[str] = field(default_factory=list)
    timed_out: bool = False
    error: str | None = None


class HostedTextTransport(Protocol):
    """Transport contract for OpenAI-compatible hosted text clients."""

    def send(
        self,
        *,
        endpoint_url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        stream: bool,
        timeout_seconds: int | None,
    ) -> HostedTextTransportResult:
        ...


class TextGenerationClient(Protocol):
    """Client protocol implemented by hosted text providers."""

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        ...


class FakeHostedTextTransport:
    """Deterministic hosted text transport for tests."""

    def __init__(
        self,
        *,
        response_text: str = "fake hosted response",
        chunks: list[str] | None = None,
        status_code: int = 200,
        payload: dict[str, object] | None = None,
        timed_out: bool = False,
        error: str | None = None,
    ) -> None:
        self.response_text = response_text
        self.chunks = list(chunks or [])
        self.status_code = status_code
        self.payload = payload
        self.timed_out = timed_out
        self.error = error
        self.requests: list[dict[str, object]] = []

    def send(
        self,
        *,
        endpoint_url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        stream: bool,
        timeout_seconds: int | None,
    ) -> HostedTextTransportResult:
        safe_headers = {
            key: ("<redacted>" if key.lower() == "authorization" else value)
            for key, value in headers.items()
        }
        self.requests.append(
            {
                "endpoint_url": endpoint_url,
                "headers": safe_headers,
                "payload": dict(payload),
                "stream": stream,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.timed_out:
            return HostedTextTransportResult(status_code=0, timed_out=True, error=self.error)
        if self.status_code >= 400:
            return HostedTextTransportResult(status_code=self.status_code, payload=self.payload, error=self.error)
        if stream and self.chunks:
            return HostedTextTransportResult(status_code=self.status_code, chunks=list(self.chunks), payload=self.payload)
        payload = self.payload or {
            "choices": [
                {
                    "message": {
                        "content": self.response_text,
                    }
                }
            ]
        }
        return HostedTextTransportResult(status_code=self.status_code, payload=payload)


class OpenAICompatibleHttpTransport:
    """Small standard-library HTTP transport for OpenAI-compatible chat APIs."""

    def send(
        self,
        *,
        endpoint_url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        stream: bool,
        timeout_seconds: int | None,
    ) -> HostedTextTransportResult:
        body = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(endpoint_url, data=body, headers=headers, method="POST")
        try:
            with urllib_request.urlopen(req, timeout=timeout_seconds) as response:
                if stream:
                    return HostedTextTransportResult(
                        status_code=response.status,
                        chunks=list(_iter_openai_sse_chunks(response)),
                    )
                try:
                    decoded = json.loads(response.read().decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return HostedTextTransportResult(status_code=response.status, error="provider_response_invalid")
                return HostedTextTransportResult(status_code=response.status, payload=decoded)
        except urllib_error.HTTPError as error:
            return HostedTextTransportResult(status_code=error.code, error=str(error))
        except (TimeoutError, socket.timeout, urllib_error.URLError) as error:
            if isinstance(error, urllib_error.URLError) and not isinstance(error.reason, TimeoutError | socket.timeout):
                return HostedTextTransportResult(status_code=0, error=str(error))
            return HostedTextTransportResult(status_code=0, timed_out=True, error=str(error))


class OpenAICompatibleTextGenerationClient:
    """Hosted text generation client for OpenAI-compatible chat completions."""

    def __init__(
        self,
        *,
        provider_id: str,
        api_key: str,
        endpoint_url: str | None = None,
        transport: HostedTextTransport | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.api_key = api_key
        self.endpoint_url = endpoint_url or OPENAI_COMPATIBLE_ENDPOINTS.get(provider_id)
        if not self.endpoint_url:
            raise HostedTextGenerationError("hosted_text_provider_unsupported")
        self.transport = transport or OpenAICompatibleHttpTransport()

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        """Generate text and normalize streaming/non-streaming provider output."""
        _validate_hosted_text_request(request)
        payload = _openai_payload(request)
        result = self.transport.send(
            endpoint_url=self.endpoint_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream" if request.stream else "application/json",
            },
            payload=payload,
            stream=request.stream,
            timeout_seconds=request.timeout_seconds,
        )
        if result.timed_out:
            raise HostedTextGenerationError("provider_timeout")
        if result.status_code in {401, 403}:
            raise HostedTextGenerationError("provider_credential_rejected")
        if result.status_code == 429:
            raise HostedTextGenerationError("provider_rate_limited")
        if result.status_code >= 400 or result.status_code == 0:
            raise HostedTextGenerationError("provider_http_error")
        deltas = result.chunks if request.stream else [_extract_message_content(result.payload)]
        if not deltas or any(delta is None for delta in deltas):
            raise HostedTextGenerationError("provider_response_invalid")
        text_deltas = [str(delta) for delta in deltas if str(delta)]
        if not text_deltas:
            raise HostedTextGenerationError("provider_response_invalid")
        return TextGenerationResult(
            output_text="".join(text_deltas),
            deltas=text_deltas,
            provider_id=self.provider_id,
            model_id=request.model_id,
            reason_codes=["hosted_text_generation_completed"],
        )


def execute_hosted_text_generation(
    provider_store: ProviderStore,
    secret_store: SecretStore,
    *,
    decision: RoutingDecision,
    request: TextGenerationRequest,
    runtime_session_id: str | None = None,
    app_id: str | None = None,
    transport: HostedTextTransport | None = None,
) -> TextGenerationResult:
    """Resolve the authorized API key and execute hosted text generation."""
    if decision.selected_provider_id is None:
        raise HostedTextGenerationError("hosted_text_provider_not_selected")
    api_key = _resolve_hosted_text_api_key(
        provider_store,
        secret_store,
        decision=decision,
        runtime_session_id=runtime_session_id,
        app_id=app_id,
    )
    client = OpenAICompatibleTextGenerationClient(
        provider_id=decision.selected_provider_id,
        api_key=api_key,
        transport=transport,
    )
    return client.generate(request)


def _resolve_hosted_text_api_key(
    provider_store: ProviderStore,
    secret_store: SecretStore,
    *,
    decision: RoutingDecision,
    runtime_session_id: str | None,
    app_id: str | None,
) -> str:
    if decision.provider_credential_binding_id_optional is not None:
        binding = provider_store.get_provider_binding(decision.provider_credential_binding_id_optional)
        try:
            lease = resolve_secret_for_runtime(
                secret_store,
                context=SecretResolutionContext(
                    workspace_id=decision.workspace_id,
                    provider_id=decision.selected_provider_id,
                    runtime_session_id=runtime_session_id,
                    platform_delivery=True,
                    allow_unbound_secret_refs=True,
                ),
                secret_ref=binding.secret_ref,
            )
        except SecretError as error:
            raise HostedTextGenerationError("provider_credential_authorization_missing") from error
        return lease.value
    if decision.provider_secret_binding_id_optional is not None:
        try:
            lease = resolve_secret_for_runtime(
                secret_store,
                context=SecretResolutionContext(
                    workspace_id=decision.workspace_id,
                    provider_id=decision.selected_provider_id,
                    runtime_session_id=runtime_session_id,
                    platform_delivery=True,
                ),
                binding_id=decision.provider_secret_binding_id_optional,
            )
        except SecretError as error:
            raise HostedTextGenerationError("provider_credential_authorization_missing") from error
        return lease.value
    if decision.app_secret_grant_id_optional is not None and app_id is not None:
        try:
            lease = resolve_app_secret_grant(
                secret_store,
                workspace_id=decision.workspace_id,
                app_id=app_id,
                grant_id=decision.app_secret_grant_id_optional,
                action="provider.hosted_text.execute",
                target=provider_secret_target(decision.selected_provider_id or "", "plain_hosted_chat"),
                runtime_session_id=runtime_session_id,
            )
        except SecretError as error:
            raise HostedTextGenerationError("provider_credential_authorization_missing") from error
        return lease.value
    raise HostedTextGenerationError("provider_credential_authorization_missing")


def _openai_payload(request: TextGenerationRequest) -> dict[str, object]:
    messages = []
    if request.system_prompt:
        messages.append({"role": "system", "content": request.system_prompt})
    messages.extend({"role": message.role, "content": message.content} for message in request.messages)
    payload: dict[str, object] = {
        "model": request.model_id,
        "messages": messages,
        "stream": request.stream,
    }
    if request.max_output_tokens is not None:
        payload["max_tokens"] = request.max_output_tokens
    return payload


def _validate_hosted_text_request(request: TextGenerationRequest) -> None:
    content_parts = [request.system_prompt or ""]
    content_parts.extend(message.content for message in request.messages)
    combined = "\n".join(content_parts)
    normalized = combined.lower()
    for marker in _blocked_hosted_text_markers(request):
        if marker.lower() in normalized:
            raise HostedTextGenerationError("hosted_text_request_contains_operational_reference")


def _blocked_hosted_text_markers(request: TextGenerationRequest) -> tuple[str, ...]:
    markers = list(BLOCKED_HOSTED_TEXT_MARKERS)
    workspace_root = str(request.workspace_root or "").strip()
    if workspace_root:
        markers.append(workspace_root.rstrip("/") + "/")
    workspace_id = str(request.workspace_id or "").strip()
    if workspace_id:
        markers.append(f"workspaces/{workspace_id}/")
    return tuple(marker for marker in markers if marker)


def _extract_message_content(payload: dict[str, object] | None) -> str:
    if not isinstance(payload, dict):
        raise HostedTextGenerationError("provider_response_invalid")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise HostedTextGenerationError("provider_response_invalid")
    first = choices[0]
    if not isinstance(first, dict):
        raise HostedTextGenerationError("provider_response_invalid")
    message = first.get("message")
    if not isinstance(message, dict):
        raise HostedTextGenerationError("provider_response_invalid")
    content = message.get("content")
    if not isinstance(content, str):
        raise HostedTextGenerationError("provider_response_invalid")
    return content


def _iter_openai_sse_chunks(response) -> Iterable[str]:
    for raw_line in response:
        line = raw_line.decode("utf-8").strip()
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if data == "[DONE]":
            break
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not isinstance(choices, list) or not choices:
            continue
        delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
        content = delta.get("content") if isinstance(delta, dict) else None
        if isinstance(content, str) and content:
            yield content
