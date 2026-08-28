"""Proofs for the private, cognitively transparent model-access bridge."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import socket
import struct
import tempfile
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.model_access.broker import ModelAccessBroker
from core.model_access.catalog import resolve_codex_source_home
from core.model_access.cli_proxy import _validated_codex_argv
from core.model_access.cli_sandbox import is_opendesign_connection_probe
from core.model_access.models import CliFrame, ProviderHttpResponse


class _ForbiddenRuntimeStore:
    def __getattr__(self, name):
        raise AssertionError(f"model access consulted Maverick runtime state: {name}")


class _ProviderStore:
    def __init__(self) -> None:
        capabilities = SimpleNamespace(
            supports_streaming=True,
            supports_tools=True,
            supports_filesystem_access=True,
            input_modalities=["text", "image"],
            output_modalities=["text", "events"],
        )
        self.definitions = [
            SimpleNamespace(
                provider_id="openrouter",
                status="active",
                capabilities=capabilities,
                model_options=[SimpleNamespace(model_id="model/exact", label="Exact API")],
                default_model_family="model/exact",
            ),
            SimpleNamespace(
                provider_id="codex",
                status="active",
                capabilities=capabilities,
                model_options=[SimpleNamespace(model_id="gpt-test", label="Codex Test")],
                default_model_family="gpt-test",
            ),
        ]
        self.binding = SimpleNamespace(
            binding_id="openrouter:default",
            provider_id="openrouter",
            workspace_id="default",
            secret_ref="platform:secrets/openrouter-test",
            status="active",
        )

    def list_provider_definitions(self):
        return list(self.definitions)

    def list_provider_bindings(self, *, workspace_id=None, provider_id=None, status=None):
        del status
        if provider_id != "openrouter":
            return []
        if workspace_id in {None, "default"}:
            return [self.binding]
        return []

    def get_provider_selection(self, workspace_id):
        return SimpleNamespace(provider_id="codex", model_id="gpt-test") if workspace_id == "default" else None


class _SecretStore:
    def get_secret(self, secret_id):
        if secret_id != "openrouter-test":
            raise KeyError(secret_id)
        return SimpleNamespace(secret_id=secret_id, status="active")

    def get_secret_by_alias(self, alias):
        raise KeyError(alias)

    def get_secret_value(self, *, secret_id):
        if secret_id != "openrouter-test":
            raise KeyError(secret_id)
        return "upstream-secret"


class _RecordingApiTransport:
    def __init__(self, *, blocking: bool = False) -> None:
        self.blocking = blocking
        self.requests: list[dict[str, object]] = []
        self.cancelled = Event()
        self.closed = Event()

    def open(self, *, provider_id, body, credential, cancellation):
        self.requests.append(
            {
                "provider_id": provider_id,
                "body": body,
                "credential": credential,
            }
        )

        def chunks():
            try:
                yield b'data: {"delta":"one"}\n\n'
                if self.blocking:
                    while not cancellation.wait(0.01):
                        pass
                    self.cancelled.set()
                else:
                    yield b'data: [DONE]\n\n'
            finally:
                if cancellation.is_set():
                    self.cancelled.set()

        return ProviderHttpResponse(
            status=200,
            headers=(("Content-Type", "text/event-stream"),),
            chunks=chunks(),
            close=self.closed.set,
        )


class _RecordingCliExecutor:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def execute(self, *, scope, provider_id, argv, cwd, stdin, cancellation):
        self.requests.append(
            {
                "scope": scope,
                "provider_id": provider_id,
                "argv": argv,
                "cwd": cwd,
                "stdin": stdin,
                "cancellation": cancellation,
            }
        )
        yield CliFrame(channel="stdout", payload=b'{"type":"thread.started"}\n')
        yield CliFrame(channel="stderr", payload=b"technical warning\n")
        yield CliFrame(channel="exit", payload=b'{"exit_code":0}')


class _FailingCliExecutor:
    def execute(self, **_kwargs):
        raise ValueError("private transport detail")
        yield  # pragma: no cover - make this a generator


class _BlockingCliExecutor:
    def __init__(self) -> None:
        self.cancelled = Event()

    def execute(self, *, cancellation, **_kwargs):
        yield CliFrame(channel="stdout", payload=b'{"type":"turn.started"}\n')
        while not cancellation.wait(0.01):
            pass
        self.cancelled.set()


class ModelAccessBrokerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data_root = self.root / "workspaces" / "default" / "data" / "design-studio"
        (self.data_root / "opendesign-native" / "project").mkdir(parents=True)
        self.state = SimpleNamespace(
            repository_root=self.root,
            provider_store=_ProviderStore(),
            secret_store=_SecretStore(),
            observability_store=None,
            runtime_store=_ForbiddenRuntimeStore(),
        )

    def test_api_request_body_stream_and_selected_model_are_semantically_unchanged(self) -> None:
        transport = _RecordingApiTransport()
        broker, lease = self._start_broker(api_transport=transport)
        body = (
            b'{"model":"model/exact","messages":[{"role":"system","content":"OpenDesign only"}],'
            b'"tools":[{"type":"function","function":{"name":"draw","parameters":{}}}],"stream":true}'
        )
        response = _request(
            broker.socket_path,
            method="POST",
            path="/v1/chat/completions",
            token=lease.token,
            body=body,
        )

        self.assertIn(b"HTTP/1.1 200 OK", response)
        self.assertIn(b'data: {"delta":"one"}', response)
        self.assertIn(b"data: [DONE]", response)
        self.assertEqual(transport.requests[0]["body"], body)
        self.assertEqual(transport.requests[0]["provider_id"], "openrouter")
        self.assertEqual(transport.requests[0]["credential"], "upstream-secret")
        self.assertTrue(transport.closed.wait(1))

    def test_catalog_is_standard_and_does_not_create_or_read_runtime_state(self) -> None:
        broker, lease = self._start_broker()
        response = _request(
            broker.socket_path,
            method="GET",
            path="/v1/models",
            token=lease.token,
        )
        payload = json.loads(response.split(b"\r\n\r\n", 1)[1])

        self.assertEqual(payload["object"], "list")
        self.assertEqual(payload["data"], [{"id": "model/exact", "object": "model", "owned_by": "openrouter"}])

    def test_codex_auth_source_ignores_maverick_runtime_homes(self) -> None:
        runtime_home = self.root / "workspaces/default/runtime/sessions/private/codex-home/.codex"
        with patch.dict(os.environ, {"MAVERICK_CODEX_HOME": str(runtime_home)}, clear=False):
            os.environ.pop("MAVERICK_MODEL_ACCESS_CODEX_HOME", None)
            resolved = resolve_codex_source_home()

        self.assertEqual(resolved, Path.home() / ".codex")
        self.assertNotEqual(resolved, runtime_home)

    def test_client_disconnect_cancels_provider_stream(self) -> None:
        transport = _RecordingApiTransport(blocking=True)
        broker, lease = self._start_broker(api_transport=transport)
        body = b'{"model":"model/exact","messages":[{"role":"user","content":"cancel"}],"stream":true}'
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(2)
        client.connect(str(broker.socket_path))
        client.sendall(_request_bytes("POST", "/v1/chat/completions", lease.token, body))
        received = b""
        while b'data: {"delta":"one"}' not in received:
            received += client.recv(4096)
        client.close()

        self.assertTrue(transport.cancelled.wait(2))
        self.assertTrue(transport.closed.wait(2))

    def test_cli_protocol_preserves_native_adapter_argv_stdin_and_stream_channels(self) -> None:
        executor = _RecordingCliExecutor()
        broker, lease = self._start_broker(cli_executor=executor)
        argv = ("exec", "--json", "--skip-git-repo-check", "--model", "gpt-test")
        prompt = b"OpenDesign-composed prompt, with no Maverick context.\n"
        response = _request(
            broker.socket_path,
            method="POST",
            path="/maverick/v1/cli/codex/exec",
            token=lease.token,
            body=prompt,
            extra_headers={
                "X-Maverick-Cli-Argv": _encoded_header(json.dumps(argv)),
                "X-Maverick-Cli-Cwd": _encoded_header("/data/opendesign-native/project"),
            },
        )
        header, framed = response.split(b"\r\n\r\n", 1)
        frames = _decode_frames(framed)

        self.assertIn(b"application/x-maverick-cli-frames", header)
        self.assertEqual(executor.requests[0]["argv"], argv)
        self.assertEqual(executor.requests[0]["stdin"], prompt)
        self.assertEqual(executor.requests[0]["cwd"], "/data/opendesign-native/project")
        self.assertEqual(frames[0], (b"O", b'{"type":"thread.started"}\n'))
        self.assertEqual(frames[1], (b"E", b"technical warning\n"))
        self.assertEqual(frames[2], (b"X", b'{"exit_code":0}'))

    def test_codex_adapter_validation_only_translates_scoped_paths(self) -> None:
        argv = (
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--sandbox",
            "danger-full-access",
            "-C",
            "/data/opendesign-native/project",
            "--model",
            "gpt-test",
            "-c",
            'model_reasoning_effort="high"',
        )
        translated = _validated_codex_argv(
            argv,
            data_root=self.data_root,
            sidecar_cwd="/data/opendesign-native/project",
        )
        self.assertEqual(translated[translated.index("-C") + 1], "/workspace/opendesign-native/project")
        with self.assertRaisesRegex(ValueError, "app data"):
            _validated_codex_argv(
                (*argv[:-6], "-C", "/etc", *argv[-4:]),
                data_root=self.data_root,
                sidecar_cwd="/etc",
            )

    def test_official_connection_probe_uses_an_isolated_workspace_mapping(self) -> None:
        cwd = "/tmp/od-conn-test-AbC_123"
        argv = (
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--sandbox",
            "danger-full-access",
            "--disable",
            "plugins",
            "-C",
            cwd,
            "--model",
            "gpt-test",
        )

        self.assertTrue(is_opendesign_connection_probe(argv, cwd))
        with self.assertRaisesRegex(ValueError, "app data"):
            _validated_codex_argv(argv, data_root=self.data_root, sidecar_cwd=cwd)
        translated = _validated_codex_argv(
            argv,
            data_root=self.data_root,
            sidecar_cwd=cwd,
            allow_connection_probe=True,
        )
        self.assertEqual(translated[translated.index("-C") + 1], "/workspace")
        self.assertFalse(is_opendesign_connection_probe(argv, "/tmp/not-opendesign"))

    def test_cli_failure_finishes_the_existing_framed_response(self) -> None:
        broker, lease = self._start_broker(cli_executor=_FailingCliExecutor())
        with self.assertLogs("core.model_access.http_server", level="ERROR"):
            response = _request(
                broker.socket_path,
                method="POST",
                path="/maverick/v1/cli/codex/exec",
                token=lease.token,
                extra_headers={
                    "X-Maverick-Cli-Argv": _encoded_header('["--version"]'),
                    "X-Maverick-Cli-Cwd": _encoded_header("/app"),
                },
            )
        header, framed = response.split(b"\r\n\r\n", 1)

        self.assertIn(b"HTTP/1.1 200 OK", header)
        self.assertNotIn(b"HTTP/1.1 502", framed)
        self.assertEqual(
            _decode_frames(framed),
            [(b"E", b"Codex model transport failed\n"), (b"X", b'{"exit_code":1}')],
        )

    def test_cli_client_disconnect_cancels_the_naked_process(self) -> None:
        executor = _BlockingCliExecutor()
        broker, lease = self._start_broker(cli_executor=executor)
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(2)
        client.connect(str(broker.socket_path))
        client.sendall(
            _request_bytes(
                "POST",
                "/maverick/v1/cli/codex/exec",
                lease.token,
                extra_headers={
                    "X-Maverick-Cli-Argv": _encoded_header('["--version"]'),
                    "X-Maverick-Cli-Cwd": _encoded_header("/app"),
                },
            )
        )
        received = b""
        while b'{"type":"turn.started"}' not in received:
            received += client.recv(4096)
        client.close()

        self.assertTrue(executor.cancelled.wait(2))

    def _start_broker(self, *, api_transport=None, cli_executor=None):
        broker = ModelAccessBroker(
            self.state,
            socket_path=self.root / "broker" / "broker.sock",
            api_transport=api_transport,
            cli_executor=cli_executor or _RecordingCliExecutor(),
        )
        broker.start()
        self.addCleanup(broker.stop)
        lease = broker.issue(
            workspace_id="default",
            app_id="design-studio",
            sidecar_id="opendesign",
            data_root=self.data_root,
            api=True,
            cli=("codex",),
        )
        self.addCleanup(lease.release)
        return broker, lease


def _request(socket_path, *, method, path, token, body=b"", extra_headers=None):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(3)
    client.connect(str(socket_path))
    client.sendall(_request_bytes(method, path, token, body, extra_headers=extra_headers))
    chunks: list[bytes] = []
    while True:
        chunk = client.recv(65536)
        if not chunk:
            break
        chunks.append(chunk)
    client.close()
    return b"".join(chunks)


def _request_bytes(method, path, token, body=b"", *, extra_headers=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Length": str(len(body)),
        "Content-Type": "application/json",
        "Connection": "close",
        **(extra_headers or {}),
    }
    lines = [f"{method} {path} HTTP/1.1", *[f"{key}: {value}" for key, value in headers.items()], "", ""]
    return "\r\n".join(lines).encode("latin1") + body


def _encoded_header(value):
    return base64.urlsafe_b64encode(value.encode("utf-8")).rstrip(b"=").decode("ascii")


def _decode_frames(payload):
    frames = []
    offset = 0
    while offset < len(payload):
        channel = payload[offset : offset + 1]
        length = struct.unpack("!I", payload[offset + 1 : offset + 5])[0]
        start = offset + 5
        frames.append((channel, payload[start : start + length]))
        offset = start + length
    return frames


if __name__ == "__main__":
    unittest.main()
