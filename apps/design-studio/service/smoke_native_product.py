#!/usr/bin/env python3
"""Exercise the native model, delegation, continuation, and isolation paths."""

from __future__ import annotations

import argparse
from base64 import b64encode
from contextlib import contextmanager
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
from threading import Event, Lock, Thread
import time
from types import SimpleNamespace
from typing import Any, Iterator
from urllib.parse import quote


APP_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = APP_ROOT.parents[1]
BACKEND_ROOT = APP_ROOT / "backend"
sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

from delegation_errors import DelegationError  # noqa: E402
from delegation_service import DelegationService  # noqa: E402
from core.model_access.http_server import ThreadingUnixModelAccessServer  # noqa: E402
from core.model_access.models import (  # noqa: E402
    CliFrame,
    ModelAccessCatalog,
    ModelAccessModel,
    ModelAccessScope,
)
from model_access_profiles import (  # noqa: E402
    API_CONFIG_PATH,
    SANDBOX_PROFILE_PATH,
    write_model_access_profiles,
)
from model_access_server import ModelAccessHttpBridge  # noqa: E402
from official_inventory_process import (  # noqa: E402
    OfficialApiClient,
    _stop_process,
    _wait_ready,
)
from official_opendesign_release import (  # noqa: E402
    OfficialInstallation,
    OfficialReleaseError,
    verify_official_installation,
)
from opencode_runtime import verify_opencode_runtime  # noqa: E402
from opendesign_client import (  # noqa: E402
    OpenDesignNotFound,
    OpenDesignRequestFailed,
)
from opendesign_launcher import build_native_launch  # noqa: E402


API_AGENT_ID = "installed-maverick-api"
CLI_AGENT_ID = "installed-codex-cli"
API_MODEL_ID = "maverick/model/exact"
BETA_API_MODEL_ID = "maverick/model/beta"
CLI_MODEL_ID = "gpt-e2e"
BETA_CLI_MODEL_ID = "gpt-beta"
STREAM_MARKER = "native-e2e-stream"
CANCEL_MARKER = "official-cancel-e2e"
CLI_MARKER = "native-e2e-cli"
CLI_CANCEL_MARKER = "official-cli-cancel-e2e"
MEDIA_ASSET_NAME = "alpha-media-e2e.png"
TERMINAL = {"succeeded", "failed", "canceled"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installation", type=Path, required=True)
    parser.add_argument("--opencode-runtime", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    args = parser.parse_args()

    installation = verify_official_installation(args.installation)
    opencode = verify_opencode_runtime(args.opencode_runtime)

    model_client = _E2EModelClient()
    bridge = ModelAccessHttpBridge(model_client)
    bridge.start()
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="design-studio-native-product-e2e-") as temporary:
            root = Path(temporary)
            broker = _E2ECliBroker(root / "model-access")
            broker.start()
            try:
                transport = _prove_opencode_streaming(
                    opencode,
                    model_client=model_client,
                    root=root / "transport",
                    timeout_seconds=args.timeout_seconds,
                )
                alpha_start = broker.request_count
                alpha = _exercise_alpha_workspace(
                    installation,
                    opencode_runtime=args.opencode_runtime,
                    model_client=model_client,
                    root=root / "alpha",
                    model_access=broker,
                    timeout_seconds=args.timeout_seconds,
                )
                broker.assert_requests_since(alpha_start, workspace_id="alpha")
                beta = _exercise_beta_workspace(
                    installation,
                    opencode_runtime=args.opencode_runtime,
                    root=root / "beta",
                    model_access=broker,
                    alpha=alpha,
                    timeout_seconds=args.timeout_seconds,
                )
            finally:
                broker.stop()
    finally:
        bridge.stop()

    print(json.dumps({
        "schema_version": "1",
        "kind": "design-studio-native-product-e2e",
        "status": "passed",
        "duration_ms": round((time.monotonic() - started) * 1000, 3),
        "selector": {
            "api_profile": alpha["api_profile"],
            "cli_profile": alpha["cli_profile"],
            "api_model": alpha["api_model"],
            "cli_executed": alpha["cli_executed"],
        },
        "opencode": {
            "streaming": transport["streaming"],
            "api_cancellation": alpha["api_cancellation"],
            "cli_cancellation": alpha["cli_cancellation"],
            "api_tools_media": alpha["api_tools_media"],
            "cli_tools_media": alpha["cli_tools_media"],
        },
        "delegation": {
            "direct_conversation_continued": alpha["conversation_continued"],
            "visible_user_message_count": alpha["visible_user_message_count"],
        },
        "workspace_isolation": beta,
    }, indent=2, sort_keys=True))


class _E2EModelClient:
    def __init__(self) -> None:
        self.slow_started = Event()
        self.slow_closed = Event()
        self.tools_media_seen = Event()
        self._lock = Lock()
        self.request_count = 0

    def catalog(self) -> dict[str, Any]:
        return _model_catalog("model/exact", CLI_MODEL_ID)

    def open(self, method: str, path: str, *, body: bytes = b"", **_kwargs):
        with self._lock:
            self.request_count += 1
        if method == "GET" and path == "/v1/models":
            return _TrackedConnection(), _ChunkResponse([
                json.dumps({
                    "object": "list",
                    "data": [{"id": "model/exact", "object": "model"}],
                }).encode("utf-8")
            ], content_type="application/json")
        payload = _json_object(body)
        if (
            MEDIA_ASSET_NAME in json.dumps(payload, separators=(",", ":"))
            and isinstance(payload.get("tools"), list)
            and payload["tools"]
        ):
            self.tools_media_seen.set()
        title_request = any(
            isinstance(message, dict)
            and "title generator" in str(message.get("content") or "")
            for message in payload.get("messages", [])
        )
        cancel_request = CANCEL_MARKER.encode("utf-8") in body and not title_request
        connection = _TrackedConnection(self.slow_closed if cancel_request else None)
        if cancel_request:
            self.slow_started.set()
            return connection, _SlowChunkResponse()
        return connection, _ChunkResponse(_completion_chunks(STREAM_MARKER))

    def reset_cancellation(self) -> None:
        self.slow_started.clear()
        self.slow_closed.clear()

    def assert_tools_media_forwarded(self) -> None:
        if not self.tools_media_seen.is_set():
            raise OfficialReleaseError(
                "OpenDesign tools and approved media did not reach the API model boundary"
            )


class _CatalogClient:
    def __init__(self, api_model: str, cli_model: str) -> None:
        self.api_model = api_model
        self.cli_model = cli_model

    def catalog(self) -> dict[str, Any]:
        return _model_catalog(self.api_model, self.cli_model)


def _model_catalog(api_model: str, cli_model: str) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "api_models": [{
            "id": api_model,
            "label": f"E2E API {api_model}",
            "provider_id": "e2e",
            "transport": "api",
            "available": True,
        }],
        "cli_models": [{
            "id": cli_model,
            "label": f"E2E CLI {cli_model}",
            "provider_id": "codex",
            "transport": "cli",
            "available": True,
        }],
        "cli_defaults": {"codex": cli_model},
    }


class _E2ECliBroker:
    """Minimal real Unix-wire broker used by the production Codex wrapper."""

    api_proxy = None
    state = None

    def __init__(self, root: Path) -> None:
        self.root = root
        self.socket_path = root / "broker.sock"
        self.cli_executor = self
        self._scopes: dict[str, ModelAccessScope] = {}
        self._requests: list[str] = []
        self._executions: list[str] = []
        self._denials: list[tuple[str, str]] = []
        self._lock = Lock()
        self._server: ThreadingUnixModelAccessServer | None = None
        self._thread: Thread | None = None
        self.cli_slow_started = Event()
        self.cli_slow_closed = Event()
        self.cli_tools_media_seen = Event()

    @property
    def request_count(self) -> int:
        with self._lock:
            return len(self._requests)

    @property
    def execution_count(self) -> int:
        with self._lock:
            return len(self._executions)

    def issue(self, workspace_id: str, *, data_root: Path) -> str:
        token = f"native-e2e-{workspace_id}-{secrets.token_urlsafe(18)}"
        self._scopes[token] = ModelAccessScope(
            workspace_id=workspace_id,
            app_id="design-studio",
            sidecar_id="opendesign",
            data_root=data_root.resolve(strict=True),
            api=True,
            cli=("codex",),
        )
        return token

    def start(self) -> None:
        self.root.mkdir(mode=0o700)
        self._server = ThreadingUnixModelAccessServer(str(self.socket_path), self)
        self._thread = Thread(
            target=self._server.serve_forever,
            name="design-studio-e2e-cli-broker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self.socket_path.unlink(missing_ok=True)

    def authorize(
        self,
        authorization: str,
        *,
        cancellation: Event | None = None,
    ) -> ModelAccessScope:
        del cancellation
        prefix = "Bearer "
        token = authorization[len(prefix):] if authorization.startswith(prefix) else ""
        scope = self._scopes.get(token)
        if scope is None:
            raise PermissionError("invalid E2E model-access capability")
        with self._lock:
            self._requests.append(scope.workspace_id)
        return scope

    def release_authorization(
        self,
        _authorization: str,
        *,
        cancellation: Event | None,
    ) -> None:
        del cancellation

    def catalog(self, scope: ModelAccessScope) -> ModelAccessCatalog:
        """Use the production Core authorizer against this exact scoped fixture."""
        model_id = {
            "alpha": CLI_MODEL_ID,
            "beta": BETA_CLI_MODEL_ID,
        }.get(scope.workspace_id)
        if model_id is None:
            raise PermissionError("unexpected E2E catalog scope")
        model = ModelAccessModel(
            model_id=model_id,
            label=f"E2E CLI {model_id}",
            provider_id="codex",
            transport="cli",
            available=True,
        )
        return ModelAccessCatalog(
            api_models=(),
            cli_models=(model,),
            cli_defaults={"codex": model_id},
        )

    def execute(
        self,
        *,
        scope: ModelAccessScope,
        provider_id: str,
        argv: tuple[str, ...],
        cwd: str,
        stdin: bytes,
        cancellation: Event,
    ) -> Iterator[CliFrame]:
        if provider_id != "codex" or scope.cli != ("codex",):
            raise PermissionError("unexpected E2E CLI scope")
        with self._lock:
            self._executions.append(scope.workspace_id)
        if "--version" in argv:
            yield CliFrame("stdout", b"codex-cli 1.0.0-e2e\n")
            yield CliFrame("exit", b'{"exit_code":0}')
            return
        project_id = Path(cwd).name
        connection_probe = project_id.startswith("od-conn-test-")
        if not connection_probe and not _scope_contains_cwd(scope, cwd):
            self._record_denial(scope.workspace_id, "workspace_project")
            raise PermissionError("CLI capability cannot access this workspace project")
        if MEDIA_ASSET_NAME.encode("utf-8") in stdin and "--add-dir" in argv:
            self.cli_tools_media_seen.set()
        if CLI_CANCEL_MARKER.encode("utf-8") in stdin:
            self.cli_slow_started.set()
            try:
                yield CliFrame(
                    "stdout",
                    b'{"type":"thread.started","thread_id":"e2e-cli-cancel"}\n',
                )
                while not cancellation.wait(0.05):
                    pass
            finally:
                self.cli_slow_closed.set()
            return
        events = (
            {"type": "thread.started", "thread_id": "e2e-cli-thread"},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {"id": "e2e-cli-item", "type": "agent_message", "text": CLI_MARKER},
            },
            {
                "type": "turn.completed",
                "usage": {"input_tokens": max(1, len(stdin)), "output_tokens": 1},
            },
        )
        for event in events:
            if cancellation.is_set():
                return
            yield CliFrame("stdout", (json.dumps(event, separators=(",", ":")) + "\n").encode())
        yield CliFrame("exit", b'{"exit_code":0}')

    def reset_cli_cancellation(self) -> None:
        self.cli_slow_started.clear()
        self.cli_slow_closed.clear()

    def assert_tools_media_forwarded(self) -> None:
        if not self.cli_tools_media_seen.is_set():
            raise OfficialReleaseError(
                "OpenDesign tools and approved media did not reach the CLI model boundary"
            )

    @property
    def denial_count(self) -> int:
        with self._lock:
            return len(self._denials)

    def assert_denial_since(
        self,
        offset: int,
        *,
        workspace_id: str,
        reason: str,
    ) -> None:
        with self._lock:
            denials = self._denials[offset:]
        if (workspace_id, reason) not in denials:
            raise OfficialReleaseError(
                f"the {workspace_id} capability was not denied for {reason}"
            )

    def assert_core_model_denial_since(
        self,
        request_offset: int,
        execution_offset: int,
        *,
        workspace_id: str,
    ) -> None:
        with self._lock:
            requests = self._requests[request_offset:]
            executions = self._executions[execution_offset:]
        if workspace_id not in requests:
            raise OfficialReleaseError(
                "the cross-workspace CLI model request did not reach the Core broker"
            )
        if workspace_id in executions:
            raise OfficialReleaseError(
                "Core invoked the CLI executor for a model outside the scoped catalog"
            )

    def _record_denial(self, workspace_id: str, reason: str) -> None:
        with self._lock:
            self._denials.append((workspace_id, reason))

    def assert_requests_since(self, offset: int, *, workspace_id: str) -> None:
        with self._lock:
            requests = self._requests[offset:]
        if not requests or set(requests) != {workspace_id}:
            raise OfficialReleaseError(
                f"model-access credentials were not isolated for workspace {workspace_id}"
            )


class _TrackedConnection:
    def __init__(self, closed: Event | None = None) -> None:
        self._closed = closed

    def close(self) -> None:
        if self._closed:
            self._closed.set()


class _ChunkResponse:
    status = 200

    def __init__(self, chunks: list[bytes], *, content_type: str = "text/event-stream") -> None:
        self._chunks = list(chunks)
        self._content_type = content_type

    def getheaders(self) -> list[tuple[str, str]]:
        return [("Content-Type", self._content_type)]

    def read1(self, _size: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


class _SlowChunkResponse:
    status = 200

    def __init__(self) -> None:
        self._index = 0

    def getheaders(self) -> list[tuple[str, str]]:
        return [("Content-Type", "text/event-stream")]

    def read1(self, _size: int) -> bytes:
        time.sleep(0.05)
        self._index += 1
        return _completion_chunk(f"cancel-{self._index}")


def _completion_chunks(text: str) -> list[bytes]:
    return [
        _completion_chunk(text),
        b'data: {"id":"e2e","object":"chat.completion.chunk","created":1,'
        b'"model":"model/exact","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n',
        b"data: [DONE]\n\n",
    ]


def _completion_chunk(text: str) -> bytes:
    return (
        "data: "
        + json.dumps({
            "id": "e2e",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "model/exact",
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": text},
                "finish_reason": None,
            }],
        }, separators=(",", ":"))
        + "\n\n"
    ).encode("utf-8")


def _prove_opencode_streaming(
    executable: Path,
    *,
    model_client: _E2EModelClient,
    root: Path,
    timeout_seconds: float,
) -> dict[str, bool]:
    native = root / "native"
    native.mkdir(parents=True)
    _profile(native, model_client)
    home = root / "home"
    home.mkdir()
    environment = {
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "OPENCODE_CONFIG": str(native / API_CONFIG_PATH),
        "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
        "PATH": "/usr/bin:/bin",
    }
    completed = subprocess.run(
        [
            str(executable),
            "run",
            "--pure",
            "--format",
            "json",
            "--model",
            API_MODEL_ID,
            "native-stream-e2e",
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0 or STREAM_MARKER not in completed.stdout:
        raise OfficialReleaseError("OpenCode did not stream through the model-access endpoint")
    return {"streaming": True}


def _exercise_alpha_workspace(
    installation: OfficialInstallation,
    *,
    opencode_runtime: Path,
    model_client: _E2EModelClient,
    root: Path,
    model_access: _E2ECliBroker,
    timeout_seconds: float,
) -> dict[str, Any]:
    native = root / "opendesign-native"
    native.mkdir(parents=True)
    _profile(native, _CatalogClient("model/exact", CLI_MODEL_ID))
    model_access_token = model_access.issue("alpha", data_root=native)
    payload = SimpleNamespace(app_id="design-studio", workspace_id="alpha", data_root=str(root))
    first_arguments = {
        "idempotency_key": "shared-e2e-key",
        "brief": "alpha first delegated brief",
        "agent_id": API_AGENT_ID,
        "model": API_MODEL_ID,
        "attachments": [{
            "authorized": True,
            "name": "alpha-asset.txt",
            "media_type": "text/plain",
            "content_base64": b64encode(b"alpha workspace asset").decode("ascii"),
        }, {
            "authorized": True,
            "name": MEDIA_ASSET_NAME,
            "media_type": "image/png",
            "content_base64": (
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
                "+A8AAQUBAScY42YAAAAASUVORK5CYII="
            ),
        }],
    }
    with _running_profiled_official(
        installation,
        native=native,
        opencode_runtime=opencode_runtime,
        model_access=model_access,
        model_access_token=model_access_token,
        timeout_seconds=timeout_seconds,
        log_path=root / "alpha-first.log",
    ) as client:
        selector = _assert_native_selector(
            client,
            api_model_id=API_MODEL_ID,
            cli_model_id=CLI_MODEL_ID,
        )
        adapter = _DelegationApi(client)
        service = DelegationService(payload, client=adapter)
        first = service.delegate(first_arguments)
        first_record = _wait_delegation(service, first, timeout_seconds=timeout_seconds)
        project_id = first_record["opendesign"]["project_id"]
        conversation_id = first_record["opendesign"]["conversation_id"]
        first_delegation_id = first_record["delegation_id"]
        asset_paths = {
            str(item.get("path") or item.get("name") or "")
            for item in adapter.list_files(project_id)
        }
        if not all(
            any(name in path for path in asset_paths)
            for name in ("alpha-asset.txt", MEDIA_ASSET_NAME)
        ):
            raise OfficialReleaseError("delegated alpha assets were not persisted")

    with _running_profiled_official(
        installation,
        native=native,
        opencode_runtime=opencode_runtime,
        model_access=model_access,
        model_access_token=model_access_token,
        timeout_seconds=timeout_seconds,
        log_path=root / "alpha-continuation.log",
    ) as client:
        adapter = _DelegationApi(client)
        direct = _run_direct_native_turn(
            client,
            adapter=adapter,
            project_id=project_id,
            conversation_id=conversation_id,
            message_id="direct-user-e2e",
            assistant_message_id="direct-assistant-e2e",
            text="alpha direct native continuation",
            agent_id=API_AGENT_ID,
            model=API_MODEL_ID,
            timeout_seconds=timeout_seconds,
        )
        _run_direct_native_turn(
            client,
            adapter=adapter,
            project_id=project_id,
            conversation_id=conversation_id,
            message_id="cli-user-e2e",
            assistant_message_id="cli-assistant-e2e",
            text="exercise the real native Codex profile",
            agent_id=CLI_AGENT_ID,
            model=CLI_MODEL_ID,
            timeout_seconds=timeout_seconds,
        )
        messages = adapter.list_messages(project_id, conversation_id)
        visible = [
            str(message.get("content") or "")
            for message in messages
            if message.get("role") == "user"
        ]
        if not all(
            brief in "\n".join(visible)
            for brief in ("alpha first delegated brief", "alpha direct native continuation")
        ):
            raise OfficialReleaseError("direct native conversation continuation was not persisted")
        if CLI_MARKER not in "\n".join(
            str(message.get("content") or "") for message in messages
        ):
            raise OfficialReleaseError("the native Codex profile did not execute a real run")
        _prove_official_cancellation(
            client,
            model_client=model_client,
            project_id=project_id,
            conversation_id=conversation_id,
            timeout_seconds=timeout_seconds,
        )
        _prove_official_cli_cancellation(
            client,
            model_access=model_access,
            project_id=project_id,
            conversation_id=conversation_id,
            timeout_seconds=timeout_seconds,
        )
        model_client.assert_tools_media_forwarded()
        model_access.assert_tools_media_forwarded()
    _assert_profile_contains_no_capability(native, model_access_token)

    return {
        **selector,
        "cli_executed": True,
        "api_cancellation": True,
        "cli_cancellation": True,
        "api_tools_media": True,
        "cli_tools_media": True,
        "conversation_continued": direct.get("conversationId", conversation_id) == conversation_id,
        "visible_user_message_count": len(visible),
        "delegation_id": first_delegation_id,
        "project_id": project_id,
        "asset_paths": sorted(asset_paths),
        "_model_access_token": model_access_token,
    }


def _exercise_beta_workspace(
    installation: OfficialInstallation,
    *,
    opencode_runtime: Path,
    root: Path,
    model_access: _E2ECliBroker,
    alpha: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, bool]:
    native = root / "opendesign-native"
    native.mkdir(parents=True)
    _profile(native, _CatalogClient("model/beta", BETA_CLI_MODEL_ID))
    model_access_token = model_access.issue("beta", data_root=native)
    payload = SimpleNamespace(app_id="design-studio", workspace_id="beta", data_root=str(root))
    correct_request_start = model_access.request_count
    with _running_profiled_official(
        installation,
        native=native,
        opencode_runtime=opencode_runtime,
        model_access=model_access,
        model_access_token=model_access_token,
        timeout_seconds=timeout_seconds,
        log_path=root / "beta.log",
    ) as client:
        adapter = _DelegationApi(client)
        _assert_native_selector(
            client,
            api_model_id=BETA_API_MODEL_ID,
            cli_model_id=BETA_CLI_MODEL_ID,
            forbidden_models={API_MODEL_ID, CLI_MODEL_ID},
        )
        service = DelegationService(payload, client=adapter)
        beta = service.delegate({
            "idempotency_key": "shared-e2e-key",
            "brief": "beta isolated delegated brief",
            "agent_id": API_AGENT_ID,
            "model": BETA_API_MODEL_ID,
        })
        beta_record = _wait_delegation(service, beta, timeout_seconds=timeout_seconds)
        project_id = beta_record["opendesign"]["project_id"]
        conversation_id = beta_record["opendesign"]["conversation_id"]
        _run_direct_native_turn(
            client,
            adapter=adapter,
            project_id=project_id,
            conversation_id=conversation_id,
            message_id="beta-cli-user-e2e",
            assistant_message_id="beta-cli-assistant-e2e",
            text="exercise beta workspace CLI capability",
            agent_id=CLI_AGENT_ID,
            model=BETA_CLI_MODEL_ID,
            timeout_seconds=timeout_seconds,
        )
        _assert_native_run_rejected(
            client,
            adapter=adapter,
            project_id=project_id,
            conversation_id=conversation_id,
            message_id="beta-cross-api-model-e2e",
            agent_id=API_AGENT_ID,
            model=API_MODEL_ID,
            timeout_seconds=timeout_seconds,
        )
        cross_cli_request_start = model_access.request_count
        cross_cli_execution_start = model_access.execution_count
        _assert_native_run_rejected(
            client,
            adapter=adapter,
            project_id=project_id,
            conversation_id=conversation_id,
            message_id="beta-cross-cli-model-e2e",
            agent_id=CLI_AGENT_ID,
            model=CLI_MODEL_ID,
            timeout_seconds=timeout_seconds,
        )
        model_access.assert_core_model_denial_since(
            cross_cli_request_start,
            cross_cli_execution_start,
            workspace_id="beta",
        )
        projects = {str(item.get("id") or "") for item in adapter.list_projects()}
        if alpha["project_id"] in projects:
            raise OfficialReleaseError("alpha OpenDesign project leaked into beta workspace")
        if beta_record["delegation_id"] == alpha["delegation_id"]:
            raise OfficialReleaseError("workspace identity was omitted from delegation identity")
        try:
            service.status(alpha["delegation_id"])
        except DelegationError as error:
            if error.code != "delegation_not_found":
                raise
        else:
            raise OfficialReleaseError("alpha delegation metadata leaked into beta workspace")
        try:
            adapter.get_project(alpha["project_id"])
        except OpenDesignNotFound:
            pass
        else:
            raise OfficialReleaseError("beta read an alpha OpenDesign project by id")
        alpha_asset = str(alpha["asset_paths"][0])
        try:
            adapter.read_file(alpha["project_id"], alpha_asset)
        except OpenDesignNotFound:
            pass
        else:
            raise OfficialReleaseError("beta read an alpha native asset by identity")
        beta_assets = {
            str(item.get("path") or item.get("name") or "")
            for project_id in projects
            for item in adapter.list_files(project_id)
        }
        if set(alpha["asset_paths"]) & beta_assets:
            raise OfficialReleaseError("alpha native assets leaked into beta workspace")
    model_access.assert_requests_since(correct_request_start, workspace_id="beta")
    _assert_profile_contains_no_capability(native, model_access_token)
    denial_start = model_access.denial_count
    # Present the stolen alpha capability with its own catalog model so the
    # trusted model check succeeds and the executor must still reject beta's
    # project path from the alpha data-root scope.
    _profile(native, _CatalogClient("model/beta", CLI_MODEL_ID))
    with _running_profiled_official(
        installation,
        native=native,
        opencode_runtime=opencode_runtime,
        model_access=model_access,
        model_access_token=alpha["_model_access_token"],
        timeout_seconds=timeout_seconds,
        log_path=root / "beta-cross-capability.log",
    ) as client:
        _assert_native_run_rejected(
            client,
            adapter=_DelegationApi(client),
            project_id=project_id,
            conversation_id=conversation_id,
            message_id="beta-cross-capability-e2e",
            agent_id=CLI_AGENT_ID,
            model=CLI_MODEL_ID,
            timeout_seconds=timeout_seconds,
        )
    model_access.assert_denial_since(
        denial_start,
        workspace_id="alpha",
        reason="workspace_project",
    )
    _assert_profile_contains_no_capability(native, alpha["_model_access_token"])
    return {
        "native_data_separate": True,
        "delegation_store_separate": True,
        "same_key_workspace_scoped": True,
        "assets_separate": True,
        "models_separate": True,
        "credentials_separate": True,
        "cross_project_denied": True,
        "cross_asset_denied": True,
        "cross_model_denied": True,
        "cross_capability_denied": True,
    }


def _prove_official_cancellation(
    client: OfficialApiClient,
    *,
    model_client: _E2EModelClient,
    project_id: str,
    conversation_id: str,
    timeout_seconds: float,
) -> None:
    model_client.reset_cancellation()
    started = client.send_json("POST", "/api/runs", {
        "message": CANCEL_MARKER,
        "currentPrompt": CANCEL_MARKER,
        "projectId": project_id,
        "conversationId": conversation_id,
        "sessionMode": "design",
        "assistantMessageId": "assistant-cancel-e2e",
        "clientRequestId": "native-product-cancel-e2e",
        "attachments": [],
        "agentId": API_AGENT_ID,
        "model": API_MODEL_ID,
    })
    run_id = str(started.get("runId") or "")
    if not run_id or not model_client.slow_started.wait(timeout_seconds):
        raise OfficialReleaseError("OpenCode cancellation stream did not start")
    client.send_json("POST", f"/api/runs/{run_id}/cancel", {})
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = str(client.get_json(f"/api/runs/{run_id}").get("status") or "")
        if status in TERMINAL:
            if status != "canceled":
                raise OfficialReleaseError(f"OpenCode cancellation ended as {status}")
            break
        time.sleep(0.05)
    else:
        raise OfficialReleaseError("OpenCode cancellation did not become terminal")
    if not model_client.slow_closed.wait(timeout_seconds):
        raise OfficialReleaseError("OpenCode cancellation did not close the upstream stream")


def _prove_official_cli_cancellation(
    client: OfficialApiClient,
    *,
    model_access: _E2ECliBroker,
    project_id: str,
    conversation_id: str,
    timeout_seconds: float,
) -> None:
    model_access.reset_cli_cancellation()
    started = client.send_json("POST", "/api/runs", {
        "message": CLI_CANCEL_MARKER,
        "currentPrompt": CLI_CANCEL_MARKER,
        "projectId": project_id,
        "conversationId": conversation_id,
        "sessionMode": "design",
        "assistantMessageId": "assistant-cli-cancel-e2e",
        "clientRequestId": "native-product-cli-cancel-e2e",
        "attachments": [],
        "agentId": CLI_AGENT_ID,
        "model": CLI_MODEL_ID,
    })
    run_id = str(started.get("runId") or "")
    if not run_id or not model_access.cli_slow_started.wait(timeout_seconds):
        raise OfficialReleaseError("Codex CLI cancellation stream did not start")
    client.send_json("POST", f"/api/runs/{run_id}/cancel", {})
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = str(client.get_json(f"/api/runs/{run_id}").get("status") or "")
        if status in TERMINAL:
            if status != "canceled":
                raise OfficialReleaseError(f"Codex CLI cancellation ended as {status}")
            break
        time.sleep(0.05)
    else:
        raise OfficialReleaseError("Codex CLI cancellation did not become terminal")
    if not model_access.cli_slow_closed.wait(timeout_seconds):
        raise OfficialReleaseError("Codex CLI cancellation did not close the broker stream")


def _assert_native_run_rejected(
    client: OfficialApiClient,
    *,
    adapter: "_DelegationApi",
    project_id: str,
    conversation_id: str,
    message_id: str,
    agent_id: str,
    model: str,
    timeout_seconds: float,
) -> None:
    now = int(time.time() * 1000)
    text = f"cross-workspace denial proof {message_id}"
    adapter.put_message(
        project_id,
        conversation_id,
        message_id,
        {
            "role": "user",
            "content": text,
            "attachments": [],
            "startedAt": now,
            "endedAt": now,
        },
    )
    try:
        started = client.send_json("POST", "/api/runs", {
            "message": text,
            "currentPrompt": text,
            "projectId": project_id,
            "conversationId": conversation_id,
            "sessionMode": "design",
            "assistantMessageId": f"assistant-{message_id}",
            "clientRequestId": f"native-product-{message_id}",
            "attachments": [],
            "agentId": agent_id,
            "model": model,
        })
    except OfficialReleaseError as error:
        if "HTTP 4" not in str(error):
            raise
        return
    run_id = str(started.get("runId") or "")
    if not run_id:
        raise OfficialReleaseError("cross-workspace denial returned no run identity")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = str(client.get_json(f"/api/runs/{run_id}").get("status") or "")
        if status in TERMINAL:
            if status != "failed":
                raise OfficialReleaseError(
                    f"cross-workspace model or capability unexpectedly ended as {status}"
                )
            return
        time.sleep(0.05)
    raise OfficialReleaseError("cross-workspace denial did not become terminal")


def _run_direct_native_turn(
    client: OfficialApiClient,
    *,
    adapter: "_DelegationApi",
    project_id: str,
    conversation_id: str,
    message_id: str,
    assistant_message_id: str,
    text: str,
    agent_id: str,
    model: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    now = int(time.time() * 1000)
    saved = adapter.put_message(
        project_id,
        conversation_id,
        message_id,
        {
            "role": "user",
            "content": text,
            "attachments": [],
            "startedAt": now,
            "endedAt": now,
        },
    )
    if saved.get("id") != message_id:
        raise OfficialReleaseError("OpenDesign did not persist a direct native user turn")
    started = client.send_json("POST", "/api/runs", {
        "message": text,
        "currentPrompt": text,
        "projectId": project_id,
        "conversationId": conversation_id,
        "sessionMode": "design",
        "assistantMessageId": assistant_message_id,
        "clientRequestId": f"native-product-{message_id}",
        "attachments": [],
        "agentId": agent_id,
        "model": model,
    })
    run_id = str(started.get("runId") or "")
    if not run_id:
        raise OfficialReleaseError("OpenDesign did not start the direct native run")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = str(client.get_json(f"/api/runs/{run_id}").get("status") or "")
        if status in TERMINAL:
            if status != "succeeded":
                raise OfficialReleaseError(f"direct native run ended as {status}")
            return started
        time.sleep(0.05)
    raise OfficialReleaseError("direct native run did not become terminal")


def _assert_native_selector(
    client: OfficialApiClient,
    *,
    api_model_id: str,
    cli_model_id: str,
    forbidden_models: set[str] | None = None,
) -> dict[str, bool]:
    agents = {
        str(agent.get("id") or ""): agent
        for agent in client.get_json("/api/agents").get("agents", [])
        if isinstance(agent, dict)
    }
    api = agents.get(API_AGENT_ID, {})
    cli = agents.get(CLI_AGENT_ID, {})
    api_models = {
        str(model.get("id") or "")
        for model in api.get("models", [])
        if isinstance(model, dict)
    }
    cli_models = {
        str(model.get("id") or "")
        for model in cli.get("models", [])
        if isinstance(model, dict)
    }
    if api.get("available") is not True or api_model_id not in api_models:
        raise OfficialReleaseError("the real OpenDesign selector omitted the API profile")
    if cli.get("available") is not True or cli_model_id not in cli_models:
        raise OfficialReleaseError("the real OpenDesign selector omitted the CLI profile")
    if (api_models | cli_models) & (forbidden_models or set()):
        raise OfficialReleaseError("a model from another workspace leaked into the selector")
    return {"api_profile": True, "cli_profile": True, "api_model": True}


def _wait_delegation(
    service: DelegationService,
    response: dict[str, Any],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    delegation_id = str(response["delegation"]["delegation_id"])
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        record = service.status(delegation_id)["delegation"]
        if record["status"] in TERMINAL:
            if record["status"] != "succeeded":
                raise OfficialReleaseError(
                    f"native delegated run ended as {record['status']}"
                )
            return record
        time.sleep(0.05)
    raise OfficialReleaseError("native delegated run did not become terminal")


class _DelegationApi:
    def __init__(self, client: OfficialApiClient) -> None:
        self.client = client

    def list_projects(self) -> list[dict[str, Any]]:
        return _objects(self._get("/api/projects"), "projects")

    def get_project(self, project_id: str) -> dict[str, Any]:
        project = self._get(f"/api/projects/{project_id}").get("project")
        return project if isinstance(project, dict) else {}

    def create_project(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._send("POST", "/api/projects", body)

    def list_conversations(self, project_id: str) -> list[dict[str, Any]]:
        return _objects(self._get(f"/api/projects/{project_id}/conversations"), "conversations")

    def create_conversation(self, project_id: str, body: dict[str, Any]) -> dict[str, Any]:
        value = self._send("POST", f"/api/projects/{project_id}/conversations", body).get("conversation")
        return value if isinstance(value, dict) else {}

    def list_messages(self, project_id: str, conversation_id: str) -> list[dict[str, Any]]:
        return _objects(
            self._get(f"/api/projects/{project_id}/conversations/{conversation_id}/messages"),
            "messages",
        )

    def put_message(
        self,
        project_id: str,
        conversation_id: str,
        message_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        value = self._send(
            "PUT",
            f"/api/projects/{project_id}/conversations/{conversation_id}/messages/{message_id}",
            body,
        ).get("message")
        return value if isinstance(value, dict) else {}

    def upload_file(self, project_id: str, body: dict[str, Any]) -> dict[str, Any]:
        value = self._send("POST", f"/api/projects/{project_id}/files", body).get("file")
        return value if isinstance(value, dict) else {}

    def list_files(self, project_id: str) -> list[dict[str, Any]]:
        return _objects(self._get(f"/api/projects/{project_id}/files"), "files")

    def read_file(self, project_id: str, path: str) -> bytes:
        try:
            return self.client.get_bytes(
                f"/api/projects/{project_id}/files/{quote(path, safe='/')}"
            )
        except OfficialReleaseError as error:
            _raise_delegation_api(error)

    def start_run(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._send("POST", "/api/runs", body)

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._get(f"/api/runs/{run_id}")

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        return self._send("POST", f"/api/runs/{run_id}/cancel", {})

    def get_result_package(self, run_id: str) -> dict[str, Any]:
        return self._get(f"/api/runs/{run_id}/result-package")

    def _get(self, path: str) -> dict[str, Any]:
        try:
            return self.client.get_json(path)
        except OfficialReleaseError as error:
            _raise_delegation_api(error)

    def _send(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.client.send_json(method, path, body)
        except OfficialReleaseError as error:
            _raise_delegation_api(error)


def _raise_delegation_api(error: OfficialReleaseError) -> None:
    if "HTTP 404" in str(error):
        raise OpenDesignNotFound("not found") from error
    raise OpenDesignRequestFailed(502) from error


def _objects(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


@contextmanager
def _running_profiled_official(
    installation: OfficialInstallation,
    *,
    native: Path,
    opencode_runtime: Path,
    model_access: _E2ECliBroker,
    model_access_token: str,
    timeout_seconds: float,
    log_path: Path,
) -> Iterator[OfficialApiClient]:
    port = _unused_port()
    token = secrets.token_urlsafe(32)
    old_socket = os.environ.get("MAVERICK_MODEL_ACCESS_SOCKET")
    old_token = os.environ.get("MAVERICK_MODEL_ACCESS_TOKEN")
    os.environ["MAVERICK_MODEL_ACCESS_SOCKET"] = "/model-access/broker.sock"
    os.environ["MAVERICK_MODEL_ACCESS_TOKEN"] = model_access_token
    try:
        command, environment, cwd = build_native_launch(
            release=installation.release,
            rootfs=installation.rootfs,
            data_dir=native,
            host="127.0.0.1",
            port=port,
            api_token=token,
            model_profile_path=SANDBOX_PROFILE_PATH,
        )
    finally:
        _restore_env("MAVERICK_MODEL_ACCESS_SOCKET", old_socket)
        _restore_env("MAVERICK_MODEL_ACCESS_TOKEN", old_token)
    command, environment, cwd = _sandboxed_native_launch(
        command,
        environment=environment,
        cwd=cwd,
        installation=installation,
        native=native,
        opencode_runtime=opencode_runtime,
        model_access=model_access.root,
    )
    process: subprocess.Popen[bytes] | None = None
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log:
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            client = OfficialApiClient(
                port=port,
                token=token,
                request_timeout_seconds=min(60.0, max(10.0, timeout_seconds)),
            )
            _wait_ready(process, client=client, timeout_seconds=timeout_seconds)
            yield client
        finally:
            if process is not None:
                _stop_process(process)


def _profile(native: Path, model_client: Any) -> Path:
    profile, _summary = write_model_access_profiles(native, model_client)
    return profile


def _sandboxed_native_launch(
    command: list[str],
    *,
    environment: dict[str, str],
    cwd: Path,
    installation: OfficialInstallation,
    native: Path,
    opencode_runtime: Path,
    model_access: Path,
) -> tuple[list[str], dict[str, str], Path]:
    """Run the unchanged daemon with the exact app/artifact paths used by Core."""
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise OfficialReleaseError("bubblewrap is required for the native sandbox E2E proof")
    artifact_namespace = installation.path.parents[1].resolve()
    rootfs = installation.rootfs.resolve()
    try:
        sandbox_rootfs = Path("/artifacts/opendesign") / rootfs.relative_to(artifact_namespace)
    except ValueError as error:
        raise OfficialReleaseError("official installation escaped its artifact namespace") from error
    sandbox_data = Path("/data/opendesign-native")
    translated_environment = {
        key: _translate_sandbox_path(
            value,
            rootfs=rootfs,
            sandbox_rootfs=sandbox_rootfs,
            native=native,
            sandbox_data=sandbox_data,
        )
        for key, value in environment.items()
    }
    translated_command = [
        _translate_sandbox_path(
            value,
            rootfs=rootfs,
            sandbox_rootfs=sandbox_rootfs,
            native=native,
            sandbox_data=sandbox_data,
        )
        for value in command
    ]
    translated_cwd = Path(_translate_sandbox_path(
        str(cwd),
        rootfs=rootfs,
        sandbox_rootfs=sandbox_rootfs,
        native=native,
        sandbox_data=sandbox_data,
    ))
    sandbox_runtime = Path("/artifacts/opendesign/opencode/1.14.17")
    confined = [
        bwrap,
        "--die-with-parent",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--tmpfs",
        "/",
        "--dir",
        "/usr",
        "--ro-bind",
        "/usr",
        "/usr",
        "--symlink",
        "usr/bin",
        "/bin",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/lib64",
        "/lib64",
        "--dir",
        "/etc",
        "--ro-bind",
        "/etc",
        "/etc",
        "--dir",
        "/app",
        "--ro-bind",
        str(APP_ROOT),
        "/app",
        "--dir",
        "/artifacts",
        "--dir",
        "/artifacts/opendesign",
        "--ro-bind",
        str(artifact_namespace),
        "/artifacts/opendesign",
        "--ro-bind",
        str(opencode_runtime.resolve()),
        str(sandbox_runtime),
        "--dir",
        "/data",
        "--dir",
        str(sandbox_data),
        "--bind",
        str(native.resolve()),
        str(sandbox_data),
        "--dir",
        "/model-access",
        "--ro-bind",
        str(model_access.resolve()),
        "/model-access",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        "/run",
        "--chdir",
        str(translated_cwd),
        "--",
        *translated_command,
    ]
    return confined, translated_environment, Path("/")


def _translate_sandbox_path(
    value: str,
    *,
    rootfs: Path,
    sandbox_rootfs: Path,
    native: Path,
    sandbox_data: Path,
) -> str:
    return value.replace(str(rootfs), str(sandbox_rootfs)).replace(
        str(native.resolve()),
        str(sandbox_data),
    )


def _assert_profile_contains_no_capability(native: Path, token: str) -> None:
    rendered = "\n".join(
        (native / relative).read_text(encoding="utf-8")
        for relative in (SANDBOX_PROFILE_PATH.relative_to("/data/opendesign-native"), API_CONFIG_PATH)
    )
    if token in rendered:
        raise OfficialReleaseError("a model-access capability was persisted in native data")


def _json_object(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _scope_contains_cwd(scope: ModelAccessScope, cwd: str) -> bool:
    sidecar_path = PurePosixPath(cwd)
    if (
        not sidecar_path.is_absolute()
        or sidecar_path.parts[:3] != ("/", "data", "opendesign-native")
        or ".." in sidecar_path.parts
    ):
        return False
    root = scope.data_root.resolve(strict=True)
    try:
        candidate = root.joinpath(*sidecar_path.parts[3:]).resolve(strict=True)
    except OSError:
        return False
    return candidate == root or root in candidate.parents


def _unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


if __name__ == "__main__":
    try:
        main()
    except (OfficialReleaseError, DelegationError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from error
