"""Content-preserving OpenAI-compatible provider proxy."""

from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
import socket
from threading import Lock
from typing import Callable, Iterable

from core.model_access.catalog import build_model_access_catalog
from core.model_access.cancellation import (
    CancellationRegistration,
    CancellationSignal,
    raise_if_cancelled,
    register_cleanup,
    submission_fence,
)
from core.model_access.models import ModelAccessScope, ModelApiTransport, ProviderHttpResponse
from core.providers.provider_credentials import resolve_provider_binding
from core.secrets.models import SecretResolutionContext
from core.secrets.secret_resolution import resolve_secret_for_runtime


MAX_MODEL_REQUEST_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class ModelApiResult:
    """HTTP response metadata and exact provider chunks."""

    status: int
    headers: tuple[tuple[str, str], ...]
    chunks: Iterable[bytes]
    close: object


class OpenRouterHttpTransport:
    """Forward exact request bytes to OpenRouter's standard chat endpoint."""

    def open(
        self,
        *,
        provider_id: str,
        body: bytes,
        credential: str,
        cancellation: CancellationSignal,
    ) -> ProviderHttpResponse:
        if provider_id != "openrouter":
            raise ValueError("provider protocol is unavailable")
        raise_if_cancelled(cancellation)
        connection = http.client.HTTPSConnection("openrouter.ai", 443, timeout=60)
        registration = register_cleanup(
            cancellation,
            lambda: _abort_connection(connection),
        )
        try:
            with submission_fence(cancellation):
                connection.request(
                    "POST",
                    "/api/v1/chat/completions",
                    body=body,
                    headers={
                        "Accept": "text/event-stream, application/json",
                        "Accept-Encoding": "identity",
                        "Authorization": f"Bearer {credential}",
                        "Content-Type": "application/json",
                        "User-Agent": "Maverick-Model-Access-Bridge/1",
                    },
                )
            raise_if_cancelled(cancellation)
            response = connection.getresponse()
            if connection.sock is not None:
                connection.sock.settimeout(0.25)
            headers = tuple(
                (name, value)
                for name, value in response.getheaders()
                if name.lower() in {"content-type", "x-request-id"}
            )
        except Exception:
            registration.close()
            _abort_connection(connection)
            raise
        return ProviderHttpResponse(
            status=response.status,
            headers=headers,
            chunks=_response_chunks(response, cancellation),
            close=_registered_close(
                registration,
                lambda: _abort_connection(connection),
            ),
        )


class ModelApiProxy:
    """Validate model authority, resolve a scoped key, and preserve semantic bytes."""

    def __init__(self, state, *, transport: ModelApiTransport | None = None) -> None:
        self.state = state
        self.transport = transport or OpenRouterHttpTransport()

    def open_chat_completion(
        self,
        *,
        scope: ModelAccessScope,
        body: bytes,
        cancellation: CancellationSignal,
    ) -> ProviderHttpResponse:
        raise_if_cancelled(cancellation)
        if not scope.api:
            raise PermissionError("API model access is not authorized")
        if len(body) > MAX_MODEL_REQUEST_BYTES:
            raise ValueError("model request is too large")
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("model request must be JSON") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("model"), str):
            raise ValueError("model request must select a model")
        model_id = payload["model"].strip()
        matches = [
            model
            for model in build_model_access_catalog(self.state, scope).api_models
            if model.available and model.model_id == model_id
        ]
        if len(matches) != 1:
            raise ValueError("selected model is unavailable")
        provider_id = matches[0].provider_id
        credential = self._credential(scope=scope, provider_id=provider_id)
        raise_if_cancelled(cancellation)
        response = self.transport.open(
            provider_id=provider_id,
            body=body,
            credential=credential,
            cancellation=cancellation,
        )
        registration = register_cleanup(cancellation, response.close)
        return ProviderHttpResponse(
            status=response.status,
            headers=response.headers,
            chunks=response.chunks,
            close=_registered_close(registration, response.close),
        )

    def _credential(self, *, scope: ModelAccessScope, provider_id: str) -> str:
        binding = resolve_provider_binding(
            self.state.provider_store,
            provider_id=provider_id,
            workspace_id=scope.workspace_id,
        )
        if binding is None:
            raise PermissionError("provider credential is unavailable")
        lease = resolve_secret_for_runtime(
            self.state.secret_store,
            context=SecretResolutionContext(
                workspace_id=scope.workspace_id,
                app_id=scope.app_id,
                provider_id=provider_id,
                platform_delivery=True,
                allow_unbound_secret_refs=True,
                action="provider.model_access.execute",
            ),
            secret_ref=binding.secret_ref,
            observability_store=getattr(self.state, "observability_store", None),
        )
        return lease.value


def _response_chunks(
    response: http.client.HTTPResponse,
    cancellation: CancellationSignal,
) -> Iterable[bytes]:
    while not cancellation.is_set():
        try:
            chunk = response.read1(64 * 1024)
        except socket.timeout:
            continue
        if not chunk:
            return
        yield chunk


def _abort_connection(connection: http.client.HTTPSConnection) -> None:
    sock = connection.sock
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    connection.close()


def _registered_close(
    registration: CancellationRegistration,
    callback: Callable[[], None],
) -> Callable[[], None]:
    def close() -> None:
        registration.close()
        callback()

    return _once(close)


def _once(callback: Callable[[], None]) -> Callable[[], None]:
    lock = Lock()
    called = False

    def invoke() -> None:
        nonlocal called
        with lock:
            if called:
                return
            called = True
        callback()

    return invoke
