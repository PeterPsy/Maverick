#!/usr/bin/env python3
"""Exercise the native model, delegation, continuation, and isolation paths."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
from threading import Event, Lock
import time
from types import SimpleNamespace
from typing import Any, Iterator


APP_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = APP_ROOT.parents[1]
BACKEND_ROOT = APP_ROOT / "backend"
sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

from delegation_errors import DelegationError  # noqa: E402
from delegation_service import DelegationService  # noqa: E402
from model_access_profiles import API_CONFIG_PATH, write_model_access_profiles  # noqa: E402
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
STREAM_MARKER = "native-e2e-stream"
CANCEL_MARKER = "official-cancel-e2e"
TERMINAL = {"succeeded", "failed", "canceled"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installation", type=Path, required=True)
    parser.add_argument("--opencode-runtime", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    args = parser.parse_args()

    installation = verify_official_installation(args.installation)
    opencode = verify_opencode_runtime(args.opencode_runtime)
    codex = shutil.which("codex")
    if not codex:
        raise OfficialReleaseError("Codex CLI is required for the native selector E2E proof")

    model_client = _E2EModelClient()
    bridge = ModelAccessHttpBridge(model_client)
    bridge.start()
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="design-studio-native-product-e2e-") as temporary:
            root = Path(temporary)
            wrappers = _write_wrappers(root / "bin", opencode=opencode, codex=Path(codex))
            transport = _prove_opencode_streaming(
                opencode,
                model_client=model_client,
                root=root / "transport",
                timeout_seconds=args.timeout_seconds,
            )
            alpha = _exercise_alpha_workspace(
                installation,
                model_client=model_client,
                root=root / "alpha",
                wrappers=wrappers,
                timeout_seconds=args.timeout_seconds,
            )
            beta = _exercise_beta_workspace(
                installation,
                model_client=model_client,
                root=root / "beta",
                wrappers=wrappers,
                alpha=alpha,
                timeout_seconds=args.timeout_seconds,
            )
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
        },
        "opencode": {
            "streaming": transport["streaming"],
            "cancellation": alpha["cancellation"],
        },
        "delegation": {
            "conversation_continued": alpha["conversation_continued"],
            "visible_user_message_count": alpha["visible_user_message_count"],
        },
        "workspace_isolation": beta,
    }, indent=2, sort_keys=True))


class _E2EModelClient:
    def __init__(self) -> None:
        self.slow_started = Event()
        self.slow_closed = Event()
        self._lock = Lock()
        self.request_count = 0

    def catalog(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "api_models": [{
                "id": "model/exact",
                "label": "Exact E2E API",
                "provider_id": "e2e",
                "transport": "api",
                "available": True,
            }],
            "cli_models": [{
                "id": "gpt-e2e",
                "label": "Codex E2E",
                "provider_id": "codex",
                "transport": "cli",
                "available": True,
            }],
            "cli_defaults": {"codex": "gpt-e2e"},
        }

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
    model_client: _E2EModelClient,
    root: Path,
    wrappers: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    native = root / "opendesign-native"
    native.mkdir(parents=True)
    _profile(native, model_client)
    payload = SimpleNamespace(app_id="design-studio", workspace_id="alpha", data_root=str(root))
    first_arguments = {
        "idempotency_key": "shared-e2e-key",
        "brief": "alpha first delegated brief",
        "agent_id": API_AGENT_ID,
        "model": API_MODEL_ID,
    }
    with _running_profiled_official(
        installation,
        native=native,
        wrappers=wrappers,
        timeout_seconds=timeout_seconds,
        log_path=root / "alpha-first.log",
    ) as client:
        selector = _assert_native_selector(client)
        service = DelegationService(payload, client=_DelegationApi(client))
        first = service.delegate(first_arguments)
        first_record = _wait_delegation(service, first, timeout_seconds=timeout_seconds)
        project_id = first_record["opendesign"]["project_id"]
        conversation_id = first_record["opendesign"]["conversation_id"]
        first_delegation_id = first_record["delegation_id"]

    with _running_profiled_official(
        installation,
        native=native,
        wrappers=wrappers,
        timeout_seconds=timeout_seconds,
        log_path=root / "alpha-continuation.log",
    ) as client:
        adapter = _DelegationApi(client)
        service = DelegationService(payload, client=adapter)
        second = service.delegate({
            "idempotency_key": "alpha-continuation-key",
            "brief": "alpha continued delegated brief",
            "project_id": project_id,
            "conversation_id": conversation_id,
            "agent_id": API_AGENT_ID,
            "model": API_MODEL_ID,
        })
        second_record = _wait_delegation(service, second, timeout_seconds=timeout_seconds)
        messages = adapter.list_messages(project_id, conversation_id)
        visible = [
            str(message.get("content") or "")
            for message in messages
            if message.get("role") == "user"
        ]
        if not all(
            brief in "\n".join(visible)
            for brief in ("alpha first delegated brief", "alpha continued delegated brief")
        ):
            raise OfficialReleaseError("delegated conversation continuation was not persisted")
        _prove_official_cancellation(
            client,
            model_client=model_client,
            project_id=project_id,
            conversation_id=conversation_id,
            timeout_seconds=timeout_seconds,
        )

    return {
        **selector,
        "cancellation": True,
        "conversation_continued": second_record["opendesign"]["conversation_id"] == conversation_id,
        "visible_user_message_count": len(visible),
        "delegation_id": first_delegation_id,
        "project_id": project_id,
    }


def _exercise_beta_workspace(
    installation: OfficialInstallation,
    *,
    model_client: _E2EModelClient,
    root: Path,
    wrappers: Path,
    alpha: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, bool]:
    native = root / "opendesign-native"
    native.mkdir(parents=True)
    _profile(native, model_client)
    payload = SimpleNamespace(app_id="design-studio", workspace_id="beta", data_root=str(root))
    with _running_profiled_official(
        installation,
        native=native,
        wrappers=wrappers,
        timeout_seconds=timeout_seconds,
        log_path=root / "beta.log",
    ) as client:
        adapter = _DelegationApi(client)
        service = DelegationService(payload, client=adapter)
        beta = service.delegate({
            "idempotency_key": "shared-e2e-key",
            "brief": "beta isolated delegated brief",
            "agent_id": API_AGENT_ID,
            "model": API_MODEL_ID,
        })
        beta_record = _wait_delegation(service, beta, timeout_seconds=timeout_seconds)
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
    return {
        "native_data_separate": True,
        "delegation_store_separate": True,
        "same_key_workspace_scoped": True,
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


def _assert_native_selector(client: OfficialApiClient) -> dict[str, bool]:
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
    if api.get("available") is not True or API_MODEL_ID not in api_models:
        raise OfficialReleaseError("the real OpenDesign selector omitted the API profile")
    if cli.get("available") is not True or not cli.get("models"):
        raise OfficialReleaseError("the real OpenDesign selector omitted the CLI profile")
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
    wrappers: Path,
    timeout_seconds: float,
    log_path: Path,
) -> Iterator[OfficialApiClient]:
    port = _unused_port()
    token = secrets.token_urlsafe(32)
    profile = native / "sandbox/agent-home/.maverick/model-access-agents.json"
    old_socket = os.environ.get("MAVERICK_MODEL_ACCESS_SOCKET")
    old_token = os.environ.get("MAVERICK_MODEL_ACCESS_TOKEN")
    os.environ["MAVERICK_MODEL_ACCESS_SOCKET"] = "/native-product-e2e/model-access.sock"
    os.environ["MAVERICK_MODEL_ACCESS_TOKEN"] = "native-product-e2e"
    try:
        command, environment, cwd = build_native_launch(
            release=installation.release,
            rootfs=installation.rootfs,
            data_dir=native,
            host="127.0.0.1",
            port=port,
            api_token=token,
            model_profile_path=profile,
        )
    finally:
        _restore_env("MAVERICK_MODEL_ACCESS_SOCKET", old_socket)
        _restore_env("MAVERICK_MODEL_ACCESS_TOKEN", old_token)
    environment.update({
        "HOME": str(native / "sandbox/agent-home"),
        "OD_AGENT_PROFILES_CONFIG": str(profile),
        "PATH": ":".join((
            str(wrappers),
            str(installation.rootfs / "usr/local/bin"),
            str(installation.rootfs / "usr/bin"),
            "/usr/bin",
            "/bin",
        )),
    })
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
            client = OfficialApiClient(port=port, token=token)
            _wait_ready(process, client=client, timeout_seconds=timeout_seconds)
            yield client
        finally:
            if process is not None:
                _stop_process(process)


def _profile(native: Path, model_client: _E2EModelClient) -> Path:
    profile, _summary = write_model_access_profiles(native, model_client)
    payload = json.loads(profile.read_text(encoding="utf-8"))
    for agent in payload["agents"]:
        if agent.get("id") == API_AGENT_ID:
            agent["env"]["OPENCODE_CONFIG"] = str(native / API_CONFIG_PATH)
    profile.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return profile


def _write_wrappers(root: Path, *, opencode: Path, codex: Path) -> Path:
    root.mkdir(parents=True)
    for name, executable in (("maverick-opencode", opencode), ("maverick-codex", codex)):
        wrapper = root / name
        wrapper.write_text(
            f"#!/bin/sh\nexec {shlex.quote(str(executable))} \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o555)
    return root


def _json_object(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


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
