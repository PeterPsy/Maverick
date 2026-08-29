"""Bounded HTTP framing for the private model-access Unix socket."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import logging
import select
import socket
import socketserver
import struct
from threading import Event, Thread
from typing import Iterable, Protocol

from core.model_access.cli_authorization import authorize_cli_invocation
from core.model_access.models import (
    CliFrame,
    ModelAccessCatalog,
    ModelAccessScope,
    ModelCliExecutor,
    ProviderHttpResponse,
)


MAX_HEADER_BYTES = 64 * 1024
MAX_CLI_HEADER_BYTES = 16 * 1024
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Request:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes


class ModelApiProxyProtocol(Protocol):
    def open_chat_completion(
        self,
        *,
        scope: ModelAccessScope,
        body: bytes,
        cancellation: Event,
    ) -> ProviderHttpResponse: ...


class ModelAccessBrokerProtocol(Protocol):
    """Broker behavior required by the private wire server."""

    state: object
    api_proxy: ModelApiProxyProtocol
    cli_executor: ModelCliExecutor

    def authorize(
        self,
        authorization: str,
        *,
        cancellation: Event | None = None,
    ) -> ModelAccessScope: ...

    def release_authorization(
        self,
        authorization: str,
        *,
        cancellation: Event | None,
    ) -> None: ...

    def catalog(self, scope: ModelAccessScope) -> ModelAccessCatalog: ...


class ThreadingUnixModelAccessServer(socketserver.ThreadingUnixStreamServer):
    """Thread-per-request Unix server owned by one broker lifecycle."""

    daemon_threads = True

    def __init__(self, path: str, broker: ModelAccessBrokerProtocol) -> None:
        self.broker = broker
        super().__init__(path, _BrokerRequestHandler)


class _BrokerRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        broker: ModelAccessBrokerProtocol = self.server.broker  # type: ignore[attr-defined]
        cancellation = Event()
        disconnect_stop = Event()
        authorization = ""
        try:
            request = _read_request(self.rfile)
            authorization = request.headers.get("authorization", "")
            scope = broker.authorize(authorization, cancellation=cancellation)
            Thread(
                target=_watch_disconnect,
                args=(self.connection, cancellation, disconnect_stop),
                name="maverick-model-access-disconnect",
                daemon=True,
            ).start()
            if request.method == "GET" and request.path == "/maverick/v1/catalog":
                _send_json(self.wfile, 200, broker.catalog(scope).public_payload())
                return
            if request.method == "GET" and request.path == "/v1/models":
                catalog = broker.catalog(scope)
                _send_json(
                    self.wfile,
                    200,
                    {
                        "object": "list",
                        "data": [
                            {
                                "id": model.model_id,
                                "object": "model",
                                "owned_by": model.provider_id,
                            }
                            for model in catalog.api_models
                            if model.available
                        ],
                    },
                )
                return
            if request.method == "POST" and request.path == "/v1/chat/completions":
                response = broker.api_proxy.open_chat_completion(
                    scope=scope,
                    body=request.body,
                    cancellation=cancellation,
                )
                try:
                    _send_stream_headers(self.wfile, response.status, response.headers)
                    for chunk in response.chunks:
                        if cancellation.is_set():
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                finally:
                    cancellation.set()
                    response.close()
                return
            if request.method == "POST" and request.path == "/maverick/v1/cli/codex/exec":
                argv = _decode_string_list_header(
                    request.headers.get("x-maverick-cli-argv", "")
                )
                authorize_cli_invocation(
                    broker.catalog(scope),
                    provider_id="codex",
                    argv=argv,
                )
                frames = broker.cli_executor.execute(
                    scope=scope,
                    provider_id="codex",
                    argv=argv,
                    cwd=_decode_string_header(request.headers.get("x-maverick-cli-cwd", "")),
                    stdin=request.body,
                    cancellation=cancellation,
                )
                _send_stream_headers(
                    self.wfile,
                    200,
                    (("Content-Type", "application/x-maverick-cli-frames"),),
                )
                _send_cli_frames(self.wfile, frames, cancellation)
                return
            _send_json(self.wfile, 404, {"error": "model_access_route_not_found"})
        except PermissionError:
            _send_json_safely(self.wfile, 403, {"error": "model_access_denied"})
        except (ValueError, json.JSONDecodeError):
            _send_json_safely(self.wfile, 400, {"error": "model_access_request_invalid"})
        except Exception:
            _send_json_safely(self.wfile, 502, {"error": "model_access_unavailable"})
        finally:
            cancellation.set()
            disconnect_stop.set()
            broker.release_authorization(
                authorization,
                cancellation=cancellation,
            )


def _read_request(stream) -> _Request:
    request_line = stream.readline(MAX_HEADER_BYTES + 1)
    if not request_line or len(request_line) > MAX_HEADER_BYTES:
        raise ValueError("model-access request line is invalid")
    try:
        method, path, version = request_line.decode("ascii").strip().split(" ")
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("model-access request line is invalid") from error
    if version not in {"HTTP/1.0", "HTTP/1.1"} or "?" in path:
        raise ValueError("model-access HTTP version or path is invalid")
    headers: dict[str, str] = {}
    consumed = len(request_line)
    while True:
        line = stream.readline(MAX_HEADER_BYTES + 1)
        consumed += len(line)
        if consumed > MAX_HEADER_BYTES or not line:
            raise ValueError("model-access headers are invalid")
        if line in {b"\r\n", b"\n"}:
            break
        try:
            name, value = line.decode("latin1").split(":", 1)
        except ValueError as error:
            raise ValueError("model-access header is invalid") from error
        key = name.strip().lower()
        if not key or key in headers:
            raise ValueError("model-access header is invalid")
        headers[key] = value.strip()
    try:
        length = int(headers.get("content-length", "0"))
    except ValueError as error:
        raise ValueError("model-access content length is invalid") from error
    if length < 0 or length > 32 * 1024 * 1024:
        raise ValueError("model-access content length is invalid")
    body = stream.read(length)
    if len(body) != length:
        raise ValueError("model-access request body is incomplete")
    return _Request(method=method, path=path, headers=headers, body=body)


def _send_json(stream, status: int, payload: dict[str, object]) -> None:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    _send_headers(
        stream,
        status,
        (("Content-Type", "application/json"), ("Content-Length", str(len(body)))),
    )
    stream.write(body)
    stream.flush()


def _send_json_safely(stream, status: int, payload: dict[str, object]) -> None:
    try:
        _send_json(stream, status, payload)
    except (BrokenPipeError, OSError):
        pass


def _send_stream_headers(stream, status: int, headers: Iterable[tuple[str, str]]) -> None:
    safe = tuple(
        (name, value)
        for name, value in headers
        if name.lower() in {"content-type", "x-request-id"}
        and "\r" not in value
        and "\n" not in value
    )
    _send_headers(stream, status, safe)


def _send_headers(stream, status: int, headers: Iterable[tuple[str, str]]) -> None:
    reason = {
        200: "OK",
        400: "Bad Request",
        403: "Forbidden",
        404: "Not Found",
        502: "Bad Gateway",
    }.get(status, "Response")
    stream.write(f"HTTP/1.1 {status} {reason}\r\n".encode("ascii"))
    for name, value in headers:
        stream.write(f"{name}: {value}\r\n".encode("latin1"))
    stream.write(b"Connection: close\r\n\r\n")
    stream.flush()


def _send_cli_frames(stream, frames: Iterable[CliFrame], cancellation: Event) -> None:
    codes = {"stdout": b"O", "stderr": b"E", "exit": b"X"}
    iterator = iter(frames)
    try:
        for frame in iterator:
            if cancellation.is_set():
                return
            stream.write(codes[frame.channel] + struct.pack("!I", len(frame.payload)) + frame.payload)
            stream.flush()
    except (BrokenPipeError, OSError):
        cancellation.set()
    except Exception:
        logger.exception("Native CLI model transport failed before completing its framed stream.")
        try:
            message = b"Codex model transport failed\n"
            stream.write(b"E" + struct.pack("!I", len(message)) + message)
            payload = b'{"exit_code":1}'
            stream.write(b"X" + struct.pack("!I", len(payload)) + payload)
            stream.flush()
        except (BrokenPipeError, OSError):
            cancellation.set()
    finally:
        close = getattr(iterator, "close", None)
        if callable(close):
            close()


def _decode_string_list_header(value: str) -> tuple[str, ...]:
    payload = json.loads(_decode_header(value))
    if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
        raise ValueError("CLI argv header is invalid")
    return tuple(payload)


def _decode_string_header(value: str) -> str:
    decoded = _decode_header(value)
    if len(decoded) > MAX_CLI_HEADER_BYTES:
        raise ValueError("CLI cwd header is invalid")
    return decoded


def _decode_header(value: str) -> str:
    if not value or len(value) > MAX_CLI_HEADER_BYTES:
        raise ValueError("CLI bridge header is invalid")
    try:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("CLI bridge header is invalid") from error


def _watch_disconnect(connection: socket.socket, cancellation: Event, stop: Event) -> None:
    while not stop.is_set() and not cancellation.is_set():
        try:
            readable, _writable, _exceptional = select.select([connection], [], [], 0.2)
            if not readable:
                continue
            data = connection.recv(1, socket.MSG_PEEK)
        except OSError:
            cancellation.set()
            return
        if not data:
            cancellation.set()
            return
