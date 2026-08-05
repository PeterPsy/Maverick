"""Core-handled routes for app-owned sidecar proxy policies."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
from pathlib import Path
from time import monotonic
from typing import Any, Iterable

from core.api.app_event_publication import declared_data_event_resources, publish_declared_app_events
from core.api.http import (
    HttpRequestError,
    StartResponse,
    json_response,
    max_json_body_bytes,
    query_params,
    read_request_body_bytes,
    status_line,
    text_response,
)
from core.api.platform_state import PlatformState
from core.api.provider_api import provider_model_settings_payload, provider_payload
from core.apps.dependencies import resolve_app_dependencies
from core.apps.errors import AppHostingError
from core.apps.models import HttpSidecarSpec, ParsedAppContract
from core.apps.runtime_requests import apply_app_runtime_requests
from core.identity.models import UserRecord
from core.providers.service import resolve_workspace_provider_status
from core.shared.entrypoints import EntrypointShutdownController, run_json_entrypoint
from core.workspaces.paths import workspace_paths


AsgiReceive = Any
AsgiSend = Any
_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
_LOGGER = logging.getLogger(__name__)
_RUNTIME_STREAM_BATCH_SIZE = 64
_RUNTIME_STREAM_POLL_SECONDS = 0.1
_RUNTIME_STREAM_KEEPALIVE_SECONDS = 15.0
_RUNTIME_STREAM_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "timed-out"}


@dataclass(frozen=True)
class SidecarCoreRouteContext:
    """Resolved app and sidecar data needed by a core-handled sidecar route."""

    source_root: Path
    data_root: str
    parsed: ParsedAppContract
    sidecar: HttpSidecarSpec
    proxy_path: str


def handle_core_sidecar_route(
    state: PlatformState,
    *,
    environ: dict,
    workspace_id: str,
    app_id: str,
    user: UserRecord | None,
    context: SidecarCoreRouteContext,
    start_path: Path,
    start_response: StartResponse,
    shutdown_controller: EntrypointShutdownController | None,
    logger,
) -> Iterable[bytes]:
    """Invoke an app backend for one route declared as handled_by_core."""
    try:
        body = _sidecar_core_json_body_from_wsgi(environ)
        result = _invoke_core_sidecar_route(
            state,
            workspace_id=workspace_id,
            app_id=app_id,
            user=user,
            context=context,
            method=str(environ.get("REQUEST_METHOD") or "GET").upper(),
            query=query_params(environ),
            headers=_core_sidecar_request_headers_from_wsgi(environ),
            body=body,
            start_path=start_path,
            shutdown_controller=shutdown_controller,
        )
    except HttpRequestError as error:
        return json_response(start_response, {"error": error.error}, status=error.status)
    except AppHostingError as error:
        logger.warning("App `%s` handled sidecar route failed: %s", app_id, error)
        return json_response(
            start_response,
            {"error": "sidecar_core_route_failed", "detail": str(error)},
            status=status_line(500),
        )
    except Exception:
        logger.exception("App `%s` handled sidecar route crashed.", app_id)
        return json_response(start_response, {"error": "sidecar_core_route_failed"}, status=status_line(500))
    try:
        return _core_sidecar_wsgi_response(result, start_response=start_response)
    except AppHostingError as error:
        logger.warning("App `%s` returned an invalid handled sidecar response: %s", app_id, error)
        return json_response(
            start_response,
            {"error": "sidecar_core_route_failed", "detail": str(error)},
            status=status_line(500),
        )


async def handle_core_sidecar_route_asgi(
    state: PlatformState,
    *,
    scope: dict[str, Any],
    receive: AsgiReceive,
    send: AsgiSend,
    workspace_id: str,
    app_id: str,
    user: UserRecord | None,
    context: SidecarCoreRouteContext,
    start_path: Path,
    shutdown_controller: EntrypointShutdownController | None,
    logger,
    response_headers: list[tuple[str, str]] | None = None,
) -> None:
    """ASGI variant of handle_core_sidecar_route."""
    try:
        body = await _sidecar_core_json_body_from_asgi(scope, receive)
        result = await asyncio.to_thread(
            _invoke_core_sidecar_route,
            state,
            workspace_id=workspace_id,
            app_id=app_id,
            user=user,
            context=context,
            method=str(scope.get("method") or "GET").upper(),
            query=_asgi_query_params(scope),
            headers=_core_sidecar_request_headers_from_asgi(scope),
            body=body,
            start_path=start_path,
            shutdown_controller=shutdown_controller,
        )
    except HttpRequestError as error:
        await _send_asgi_json(send, {"error": error.error}, status=error.status, headers=response_headers)
        return
    except AppHostingError as error:
        logger.warning("App `%s` handled ASGI sidecar route failed: %s", app_id, error)
        await _send_asgi_json(
            send,
            {"error": "sidecar_core_route_failed", "detail": str(error)},
            status=status_line(500),
            headers=response_headers,
        )
        return
    except Exception:
        logger.exception("App `%s` handled ASGI sidecar route crashed.", app_id)
        await _send_asgi_json(
            send,
            {"error": "sidecar_core_route_failed"},
            status=status_line(500),
            headers=response_headers,
        )
        return
    try:
        runtime_stream = _pop_runtime_stream_response(result)
    except AppHostingError as error:
        logger.warning("App `%s` returned an invalid ASGI sidecar response: %s", app_id, error)
        await _send_asgi_json(
            send,
            {"error": "sidecar_core_route_failed", "detail": str(error)},
            status=status_line(500),
            headers=response_headers,
        )
        return
    if runtime_stream is not None:
        await _send_runtime_stream_asgi(
            state,
            receive=receive,
            send=send,
            descriptor=runtime_stream,
            workspace_id=workspace_id,
            app_id=app_id,
            user=user,
            context=context,
            start_path=start_path,
            shutdown_controller=shutdown_controller,
            response_headers=response_headers,
        )
        return
    await _send_core_sidecar_asgi_response(send, result, headers=response_headers)


def _invoke_core_sidecar_route(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    user: UserRecord | None,
    context: SidecarCoreRouteContext,
    method: str,
    query: dict[str, str],
    headers: dict[str, str],
    body: dict[str, Any],
    start_path: Path,
    shutdown_controller: EntrypointShutdownController | None,
) -> dict[str, Any]:
    backend = context.parsed.contract.entrypoints.backend
    if backend is None:
        raise AppHostingError(f"App `{app_id}` cannot handle sidecar route `{context.proxy_path}` without a backend.")
    paths = workspace_paths(workspace_id, start_path=start_path)
    from core.api.sidecar_entrypoint_invocation import run_json_entrypoint_with_sidecars

    binding = state.app_store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    result = run_json_entrypoint_with_sidecars(
        context.source_root / backend,
        payload={
            "surface": "sidecar_core_handler",
            "workspace_id": workspace_id,
            "app_id": app_id,
            "workspace_root": str(paths.root),
            "data_root": context.data_root,
            "uploaded_storage_root": str(paths.uploaded_storage),
            "generated_storage_root": str(paths.generated_storage),
            "sidecar_id": context.sidecar.service_id,
            "route_path": context.proxy_path,
            "method": method,
            "query": query,
            "headers": headers,
            "body": body,
            "effective_mode": "sandbox",
            "platform_role": None if user is None else user.platform_role,
            "user_id": None if user is None else user.user_id,
            "app_dependencies": _app_dependencies_payload(
                state,
                workspace_id=workspace_id,
                app_id=app_id,
                user=user,
                start_path=start_path,
            ),
            "provider_proxy": _provider_proxy_payload(
                state,
                workspace_id=workspace_id,
                enabled=context.parsed.contract.permissions.providers.model_proxy,
            ),
            "runtime_session_id": "",
            "turn_id": "",
            "app_secrets": {},
            "app_secret_errors": [],
        },
        cwd=context.source_root,
        binding=binding,
        parsed=context.parsed,
        surface="backend",
        start_path=start_path,
        actor_user_id=None if user is None else user.user_id,
        runtime_session_id=None,
        observability_store=state.observability_store,
        timeout_seconds=int(context.parsed.contract.hook_timeouts.backend_seconds),
        shutdown_controller=shutdown_controller,
    )
    publish_declared_app_events(
        state.app_event_bus,
        result,
        workspace_id=workspace_id,
        app_id=app_id,
        declared_resources=declared_data_event_resources(context.parsed.contract.capabilities.data_events),
        remove_from_result=True,
    )
    apply_app_runtime_requests(
        state,
        result=result,
        workspace_id=workspace_id,
        app_id=app_id,
        source_root=context.source_root,
        backend_entrypoint=backend,
        data_root=context.data_root,
        parsed=context.parsed,
        start_path=start_path,
        actor_user_id=None if user is None else user.user_id,
    )
    return result


def _sidecar_core_json_body_from_wsgi(environ: dict) -> dict[str, Any]:
    raw = read_request_body_bytes(environ)
    return _decode_sidecar_core_json_body(raw, content_type=str(environ.get("CONTENT_TYPE") or ""))


async def _sidecar_core_json_body_from_asgi(scope: dict[str, Any], receive: AsgiReceive) -> dict[str, Any]:
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message.get("type") != "http.request":
            break
        chunk = bytes(message.get("body") or b"")
        size += len(chunk)
        if size > max_json_body_bytes():
            raise HttpRequestError("request_body_too_large", "413 Payload Too Large")
        chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return _decode_sidecar_core_json_body(b"".join(chunks), content_type=_asgi_header(scope, "content-type"))


def _decode_sidecar_core_json_body(raw: bytes, *, content_type: str) -> dict[str, Any]:
    if not raw:
        return {}
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized and normalized != "application/json":
        raise HttpRequestError("sidecar_core_route_requires_json", "400 Bad Request")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HttpRequestError("invalid_json_body", "400 Bad Request") from error
    if not isinstance(payload, dict):
        raise HttpRequestError("json_body_must_be_object", "400 Bad Request")
    return payload


def _core_sidecar_wsgi_response(result: dict[str, Any], *, start_response: StartResponse) -> Iterable[bytes]:
    if _pop_runtime_stream_response(result) is not None:
        return json_response(
            start_response,
            {"error": "runtime_stream_requires_asgi"},
            status=status_line(426),
        )
    status_code = int(result.get("status_code", 200))
    if "json" in result and isinstance(result.get("json"), dict):
        return json_response(start_response, result["json"], status=status_line(status_code))
    if "body" in result:
        return text_response(start_response, str(result["body"]), status=status_line(status_code))
    return json_response(start_response, result, status=status_line(status_code))


async def _send_core_sidecar_asgi_response(
    send: AsgiSend,
    result: dict[str, Any],
    *,
    headers: list[tuple[str, str]] | None = None,
) -> None:
    status_code = int(result.get("status_code", 200))
    if "json" in result and isinstance(result.get("json"), dict):
        body = json.dumps(result["json"], indent=2).encode("utf-8")
        content_type = b"application/json; charset=utf-8"
    elif "body" in result:
        body = str(result["body"]).encode("utf-8")
        content_type = b"text/plain; charset=utf-8"
    else:
        body = json.dumps(result, indent=2).encode("utf-8")
        content_type = b"application/json; charset=utf-8"
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", content_type),
                (b"content-length", str(len(body)).encode("ascii")),
                *[(name.lower().encode("latin1"), value.encode("latin1")) for name, value in (headers or [])],
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


def _pop_runtime_stream_response(result: dict[str, Any]) -> dict[str, Any] | None:
    response_json = result.get("json") if isinstance(result.get("json"), dict) else None
    value = result.pop("runtime_stream_response", None)
    if value is None and response_json is not None:
        value = response_json.pop("runtime_stream_response", None)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise AppHostingError("Runtime stream response descriptor must be an object.")
    return value


async def _send_runtime_stream_asgi(
    state: PlatformState,
    *,
    receive: AsgiReceive,
    send: AsgiSend,
    descriptor: dict[str, Any],
    workspace_id: str,
    app_id: str,
    user: UserRecord | None,
    context: SidecarCoreRouteContext,
    start_path: Path,
    shutdown_controller: EntrypointShutdownController | None,
    response_headers: list[tuple[str, str]] | None,
) -> None:
    stream_id = str(descriptor.get("stream_id") or "").strip()
    callback = descriptor.get("callback") if isinstance(descriptor.get("callback"), dict) else {}
    action = str(callback.get("action") or "").strip()
    if not stream_id or not action:
        raise AppHostingError("Runtime stream response requires stream_id and callback.action.")
    try:
        status_code = int(descriptor.get("status_code") or 200)
    except (TypeError, ValueError) as exc:
        raise AppHostingError("Runtime stream response status_code is invalid.") from exc
    if status_code < 200 or status_code >= 300:
        raise AppHostingError("Runtime stream response status_code must be successful.")
    try:
        after_sequence = max(0, int(descriptor.get("after_sequence") or 0))
    except (TypeError, ValueError) as exc:
        raise AppHostingError("Runtime stream after_sequence must be a non-negative integer.") from exc
    stream = state.runtime_store.get_app_stream(
        stream_id,
        workspace_id=workspace_id,
        source_app_id=app_id,
    )
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"text/event-stream; charset=utf-8"),
                (b"cache-control", b"no-cache, no-store"),
                (b"x-accel-buffering", b"no"),
                *[
                    (name.lower().encode("latin1"), value.encode("latin1"))
                    for name, value in (response_headers or [])
                    if name.lower() not in {"content-type", "content-length", "cache-control"}
                ],
            ],
        }
    )
    last_delivery = monotonic()
    while True:
        events = state.runtime_store.read_app_stream_events(
            stream_id,
            workspace_id=workspace_id,
            source_app_id=app_id,
            after_sequence=after_sequence,
            limit=_RUNTIME_STREAM_BATCH_SIZE,
        )
        if events:
            translated = await asyncio.to_thread(
                _invoke_runtime_stream_translation,
                state,
                workspace_id=workspace_id,
                app_id=app_id,
                user=user,
                context=context,
                callback=callback,
                events=events,
                start_path=start_path,
                shutdown_controller=shutdown_controller,
            )
            expected_ack = events[-1].sequence
            if int(translated.get("ack_sequence") or -1) != expected_ack:
                raise AppHostingError("Runtime stream translator did not acknowledge the complete ordered batch.")
            chunks = translated.get("sse_events")
            if not isinstance(chunks, list):
                raise AppHostingError("Runtime stream translator must return sse_events.")
            for chunk in chunks:
                encoded = _encode_sse_event(chunk)
                await send({"type": "http.response.body", "body": encoded, "more_body": True})
            after_sequence = expected_ack
            last_delivery = monotonic()
            if any(event.terminal for event in events):
                break
            continue
        stream = state.runtime_store.get_app_stream(
            stream_id,
            workspace_id=workspace_id,
            source_app_id=app_id,
        )
        if stream.status in _RUNTIME_STREAM_TERMINAL_STATUSES:
            break
        if monotonic() - last_delivery >= _RUNTIME_STREAM_KEEPALIVE_SECONDS:
            await send({"type": "http.response.body", "body": b": keepalive\n\n", "more_body": True})
            last_delivery = monotonic()
        try:
            message = await asyncio.wait_for(receive(), timeout=_RUNTIME_STREAM_POLL_SECONDS)
        except TimeoutError:
            continue
        if message.get("type") == "http.disconnect":
            return
    await send({"type": "http.response.body", "body": b"", "more_body": False})


def _invoke_runtime_stream_translation(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    user: UserRecord | None,
    context: SidecarCoreRouteContext,
    callback: dict[str, Any],
    events: list,
    start_path: Path,
    shutdown_controller: EntrypointShutdownController | None,
) -> dict[str, Any]:
    backend = context.parsed.contract.entrypoints.backend
    if backend is None:
        raise AppHostingError(f"App `{app_id}` cannot translate a runtime stream without a backend.")
    callback_payload = callback.get("payload") if isinstance(callback.get("payload"), dict) else {}
    paths = workspace_paths(workspace_id, start_path=start_path)
    result = run_json_entrypoint(
        context.source_root / backend,
        payload={
            "surface": "runtime_stream_translation",
            "workspace_id": workspace_id,
            "app_id": app_id,
            "workspace_root": str(paths.root),
            "data_root": context.data_root,
            "uploaded_storage_root": str(paths.uploaded_storage),
            "generated_storage_root": str(paths.generated_storage),
            "platform_role": None if user is None else user.platform_role,
            "user_id": None if user is None else user.user_id,
            "body": {
                **callback_payload,
                "action": str(callback.get("action") or ""),
                "events": [
                    {
                        "stream_id": event.stream_id,
                        "sequence": event.sequence,
                        "event_id": event.event_id,
                        "event_type": event.event_type,
                        "timestamp": event.created_at.isoformat(),
                        "payload": event.payload,
                        "terminal": event.terminal,
                    }
                    for event in events
                ],
            },
            "runtime_session_id": events[-1].session_id if events else "",
            "turn_id": events[-1].turn_id if events else "",
            "app_secrets": {},
            "app_secret_errors": [],
        },
        cwd=context.source_root,
        timeout_seconds=int(context.parsed.contract.hook_timeouts.backend_seconds),
        shutdown_controller=shutdown_controller,
    )
    response = result.get("json") if isinstance(result.get("json"), dict) else result
    if not isinstance(response, dict) or int(result.get("status_code", 200)) >= 400:
        raise AppHostingError("Runtime stream translator failed.")
    return response


def _encode_sse_event(value: object) -> bytes:
    if not isinstance(value, dict):
        raise AppHostingError("Runtime stream SSE event must be an object.")
    event_id = str(value.get("id") or "").strip()
    event_name = str(value.get("event") or "message").strip()
    data = value.get("data")
    if not event_id or any(character in event_id for character in "\r\n\0"):
        raise AppHostingError("Runtime stream SSE id is invalid.")
    if not event_name or any(character in event_name for character in "\r\n\0"):
        raise AppHostingError("Runtime stream SSE event name is invalid.")
    encoded_data = json.dumps(data if isinstance(data, dict) else {}, ensure_ascii=True, separators=(",", ":"))
    return f"id: {event_id}\nevent: {event_name}\ndata: {encoded_data}\n\n".encode("utf-8")


def _app_dependencies_payload(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    user: UserRecord | None,
    start_path: Path,
) -> dict[str, object]:
    try:
        return resolve_app_dependencies(
            state.app_store,
            workspace_id=workspace_id,
            consumer_app_id=app_id,
            user=user,
            workspace_store=state.workspace_store,
            start_path=start_path,
        )
    except Exception:
        _LOGGER.exception("App `%s` dependency resolution failed in workspace `%s`.", app_id, workspace_id)
        return {"workspace_id": workspace_id, "consumer_app_id": app_id, "status": "blocked", "dependencies": []}


def _provider_proxy_payload(
    state: PlatformState,
    *,
    workspace_id: str,
    enabled: bool,
) -> dict[str, object]:
    if not enabled:
        return {
            "enabled": False,
            "workspace_id": workspace_id,
            "credential_source": "none",
            "deliver_secrets_to_app": False,
        }
    try:
        status = resolve_workspace_provider_status(state.provider_store, workspace_id=workspace_id)
    except Exception:
        _LOGGER.exception("Provider proxy status resolution failed in workspace `%s`.", workspace_id)
        return {
            "enabled": True,
            "workspace_id": workspace_id,
            "configured": False,
            "active_provider": None,
            "model_settings": None,
            "blocked_reason": "provider_unavailable",
            "blocked_detail": "Provider status could not be resolved.",
            "credential_source": "core-vault",
            "deliver_secrets_to_app": False,
        }
    active_provider = None if status.active_provider is None else provider_payload(status.active_provider)
    model_settings = (
        None
        if status.active_provider is None
        else provider_model_settings_payload(status.active_provider, status.selection)
    )
    return {
        "enabled": True,
        "workspace_id": workspace_id,
        "configured": status.configured,
        "active_provider": active_provider,
        "model_settings": model_settings,
        "blocked_reason": status.blocked_reason,
        "blocked_detail": status.blocked_detail,
        "credential_source": "core-vault",
        "deliver_secrets_to_app": False,
    }


def _core_sidecar_request_headers_from_wsgi(environ: dict) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in environ.items():
        if key.startswith("HTTP_"):
            name = key.removeprefix("HTTP_").replace("_", "-").lower()
            _add_safe_core_sidecar_header(headers, name, value)
    if environ.get("CONTENT_TYPE"):
        _add_safe_core_sidecar_header(headers, "content-type", environ["CONTENT_TYPE"])
    return headers


def _core_sidecar_request_headers_from_asgi(scope: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw_name, raw_value in scope.get("headers", []):
        name = raw_name.decode("latin1").replace("_", "-").lower()
        _add_safe_core_sidecar_header(headers, name, raw_value.decode("latin1"))
    return headers


def _add_safe_core_sidecar_header(headers: dict[str, str], name: str, value: Any) -> None:
    lowered = name.lower()
    if lowered in _HOP_BY_HOP_HEADERS or lowered in {"authorization", "cookie", "x-api-key"}:
        return
    if lowered not in {"accept", "content-type", "last-event-id", "origin", "referer", "user-agent"}:
        return
    text = str(value or "").strip()
    if not text or any(char in text for char in "\r\n\0"):
        return
    headers[lowered] = text[:4096]


def _asgi_query_params(scope: dict[str, Any]) -> dict[str, str]:
    return query_params({"QUERY_STRING": bytes(scope.get("query_string") or b"").decode("latin1")})


def _asgi_header(scope: dict[str, Any], header_name: str) -> str:
    expected = header_name.lower().encode("latin1")
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name.lower() == expected:
            return raw_value.decode("latin1")
    return ""


async def _send_asgi_json(
    send: AsgiSend,
    payload: dict[str, Any],
    *,
    status: str,
    headers: list[tuple[str, str]] | None = None,
) -> None:
    body = json.dumps(payload, indent=2).encode("utf-8")
    status_code = int(status.split(" ", 1)[0])
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
                *[(name.lower().encode("latin1"), value.encode("latin1")) for name, value in (headers or [])],
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})
