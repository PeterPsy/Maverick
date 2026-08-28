"""Loopback OpenAI-compatible endpoint consumed by native OpenDesign."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

from model_access_client import ModelAccessClient, ModelAccessClientError


MODEL_ACCESS_HOST = "127.0.0.1"
MODEL_ACCESS_PORT = 49491
MODEL_ACCESS_API_KEY = "maverick-local"
MODEL_ACCESS_BASE_URL = f"http://{MODEL_ACCESS_HOST}:{MODEL_ACCESS_PORT}/v1"
MAX_REQUEST_BYTES = 32 * 1024 * 1024


class ModelAccessHttpBridge:
    """Own a standard local endpoint while Core retains provider credentials."""

    def __init__(self, client: ModelAccessClient) -> None:
        handler = _handler_for(client)
        self.server = ThreadingHTTPServer((MODEL_ACCESS_HOST, MODEL_ACCESS_PORT), handler)
        self.server.daemon_threads = True
        self.thread = Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.1},
            name="opendesign-model-access-http",
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _handler_for(client: ModelAccessClient):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._json(200, {"ok": True})
                return
            if self.path != "/v1/models" or not self._authorized():
                self._json(404 if self.path != "/v1/models" else 401, {"error": "not_available"})
                return
            self._proxy("GET", self.path, b"")

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/chat/completions" or not self._authorized():
                self._json(404 if self.path != "/v1/chat/completions" else 401, {"error": "not_available"})
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._json(400, {"error": "invalid_request"})
                return
            if length < 0 or length > MAX_REQUEST_BYTES:
                self._json(413, {"error": "request_too_large"})
                return
            body = self.rfile.read(length)
            if len(body) != length:
                self._json(400, {"error": "invalid_request"})
                return
            self._proxy("POST", self.path, body)

        def _authorized(self) -> bool:
            return self.headers.get("Authorization") == f"Bearer {MODEL_ACCESS_API_KEY}"

        def _proxy(self, method: str, path: str, body: bytes) -> None:
            try:
                connection, response = client.open(method, path, body=body)
            except ModelAccessClientError:
                self._json(503, {"error": "model_access_unavailable"})
                return
            try:
                self.send_response(response.status)
                for name, value in response.getheaders():
                    if name.lower() in {"content-type", "x-request-id"}:
                        self.send_header(name, value)
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                while True:
                    chunk = response.read1(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                connection.close()

        def _json(self, status: int, payload: dict[str, object]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def log_message(self, _format: str, *_args) -> None:
            return

    return Handler
