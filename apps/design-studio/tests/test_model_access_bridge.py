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

from model_access_profiles import API_CONFIG_PATH, write_model_access_profiles  # noqa: E402
from model_access_server import MODEL_ACCESS_API_KEY, ModelAccessHttpBridge  # noqa: E402
from maverick_codex_cli import _validate_selected_model  # noqa: E402
from opencode_runtime import OpenCodeRuntimeError  # noqa: E402


class _CatalogClient:
    def __init__(self, *, api: bool = True, cli: bool = True) -> None:
        self.api = api
        self.cli = cli

    def catalog(self):
        catalog = {
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
        if not self.api:
            catalog["api_models"] = []
        if not self.cli:
            catalog["cli_models"] = []
        return catalog


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
    def test_codex_wrapper_rejects_a_model_outside_the_workspace_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile, _summary = write_model_access_profiles(
                Path(temporary),
                _CatalogClient(),
            )

            _validate_selected_model(("exec", "--model", "gpt-test"), profile_path=profile)
            with self.assertRaisesRegex(RuntimeError, "unavailable in this workspace"):
                _validate_selected_model(
                    ("exec", "--model", "gpt-other-workspace"),
                    profile_path=profile,
                )

    def test_profile_uses_official_local_profile_contract_without_secrets_or_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target, summary = write_model_access_profiles(Path(temporary), _CatalogClient())
            raw = target.read_text(encoding="utf-8")
            payload = json.loads(raw)
            api_config = json.loads((Path(temporary) / API_CONFIG_PATH).read_text())

        profiles = {profile["id"]: profile for profile in payload["agents"]}
        profile = profiles["installed-codex-cli"]
        self.assertEqual(profile["baseAgent"], "codex")
        self.assertEqual(profile["bin"], "maverick-codex")
        self.assertEqual(profile["models"], [{"id": "gpt-test", "label": "Codex Test"}])
        self.assertEqual(profile["defaultModel"], "gpt-test")
        api_profile = profiles["installed-maverick-api"]
        self.assertEqual(api_profile["baseAgent"], "opencode")
        self.assertEqual(api_profile["bin"], "maverick-opencode")
        self.assertEqual(api_profile["env"]["OPENCODE_DISABLE_PROJECT_CONFIG"], "true")
        self.assertEqual(
            api_profile["models"],
            [{"id": "maverick/model/exact", "label": "Exact API"}],
        )
        provider = api_config["provider"]["maverick"]
        self.assertEqual(provider["options"]["baseURL"], "http://127.0.0.1:49491/v1")
        self.assertEqual(provider["models"], {"model/exact": {"name": "Exact API"}})
        self.assertEqual(summary["model_count"], 1)
        self.assertEqual(summary["api_model_count"], 1)
        self.assertNotIn("secret", raw.lower())
        self.assertNotIn("systemprompt", raw.lower())
        self.assertNotIn("memory", raw.lower())

    def test_cli_profile_remains_active_when_api_catalog_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target, summary = write_model_access_profiles(
                Path(temporary),
                _CatalogClient(api=False),
            )
            profiles = json.loads(target.read_text(encoding="utf-8"))["agents"]

            self.assertEqual([profile["id"] for profile in profiles], ["installed-codex-cli"])
            self.assertEqual(summary["cli"]["state"], "ready")
            self.assertEqual(summary["api"]["state"], "degraded")
            self.assertFalse((Path(temporary) / API_CONFIG_PATH).exists())

    def test_api_profile_remains_active_when_cli_catalog_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target, summary = write_model_access_profiles(
                Path(temporary),
                _CatalogClient(cli=False),
            )
            profiles = json.loads(target.read_text(encoding="utf-8"))["agents"]

        self.assertEqual([profile["id"] for profile in profiles], ["installed-maverick-api"])
        self.assertEqual(summary["cli"]["state"], "degraded")
        self.assertEqual(summary["api"]["state"], "ready")

    def test_cli_profile_remains_active_when_optional_opencode_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target, summary = write_model_access_profiles(
                Path(temporary),
                _CatalogClient(),
                opencode_available=False,
            )
            profiles = json.loads(target.read_text(encoding="utf-8"))["agents"]

            self.assertEqual([profile["id"] for profile in profiles], ["installed-codex-cli"])
            self.assertEqual(summary["cli"]["state"], "ready")
            self.assertEqual(summary["api"], {
                "state": "degraded",
                "reason": "opencode_runtime_unavailable",
                "model_count": 1,
            })
            self.assertFalse((Path(temporary) / API_CONFIG_PATH).exists())

    def test_launcher_keeps_cli_profile_when_optional_runtime_verification_fails(self) -> None:
        from opendesign_launcher import _configure_model_access

        class _Bridge:
            def start(self) -> None:
                return

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict("os.environ", {"MAVERICK_OPENDESIGN_MODEL_BRIDGE": "enabled"}),
            patch("opendesign_launcher.ModelAccessConfiguration.from_environment", return_value=object()),
            patch("opendesign_launcher.ModelAccessClient", return_value=_CatalogClient()),
            patch(
                "opendesign_launcher.verify_opencode_runtime",
                side_effect=OpenCodeRuntimeError("missing"),
            ),
            patch("opendesign_launcher.ModelAccessHttpBridge", return_value=_Bridge()),
        ):
            data = Path(temporary) / "native"
            data.mkdir()
            bridge, status, profile_path = _configure_model_access(
                data,
                artifact_root=Path(temporary) / "artifacts",
            )
            profiles = json.loads(
                (data / "sandbox/agent-home/.maverick/model-access-agents.json").read_text()
            )["agents"]

        self.assertIsNotNone(bridge)
        self.assertIsNotNone(profile_path)
        self.assertEqual([profile["id"] for profile in profiles], ["installed-codex-cli"])
        self.assertEqual(
            status["profiles"]["api"]["reason"],
            "opencode_runtime_unavailable",
        )

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
