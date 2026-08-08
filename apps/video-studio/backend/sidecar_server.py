"""Governed read-only HTTP sidecar for Video Studio foundation inspection."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from typing import Any
from urllib.parse import urlsplit

from service import handle_foundation_action


_ACTION_BY_PATH = {
    "/health": "health",
    "/schema": "schema",
    "/status": "status",
}


class FoundationRequestHandler(BaseHTTPRequestHandler):
    """Serve only the exact GET routes allowlisted by the app contract."""

    server_version = "VideoStudioFoundation/1"
    sys_version = ""

    def do_GET(self) -> None:  # noqa: N802 - standard-library handler API
        if not self._authorized():
            self._json(401, {"ok": False, "error": {"code": "unauthorized"}})
            return
        action = _ACTION_BY_PATH.get(urlsplit(self.path).path)
        if action is None:
            self._json(404, {"ok": False, "error": {"code": "not_found"}})
            return
        status_code, payload = handle_foundation_action(
            os.environ.get("VIDEO_STUDIO_DATA_ROOT", ""),
            action,
        )
        payload["surface"] = "sidecar"
        self._json(status_code, payload)

    def log_message(self, format: str, *args: Any) -> None:
        """Keep request values out of process logs."""

    def _authorized(self) -> bool:
        expected_token = os.environ.get("VIDEO_STUDIO_SIDECAR_TOKEN", "")
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {expected_token}"
        return bool(expected_token) and hmac.compare_digest(supplied, expected)

    def _json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)


class FoundationServer(ThreadingHTTPServer):
    """Bounded lifecycle wrapper for concurrent platform health requests."""

    daemon_threads = True
    allow_reuse_address = False


def main() -> None:
    host = os.environ.get("VIDEO_STUDIO_SIDECAR_HOST", "")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Video Studio sidecar requires a loopback bind host.")
    try:
        port = int(os.environ.get("VIDEO_STUDIO_SIDECAR_PORT", "0"))
    except ValueError as error:
        raise SystemExit("Video Studio sidecar port is invalid.") from error
    if not 1 <= port <= 65535:
        raise SystemExit("Video Studio sidecar port is invalid.")
    if not os.environ.get("VIDEO_STUDIO_SIDECAR_TOKEN"):
        raise SystemExit("Video Studio sidecar technical token is missing.")
    if not os.environ.get("VIDEO_STUDIO_DATA_ROOT"):
        raise SystemExit("Video Studio sidecar data root is missing.")
    FoundationServer((host, port), FoundationRequestHandler).serve_forever()


if __name__ == "__main__":
    main()
