"""Hosted text generation client and transports."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext, suppress
from dataclasses import dataclass, field
import json
import socket
from threading import Event, Lock
from typing import Callable, Iterable, Iterator, Literal, Protocol
from urllib import error as urllib_error
from urllib import parse as urllib_parse
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
MessageContentPartType = Literal["text", "image_url", "inline_data"]

OPENAI_COMPATIBLE_ENDPOINTS = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
}
GOOGLE_AI_STUDIO_ENDPOINT_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
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


class HostedTextCancellation:
    """Thread-safe cancellation and completion handle for one hosted request."""

    def __init__(self) -> None:
        self._cancelled = Event()
        self._finished = Event()
        self._abort_lock = Lock()
        self._abort: Callable[[], object] | None = None

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        """Signal cancellation and abort the currently bound transport response."""
        self._cancelled.set()
        with self._abort_lock:
            abort = self._abort
        if abort is not None:
            with suppress(Exception):
                abort()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise HostedTextGenerationError("provider_cancelled")

    def wait_cancelled(self, timeout: float | None = None) -> bool:
        return self._cancelled.wait(timeout=timeout)

    def mark_finished(self) -> None:
        self._finished.set()

    def wait_finished(self, timeout: float | None = None) -> bool:
        return self._finished.wait(timeout=timeout)

    @contextmanager
    def interruptible(self, abort: Callable[[], object]) -> Iterator[None]:
        """Bind an abort callback without losing a concurrent cancellation."""
        with self._abort_lock:
            self._abort = abort
            cancelled = self.cancelled
        if cancelled:
            try:
                with suppress(Exception):
                    abort()
            finally:
                with self._abort_lock:
                    if self._abort is abort:
                        self._abort = None
            self.raise_if_cancelled()
        try:
            yield
        finally:
            with self._abort_lock:
                if self._abort is abort:
                    self._abort = None


@dataclass(frozen=True)
class TextGenerationContentPart:
    """One multimodal hosted chat content part."""

    type: MessageContentPartType
    text: str | None = None
    image_url: str | None = None
    mime_type: str | None = None
    data: str | None = None
    filename: str | None = None


@dataclass(frozen=True)
class TextGenerationMessage:
    """One hosted chat message."""

    role: MessageRole
    content: str | list[TextGenerationContentPart]


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
    provider_routing: dict[str, object] | None = None


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
        chunk_sink: Callable[[str], None] | None = None,
        sent_sink: Callable[[dict[str, object]], None] | None = None,
        accepted_sink: Callable[[dict[str, object]], None] | None = None,
        cancellation: HostedTextCancellation | None = None,
    ) -> HostedTextTransportResult:
        ...


class TextGenerationClient(Protocol):
    """Client protocol implemented by hosted text providers."""

    def generate(
        self,
        request: TextGenerationRequest,
        *,
        delta_sink: Callable[[str], None] | None = None,
        sent_sink: Callable[[dict[str, object]], None] | None = None,
        accepted_sink: Callable[[dict[str, object]], None] | None = None,
        cancellation: HostedTextCancellation | None = None,
    ) -> TextGenerationResult:
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
        chunk_sink: Callable[[str], None] | None = None,
        sent_sink: Callable[[dict[str, object]], None] | None = None,
        accepted_sink: Callable[[dict[str, object]], None] | None = None,
        cancellation: HostedTextCancellation | None = None,
    ) -> HostedTextTransportResult:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        safe_headers = {
            key: ("<redacted>" if key.lower() in {"authorization", "x-goog-api-key"} else value)
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
        if sent_sink is not None:
            sent_sink({"source": "fake"})
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        if self.timed_out:
            return HostedTextTransportResult(status_code=0, timed_out=True, error=self.error)
        if self.status_code >= 400:
            return HostedTextTransportResult(status_code=self.status_code, payload=self.payload, error=self.error)
        if accepted_sink is not None:
            accepted_sink({"status_code": self.status_code})
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        if stream and self.chunks:
            if chunk_sink is not None:
                for chunk in self.chunks:
                    if cancellation is not None:
                        cancellation.raise_if_cancelled()
                    chunk_sink(chunk)
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
        chunk_sink: Callable[[str], None] | None = None,
        sent_sink: Callable[[dict[str, object]], None] | None = None,
        accepted_sink: Callable[[dict[str, object]], None] | None = None,
        cancellation: HostedTextCancellation | None = None,
    ) -> HostedTextTransportResult:
        body = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(endpoint_url, data=body, headers=headers, method="POST")
        try:
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            if sent_sink is not None:
                sent_sink({})
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            with urllib_request.urlopen(req, timeout=timeout_seconds) as response:
                cancellation_scope = (
                    cancellation.interruptible(response.close) if cancellation is not None else nullcontext()
                )
                with cancellation_scope:
                    if accepted_sink is not None:
                        accepted_sink({"status_code": response.status})
                    if cancellation is not None:
                        cancellation.raise_if_cancelled()
                    if stream:
                        chunks: list[str] = []
                        for chunk in _iter_openai_sse_chunks(response):
                            if cancellation is not None:
                                cancellation.raise_if_cancelled()
                            chunks.append(chunk)
                            if chunk_sink is not None:
                                chunk_sink(chunk)
                        if cancellation is not None:
                            cancellation.raise_if_cancelled()
                        return HostedTextTransportResult(
                            status_code=response.status,
                            chunks=chunks,
                        )
                    try:
                        response_payload = response.read()
                        if cancellation is not None:
                            cancellation.raise_if_cancelled()
                        decoded = json.loads(response_payload.decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        return HostedTextTransportResult(status_code=response.status, error="provider_response_invalid")
                    return HostedTextTransportResult(status_code=response.status, payload=decoded)
        except HostedTextGenerationError:
            raise
        except urllib_error.HTTPError as error:
            return HostedTextTransportResult(status_code=error.code, error=str(error))
        except (TimeoutError, socket.timeout, urllib_error.URLError) as error:
            if isinstance(error, urllib_error.URLError) and not isinstance(error.reason, TimeoutError | socket.timeout):
                return HostedTextTransportResult(status_code=0, error=str(error))
            return HostedTextTransportResult(status_code=0, timed_out=True, error=str(error))
        except Exception as error:
            if cancellation is not None and cancellation.cancelled:
                raise HostedTextGenerationError("provider_cancelled") from error
            raise


class GoogleAIStudioHttpTransport(OpenAICompatibleHttpTransport):
    """HTTP transport that parses Gemini SSE chunks."""

    def send(
        self,
        *,
        endpoint_url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        stream: bool,
        timeout_seconds: int | None,
        chunk_sink: Callable[[str], None] | None = None,
        sent_sink: Callable[[dict[str, object]], None] | None = None,
        accepted_sink: Callable[[dict[str, object]], None] | None = None,
        cancellation: HostedTextCancellation | None = None,
    ) -> HostedTextTransportResult:
        if not stream:
            return super().send(
                endpoint_url=endpoint_url,
                headers=headers,
                payload=payload,
                stream=stream,
                timeout_seconds=timeout_seconds,
                chunk_sink=chunk_sink,
                sent_sink=sent_sink,
                accepted_sink=accepted_sink,
                cancellation=cancellation,
            )
        body = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(endpoint_url, data=body, headers=headers, method="POST")
        try:
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            if sent_sink is not None:
                sent_sink({})
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            with urllib_request.urlopen(req, timeout=timeout_seconds) as response:
                cancellation_scope = (
                    cancellation.interruptible(response.close) if cancellation is not None else nullcontext()
                )
                with cancellation_scope:
                    if accepted_sink is not None:
                        accepted_sink({"status_code": response.status})
                    if cancellation is not None:
                        cancellation.raise_if_cancelled()
                    chunks: list[str] = []
                    for chunk in _iter_gemini_sse_chunks(response):
                        if cancellation is not None:
                            cancellation.raise_if_cancelled()
                        chunks.append(chunk)
                        if chunk_sink is not None:
                            chunk_sink(chunk)
                    if cancellation is not None:
                        cancellation.raise_if_cancelled()
                    return HostedTextTransportResult(
                        status_code=response.status,
                        chunks=chunks,
                    )
        except HostedTextGenerationError:
            raise
        except urllib_error.HTTPError as error:
            return HostedTextTransportResult(status_code=error.code, error=str(error))
        except (TimeoutError, socket.timeout, urllib_error.URLError) as error:
            if isinstance(error, urllib_error.URLError) and not isinstance(error.reason, TimeoutError | socket.timeout):
                return HostedTextTransportResult(status_code=0, error=str(error))
            return HostedTextTransportResult(status_code=0, timed_out=True, error=str(error))
        except Exception as error:
            if cancellation is not None and cancellation.cancelled:
                raise HostedTextGenerationError("provider_cancelled") from error
            raise


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

    def generate(
        self,
        request: TextGenerationRequest,
        *,
        delta_sink: Callable[[str], None] | None = None,
        sent_sink: Callable[[dict[str, object]], None] | None = None,
        accepted_sink: Callable[[dict[str, object]], None] | None = None,
        cancellation: HostedTextCancellation | None = None,
    ) -> TextGenerationResult:
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
            chunk_sink=delta_sink,
            sent_sink=sent_sink,
            accepted_sink=accepted_sink,
            cancellation=cancellation,
        )
        if cancellation is not None:
            cancellation.raise_if_cancelled()
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


class GoogleAIStudioTextGenerationClient:
    """Hosted text generation client for the Gemini API."""

    def __init__(
        self,
        *,
        api_key: str,
        endpoint_root: str | None = None,
        transport: HostedTextTransport | None = None,
    ) -> None:
        self.provider_id = "google-ai-studio"
        self.api_key = api_key
        self.endpoint_root = (endpoint_root or GOOGLE_AI_STUDIO_ENDPOINT_ROOT).rstrip("/")
        self.transport = transport or GoogleAIStudioHttpTransport()

    def generate(
        self,
        request: TextGenerationRequest,
        *,
        delta_sink: Callable[[str], None] | None = None,
        sent_sink: Callable[[dict[str, object]], None] | None = None,
        accepted_sink: Callable[[dict[str, object]], None] | None = None,
        cancellation: HostedTextCancellation | None = None,
    ) -> TextGenerationResult:
        """Generate text through Google AI Studio and normalize Gemini responses."""
        _validate_hosted_text_request(request)
        payload = _gemini_payload(request)
        result = self.transport.send(
            endpoint_url=_gemini_endpoint(self.endpoint_root, model_id=request.model_id, stream=request.stream),
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "text/event-stream" if request.stream else "application/json",
            },
            payload=payload,
            stream=request.stream,
            timeout_seconds=request.timeout_seconds,
            chunk_sink=delta_sink,
            sent_sink=sent_sink,
            accepted_sink=accepted_sink,
            cancellation=cancellation,
        )
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        if result.timed_out:
            raise HostedTextGenerationError("provider_timeout")
        if result.status_code in {401, 403}:
            raise HostedTextGenerationError("provider_credential_rejected")
        if result.status_code == 429:
            raise HostedTextGenerationError("provider_rate_limited")
        if result.status_code >= 400 or result.status_code == 0:
            raise HostedTextGenerationError("provider_http_error")
        deltas = result.chunks if request.stream else [_extract_gemini_text(result.payload)]
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
    delta_sink: Callable[[str], None] | None = None,
    sent_sink: Callable[[dict[str, object]], None] | None = None,
    accepted_sink: Callable[[dict[str, object]], None] | None = None,
    cancellation: HostedTextCancellation | None = None,
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
    client = _hosted_text_generation_client(
        provider_id=decision.selected_provider_id,
        api_key=api_key,
        transport=transport,
    )
    return client.generate(
        request,
        delta_sink=delta_sink,
        sent_sink=sent_sink,
        accepted_sink=accepted_sink,
        cancellation=cancellation,
    )


def _hosted_text_generation_client(
    *,
    provider_id: str,
    api_key: str,
    transport: HostedTextTransport | None = None,
) -> TextGenerationClient:
    if provider_id == "google-ai-studio":
        return GoogleAIStudioTextGenerationClient(api_key=api_key, transport=transport)
    return OpenAICompatibleTextGenerationClient(
        provider_id=provider_id,
        api_key=api_key,
        transport=transport,
    )


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
    messages.extend({"role": message.role, "content": _message_content_payload(message.content)} for message in request.messages)
    payload: dict[str, object] = {
        "model": request.model_id,
        "messages": messages,
        "stream": request.stream,
    }
    if request.max_output_tokens is not None:
        payload["max_tokens"] = request.max_output_tokens
    provider_routing = _openrouter_provider_payload(request.provider_routing)
    if provider_routing:
        payload["provider"] = provider_routing
    return payload


def _gemini_endpoint(endpoint_root: str, *, model_id: str, stream: bool) -> str:
    action = "streamGenerateContent?alt=sse" if stream else "generateContent"
    return f"{endpoint_root}/{urllib_parse.quote(model_id, safe='')}:{action}"


def _gemini_payload(request: TextGenerationRequest) -> dict[str, object]:
    contents = []
    for message in request.messages:
        role = "model" if message.role == "assistant" else "user"
        contents.append({"role": role, "parts": _gemini_content_parts(message.content)})
    payload: dict[str, object] = {"contents": contents}
    if request.system_prompt:
        payload["systemInstruction"] = {"parts": [{"text": request.system_prompt}]}
    generation_config: dict[str, object] = {}
    if request.max_output_tokens is not None:
        generation_config["maxOutputTokens"] = request.max_output_tokens
    if generation_config:
        payload["generationConfig"] = generation_config
    return payload


def _gemini_content_parts(content: str | list[TextGenerationContentPart]) -> list[dict[str, object]]:
    if isinstance(content, str):
        return [{"text": content}]
    parts: list[dict[str, object]] = []
    for part in content:
        if part.type == "text":
            parts.append({"text": part.text or ""})
        elif part.type == "image_url" and part.image_url:
            inline = _gemini_inline_data_part(part.image_url)
            if inline:
                parts.append(inline)
        elif part.type == "inline_data" and part.data:
            parts.append(
                {
                    "inlineData": {
                        "mimeType": part.mime_type or "application/octet-stream",
                        "data": part.data,
                    }
                }
            )
    return parts or [{"text": ""}]


def _gemini_inline_data_part(image_url: str) -> dict[str, object] | None:
    if not image_url.startswith("data:") or "," not in image_url:
        return None
    metadata, data = image_url.split(",", 1)
    mime_type = metadata.removeprefix("data:").split(";", 1)[0] or "application/octet-stream"
    return {"inlineData": {"mimeType": mime_type, "data": data}}


def _openrouter_provider_payload(value: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    mode = str(value.get("mode") or "auto").strip()
    provider_id = str(value.get("provider_id") or "").strip()
    payload: dict[str, object] = {}
    if mode == "prefer" and provider_id:
        payload["order"] = [provider_id]
    elif mode == "only" and provider_id:
        payload["only"] = [provider_id]
    elif mode == "ignore" and provider_id:
        payload["ignore"] = [provider_id]
    if "allow_fallbacks" in value:
        payload["allow_fallbacks"] = bool(value.get("allow_fallbacks"))
    if value.get("require_parameters") is not None:
        payload["require_parameters"] = bool(value.get("require_parameters"))
    if "zdr" in value:
        payload["zdr"] = bool(value.get("zdr"))
    sort = str(value.get("sort") or "").strip()
    if sort in {"price", "throughput", "latency"}:
        payload["sort"] = sort
    data_collection = str(value.get("data_collection") or "").strip()
    if data_collection in {"allow", "deny"}:
        payload["data_collection"] = data_collection
    quantizations = [
        str(item).strip()
        for item in (value.get("quantizations") if isinstance(value.get("quantizations"), list) else [])
        if str(item).strip()
    ]
    if quantizations:
        payload["quantizations"] = quantizations
    return payload


def _message_content_payload(content: str | list[TextGenerationContentPart]) -> str | list[dict[str, object]]:
    if isinstance(content, str):
        return content
    parts: list[dict[str, object]] = []
    for part in content:
        if part.type == "text":
            parts.append({"type": "text", "text": part.text or ""})
        elif part.type == "image_url" and part.image_url:
            parts.append({"type": "image_url", "image_url": {"url": part.image_url}})
        elif part.type == "inline_data" and part.data:
            payload = _openai_inline_data_payload(part)
            if payload:
                parts.append(payload)
    return parts


def _openai_inline_data_payload(part: TextGenerationContentPart) -> dict[str, object] | None:
    mime_type = part.mime_type or "application/octet-stream"
    if mime_type.startswith("image/"):
        return {"type": "image_url", "image_url": {"url": _data_url(mime_type=mime_type, data=part.data or "")}}
    if mime_type.startswith("audio/"):
        return {
            "type": "input_audio",
            "input_audio": {
                "data": part.data or "",
                "format": _audio_format(mime_type=mime_type, filename=part.filename or ""),
            },
        }
    if mime_type.startswith("video/"):
        return {"type": "video_url", "video_url": {"url": _data_url(mime_type=mime_type, data=part.data or "")}}
    return {
        "type": "file",
        "file": {
            "filename": part.filename or "attachment",
            "file_data": _data_url(mime_type=mime_type, data=part.data or ""),
        },
    }


def _data_url(*, mime_type: str, data: str) -> str:
    return f"data:{mime_type};base64,{data}"


def _audio_format(*, mime_type: str, filename: str) -> str:
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension in {"wav", "mp3", "aiff", "aac", "ogg", "flac", "m4a", "pcm16", "pcm24"}:
        return extension
    subtype = mime_type.split("/", 1)[1].split(";", 1)[0].lower() if "/" in mime_type else ""
    return {
        "mpeg": "mp3",
        "mp4": "m4a",
        "x-m4a": "m4a",
        "x-wav": "wav",
        "webm": "webm",
    }.get(subtype, subtype or "wav")


def _validate_hosted_text_request(request: TextGenerationRequest) -> None:
    content_parts = [request.system_prompt or ""]
    for message in request.messages:
        if isinstance(message.content, str):
            content_parts.append(message.content)
        else:
            content_parts.extend(part.text or "" for part in message.content if part.type == "text")
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


def _extract_gemini_text(payload: dict[str, object] | None) -> str:
    if not isinstance(payload, dict):
        raise HostedTextGenerationError("provider_response_invalid")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise HostedTextGenerationError("provider_response_invalid")
    return _extract_gemini_candidate_text(candidates[0])


def _extract_gemini_candidate_text(candidate: object) -> str:
    if not isinstance(candidate, dict):
        raise HostedTextGenerationError("provider_response_invalid")
    content = candidate.get("content")
    if not isinstance(content, dict):
        raise HostedTextGenerationError("provider_response_invalid")
    parts = content.get("parts")
    if not isinstance(parts, list):
        raise HostedTextGenerationError("provider_response_invalid")
    text_parts = [part.get("text") for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)]
    if not text_parts:
        raise HostedTextGenerationError("provider_response_invalid")
    return "".join(text_parts)


def _iter_openai_sse_chunks(response) -> Iterable[str]:
    for raw_line in response:
        try:
            line = raw_line.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise HostedTextGenerationError("provider_response_invalid") from error
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


def _iter_gemini_sse_chunks(response) -> Iterable[str]:
    for raw_line in response:
        try:
            line = raw_line.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise HostedTextGenerationError("provider_response_invalid") from error
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if not data:
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        candidates = payload.get("candidates") if isinstance(payload, dict) else None
        if not isinstance(candidates, list) or not candidates:
            continue
        try:
            text = _extract_gemini_candidate_text(candidates[0])
        except HostedTextGenerationError:
            continue
        if text:
            yield text
