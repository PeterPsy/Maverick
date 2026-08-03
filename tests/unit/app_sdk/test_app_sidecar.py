"""Tests for the public app-sidecar SDK client."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import socket
import tempfile
from threading import Thread
import unittest

from core.app_sdk.app_sidecar import (
    AppSidecarRequestError,
    AppSidecarUnavailableError,
    app_sidecar,
)


class AppSidecarSdkTests(unittest.TestCase):
    def test_client_calls_only_declared_broker_and_decodes_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            socket_path = str(Path(temp) / "broker.sock")
            captured: dict = {}
            thread = self._serve_once(
                socket_path,
                captured,
                {
                    "ok": True,
                    "status_code": 200,
                    "headers": {"content-type": "application/json"},
                    "body_base64": base64.b64encode(b'{"id":"od_1"}').decode("ascii"),
                },
            )
            payload = self._payload(socket_path)

            response = app_sidecar(payload, "opendesign").get(
                "/api/projects/od_1",
                query={"include": ["files", "runs"]},
            )
            thread.join(timeout=2)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": "od_1"})
        self.assertEqual(captured["capability"], "opaque-capability")
        self.assertEqual(captured["method"], "GET")
        self.assertEqual(captured["path"], "/api/projects/od_1")
        self.assertIn("include=files", captured["query_string"])
        self.assertNotIn(socket_path, repr(app_sidecar(payload, "opendesign")))
        self.assertNotIn("opaque-capability", repr(app_sidecar(payload, "opendesign")))

    def test_client_has_no_direct_fallback_for_missing_or_failed_broker(self) -> None:
        with self.assertRaisesRegex(AppSidecarUnavailableError, "service_not_available"):
            app_sidecar({}, "opendesign")

        with tempfile.TemporaryDirectory() as temp:
            client = app_sidecar(self._payload(str(Path(temp) / "missing.sock")), "opendesign")
            with self.assertRaisesRegex(AppSidecarUnavailableError, "broker_unavailable"):
                client.get("/api/projects")

    def test_broker_denial_is_preserved_without_direct_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            socket_path = str(Path(temp) / "broker.sock")
            captured: dict = {}
            thread = self._serve_once(
                socket_path,
                captured,
                {"ok": False, "error": "route_not_allowed"},
            )
            client = app_sidecar(self._payload(socket_path), "opendesign")

            with self.assertRaisesRegex(AppSidecarRequestError, "route_not_allowed"):
                client.post("/api/projects", json_body={"name": "forbidden"})
            thread.join(timeout=2)

        self.assertEqual(captured["method"], "POST")

    @staticmethod
    def _payload(socket_path: str) -> dict:
        return {
            "app_sidecar": {
                "protocol": "maverick.app-sidecar.v1",
                "invocation_id": "invoke-1",
                "services": {
                    "opendesign": {
                        "broker_socket": socket_path,
                        "capability": "opaque-capability",
                        "expires_in_seconds": 30,
                        "request_budget": 2,
                        "max_request_body_bytes": 4096,
                        "max_response_body_bytes": 65536,
                        "streaming": False,
                    }
                },
            }
        }

    @staticmethod
    def _serve_once(socket_path: str, captured: dict, response: dict) -> Thread:
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(socket_path)
        server.listen(1)

        def run() -> None:
            try:
                connection, _address = server.accept()
                with connection:
                    request = b""
                    while not request.endswith(b"\n"):
                        request += connection.recv(65536)
                    captured.update(json.loads(request.decode("utf-8")))
                    connection.sendall(json.dumps(response).encode("utf-8") + b"\n")
            finally:
                server.close()

        thread = Thread(target=run, daemon=True)
        thread.start()
        return thread


if __name__ == "__main__":
    unittest.main()
