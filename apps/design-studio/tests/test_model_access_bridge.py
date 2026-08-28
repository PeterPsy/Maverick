"""Native OpenDesign model-bridge adapter tests."""

from __future__ import annotations

import http.client
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = APP_ROOT / "service"
import sys

sys.path.insert(0, str(SERVICE_ROOT))

from model_access_profiles import write_model_access_profiles  # noqa: E402
from model_access_server import MODEL_ACCESS_API_KEY, ModelAccessHttpBridge  # noqa: E402


class _CatalogClient:
    def catalog(self):
        return {
            "schema_version": "1",
            "api_models": [
                {
                    "id": "model/exact",
                    "label": "Exact API",
                    "provider_id": "openrouter",
                    "transport": "api",
                    "available": True,
                }
            ],
            "cli_models": [
                {
                    "id": "gpt-test",
                    "label": "Codex Test",
                    "provider_id": "codex",
                    "transport": "cli",
                    "available": True,
                }
            ],
            "cli_defaults": {"codex": "gpt-test"},
        }


class _Response:
    status = 200

    def __init__(self, body: bytes) -> None:
        self.body = io.BytesIO(body)

    def getheaders(self):
        return [("Content-Type", "text/event-stream")]

    def read1(self, size):
        return self.body.read(size)


class _Connection:
    def __init__(self) -> None:
        self.closed = False

    def close(self):
        self.closed = True


class _ProxyClient:
    def __init__(self) -> None:
        self.requests = []
        self.connection = _Connection()

    def open(self, method, path, *, body=b"", **_kwargs):
        self.requests.append((method, path, body))
        return self.connection, _Response(b'data: {"delta":"native"}\n\ndata: [DONE]\n\n')


class NativeModelAccessAdapterTests(unittest.TestCase):
    def test_profile_uses_official_local_profile_contract_without_secrets_or_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target, summary = write_model_access_profiles(Path(temporary), _CatalogClient())
            raw = target.read_text(encoding="utf-8")
            payload = json.loads(raw)

        profile = payload["agents"][0]
        self.assertEqual(profile["baseAgent"], "codex")
        self.assertEqual(profile["bin"], "maverick-codex")
        self.assertEqual(profile["models"], [{"id": "gpt-test", "label": "Codex Test"}])
        self.assertEqual(profile["defaultModel"], "gpt-test")
        self.assertEqual(summary["model_count"], 1)
        self.assertNotIn("secret", raw.lower())
        self.assertNotIn("systemprompt", raw.lower())
        self.assertNotIn("memory", raw.lower())

    def test_standard_endpoint_forwards_exact_open_design_body_and_stream(self) -> None:
        client = _ProxyClient()
        with patch("model_access_server.MODEL_ACCESS_PORT", 0):
            bridge = ModelAccessHttpBridge(client)
        bridge.start()
        self.addCleanup(bridge.stop)
        port = bridge.server.server_address[1]
        body = b'{"model":"model/exact","messages":[{"role":"system","content":"native"}],"stream":true}'
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=body,
            headers={
                "Authorization": f"Bearer {MODEL_ACCESS_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        streamed = response.read()
        connection.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(client.requests, [("POST", "/v1/chat/completions", body)])
        self.assertIn(b'"delta":"native"', streamed)
        self.assertIn(b"[DONE]", streamed)
        self.assertTrue(client.connection.closed)


if __name__ == "__main__":
    unittest.main()
