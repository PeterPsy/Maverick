"""Thin process host for the unchanged official OpenDesign OCI rootfs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import stat
import subprocess
from typing import Any

from official_opendesign_release import (
    OfficialReleaseError,
    load_official_release,
    verify_official_installation,
)
from native_cutover_quiescence import reject_if_native_host_quiesced
from native_cutover_state import NativeDataCutoverError
from model_access_client import ModelAccessClient, ModelAccessClientError, ModelAccessConfiguration
from model_access_profiles import (
    SANDBOX_PROFILE_PATH,
    remove_model_access_profiles,
    write_model_access_profiles,
)
from model_access_server import (
    MODEL_ACCESS_API_KEY,
    MODEL_ACCESS_BASE_URL,
    ModelAccessHttpBridge,
)


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
OFFICIAL_STORE_MOUNT = Path("/artifacts/opendesign")
HOST_STATUS_FILE = "native-host-status.json"


def main() -> None:
    host = _required_env("OD_BIND_HOST")
    if host not in LOOPBACK_HOSTS:
        raise SystemExit(f"OpenDesign sidecar must bind to loopback, got {host!r}.")
    port = _port(_required_env("OD_PORT"))
    api_token = _required_env("OD_API_TOKEN")
    store_root = _required_directory(
        Path(_required_env("MAVERICK_OPENDESIGN_STORE_ROOT")),
        expected=OFFICIAL_STORE_MOUNT,
        label="official OpenDesign artifact store",
    )
    data_dir = _required_directory(
        Path(_required_env("MAVERICK_OPENDESIGN_DATA_DIR")),
        create=True,
        label="OpenDesign data directory",
    )
    try:
        reject_if_native_host_quiesced(data_dir.parent)
    except NativeDataCutoverError as error:
        raise OfficialReleaseError(str(error)) from error
    release = load_official_release()
    installation_path = store_root / "official" / release.digest_key
    installation = verify_official_installation(installation_path, expected_release=release)
    model_bridge, model_status, model_profile_path = _configure_model_access(data_dir)
    _write_bridge_capabilities(
        data_dir.parent,
        {
            "schema_version": "1",
            "model_access": model_status,
            "delegation": {
                "state": "disabled",
                "reason": "not_configured",
            },
        },
    )
    command, environment, cwd = build_native_launch(
        rootfs=installation.rootfs,
        data_dir=data_dir,
        host=host,
        port=port,
        api_token=api_token,
        model_profile_path=model_profile_path,
    )
    _write_host_status(
        data_dir.parent,
        {
            "schema_version": "1",
            "state": "starting",
            "mode": "official-native",
            "image": release.image,
            "version": release.version,
            "manifest_digest": release.manifest_digest,
            "rootfs_snapshot_sha256": installation.rootfs_snapshot_sha256,
            "customizations": [],
            "model_bridge": model_status,
            "delegation_bridge": os.environ.get("MAVERICK_OPENDESIGN_DELEGATION_BRIDGE", "disabled"),
        },
    )
    try:
        os.chdir(cwd)
        if model_bridge is None:
            os.execve(command[0], command, environment)
        _supervise_official_process(
            command,
            environment=environment,
            cwd=cwd,
            model_bridge=model_bridge,
        )
    except OSError as error:
        raise SystemExit(f"Official OpenDesign process could not start: {error}") from error


def build_native_launch(
    *,
    rootfs: Path,
    data_dir: Path,
    host: str,
    port: int,
    api_token: str,
    model_profile_path: Path | None = None,
) -> tuple[list[str], dict[str, str], Path]:
    """Build the official OCI entrypoint inside Core's artifact-root sandbox.

    The outer Maverick sandbox owns authentication, workspace binding, network
    isolation, the Unix relay, and the read-only official OCI execution root.
    Only the upstream data volume is writable.
    """
    release = load_official_release()
    root = _required_directory(rootfs, label="official OpenDesign rootfs")
    data = _required_directory(data_dir, create=True, label="OpenDesign data directory")
    if host not in LOOPBACK_HOSTS:
        raise OfficialReleaseError("official OpenDesign must bind to loopback")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise OfficialReleaseError("official OpenDesign port is invalid")
    if not isinstance(api_token, str) or not api_token or "\x00" in api_token:
        raise OfficialReleaseError("official OpenDesign API token is invalid")
    _require_official_runtime_files(root)
    environment = {
        "DO_NOT_TRACK": "1",
        "HOME": "/app/.od/sandbox/agent-home",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "MAVERICK_OPENDESIGN_DELEGATION_BRIDGE": os.environ.get(
            "MAVERICK_OPENDESIGN_DELEGATION_BRIDGE", "disabled"
        ),
        "MAVERICK_OPENDESIGN_MODEL_BRIDGE": os.environ.get(
            "MAVERICK_OPENDESIGN_MODEL_BRIDGE", "disabled"
        ),
        "NEXT_TELEMETRY_DISABLED": "1",
        "NODE_ENV": "production",
        "OD_API_TOKEN": api_token,
        "OD_BIND_HOST": host,
        "OD_DATA_DIR": str(data),
        "OD_PORT": str(port),
        "OD_REQUIRE_API_TOKEN_ON_LOOPBACK": "1",
        "OD_SANDBOX_MODE": "1",
        "PATH": "/maverick/app/service:/usr/local/bin:/usr/bin:/bin",
        "TMPDIR": "/tmp",
        "TINI_SUBREAPER": "1",
        "TZ": "UTC",
    }
    if model_profile_path is not None:
        environment.update(
            {
                "MAVERICK_MODEL_ACCESS_SOCKET": _required_env("MAVERICK_MODEL_ACCESS_SOCKET"),
                "MAVERICK_MODEL_ACCESS_STATE": "available",
                "MAVERICK_MODEL_ACCESS_TOKEN": _required_env("MAVERICK_MODEL_ACCESS_TOKEN"),
                "ALL_PROXY": "",
                "HTTP_PROXY": "",
                "HTTPS_PROXY": "",
                "NO_PROXY": "*",
                "all_proxy": "",
                "http_proxy": "",
                "https_proxy": "",
                "no_proxy": "*",
                "OD_ALLOWED_INTERNAL_HOSTS": "127.0.0.1,localhost",
                "OD_AGENT_PROFILES_CONFIG": model_profile_path.as_posix(),
                "OD_CODEX_DISABLE_PLUGINS": "1",
                "OD_CODEX_SANDBOX": "danger-full-access",
            }
        )
    command = [*release.entrypoint, *release.command]
    return command, environment, Path(release.working_directory)


def _configure_model_access(
    data_dir: Path,
) -> tuple[ModelAccessHttpBridge | None, dict[str, Any], Path | None]:
    remove_model_access_profiles(data_dir)
    try:
        configuration = ModelAccessConfiguration.from_environment()
        client = ModelAccessClient(configuration)
    except ModelAccessClientError:
        return None, {"state": "degraded", "reason": "core_broker_unavailable"}, None

    cli_status: dict[str, Any]
    profile_path: Path | None = None
    try:
        _host_profile, profile = write_model_access_profiles(data_dir, client)
        profile_path = SANDBOX_PROFILE_PATH
        cli_status = {"state": "ready", **profile}
    except Exception:
        remove_model_access_profiles(data_dir)
        cli_status = {"state": "degraded", "reason": "cli_profile_unavailable"}

    bridge: ModelAccessHttpBridge | None = None
    try:
        bridge = ModelAccessHttpBridge(client)
        bridge.start()
        api_status: dict[str, Any] = {
            "state": "ready",
            "protocol": "openai-compatible",
            "base_url": MODEL_ACCESS_BASE_URL,
            "credential_handle": MODEL_ACCESS_API_KEY,
        }
    except Exception:
        api_status = {"state": "degraded", "reason": "api_endpoint_unavailable"}
    state = "ready" if api_status["state"] == cli_status["state"] == "ready" else "degraded"
    return bridge, {
        "state": state,
        "semantic_enrichment": False,
        "api": api_status,
        "cli": cli_status,
    }, profile_path


def _supervise_official_process(
    command: list[str],
    *,
    environment: dict[str, str],
    cwd: Path,
    model_bridge: ModelAccessHttpBridge,
) -> None:
    process = subprocess.Popen(command, cwd=cwd, env=environment)
    previous: dict[signal.Signals, Any] = {}

    def forward(signum, _frame) -> None:
        if process.poll() is None:
            process.send_signal(signum)

    try:
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, forward)
        exit_code = process.wait()
    finally:
        model_bridge.stop()
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    raise SystemExit(exit_code)


def _require_official_runtime_files(rootfs: Path) -> None:
    for relative in (
        "app/apps/daemon/dist/cli.js",
        "app/apps/web/out/index.html",
        "usr/local/bin/node",
        "lib/ld-musl-x86_64.so.1",
        "sbin/tini",
    ):
        path = rootfs / relative
        try:
            metadata = path.lstat()
        except OSError as error:
            raise OfficialReleaseError(f"official OpenDesign rootfs is missing {relative}") from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise OfficialReleaseError(f"official OpenDesign rootfs path is unsafe: {relative}")


def _required_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value or "\x00" in value:
        raise SystemExit(f"{name} is required.")
    return value


def _required_directory(
    path: Path,
    *,
    expected: Path | None = None,
    create: bool = False,
    label: str,
) -> Path:
    if expected is not None and path != expected:
        raise OfficialReleaseError(f"{label} must use the declared capability mount")
    if create:
        path.mkdir(parents=True, exist_ok=True)
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise OfficialReleaseError(f"{label} is unavailable") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise OfficialReleaseError(f"{label} must be a real directory")
    return resolved


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise SystemExit("OD_PORT must be an integer.") from error
    if not 1 <= port <= 65535:
        raise SystemExit("OD_PORT is outside the valid range.")
    return port


def _write_host_status(root: Path, payload: dict[str, Any]) -> None:
    _write_private_json(root / HOST_STATUS_FILE, payload)


def _write_bridge_capabilities(root: Path, payload: dict[str, Any]) -> None:
    _write_private_json(root / "bridge-capabilities.json", payload)


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        os.write(descriptor, body)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


if __name__ == "__main__":
    try:
        main()
    except OfficialReleaseError as error:
        raise SystemExit(str(error)) from error
