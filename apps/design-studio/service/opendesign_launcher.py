"""Thin process host for the unchanged official OpenDesign OCI rootfs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any, Callable

from official_opendesign_release import (
    OfficialRelease,
    OfficialReleaseError,
    load_official_release,
    load_official_release_payload,
    verify_official_installation,
)
from official_bridge_contracts import validate_delegation_status
from official_oci_validation import reject_duplicate_pairs
from model_access_client import ModelAccessClient, ModelAccessClientError, ModelAccessConfiguration
from model_access_profiles import (
    SANDBOX_PROFILE_PATH,
    remove_model_access_profiles,
    write_model_access_profiles,
)
from model_access_constants import MODEL_ACCESS_API_KEY, MODEL_ACCESS_BASE_URL
from model_access_server import (
    ModelAccessHttpBridge,
)
from native_profile_bootstrap import NativeProfileBootstrap, preferred_profile_id
from official_inventory_process import OfficialApiClient
from official_process_supervisor import official_api_ready, supervise_official_process
from opencode_runtime import OpenCodeRuntimeError, RUNTIME_RELATIVE_PATH, verify_opencode_runtime


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
OFFICIAL_STORE_MOUNT = Path("/artifacts/opendesign")
SIDECAR_DATA_MOUNT = Path("/data")
SIDECAR_STATUS_MOUNT = Path("/run/maverick/sidecar-status.json")
LAUNCH_CONFIGURATION_ENV = "MAVERICK_APP_OPENDESIGN_LAUNCH_CONFIGURATION"
SIDECAR_STATUS_ENV = "MAVERICK_SIDECAR_STATUS_FILE"


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
        expected=SIDECAR_DATA_MOUNT,
        create=True,
        label="OpenDesign data directory",
    )
    release, delegation_status = _launch_configuration()
    installation_path = store_root / "official" / release.digest_key
    installation = verify_official_installation(installation_path, expected_release=release)
    model_bridge, model_status, model_profile_path = _configure_model_access(
        data_dir,
        artifact_root=store_root,
    )
    status_file = _required_status_file()
    report_status = _host_status_reporter(
        status_file,
        {
            "schema_version": "1",
            "mode": "official-native",
            "image": release.image,
            "version": release.version,
            "manifest_digest": release.manifest_digest,
            "rootfs_snapshot_sha256": installation.rootfs_snapshot_sha256,
            "customizations": [],
            "model_bridge": model_status,
            "delegation_bridge": delegation_status,
            "direct_delegation_bridge": "disabled",
        },
    )
    report_status("starting", None)
    command, environment, cwd = build_native_launch(
        release=release,
        rootfs=installation.rootfs,
        data_dir=data_dir,
        host=host,
        port=port,
        api_token=api_token,
        model_profile_path=model_profile_path,
    )
    profile_bootstrap = NativeProfileBootstrap(
        OfficialApiClient(
            port=port,
            token=api_token,
            request_timeout_seconds=5.0,
        ),
        preferred_profile_id=preferred_profile_id(model_status),
    )

    def native_ready() -> bool:
        return official_api_ready(
            host=host,
            port=port,
            api_token=api_token,
        ) and profile_bootstrap.ensure()

    try:
        os.chdir(cwd)
        supervise_official_process(
            command,
            environment=environment,
            cwd=cwd,
            model_bridge=model_bridge,
            ready_probe=native_ready,
            state_changed=report_status,
        )
    except OSError as error:
        raise SystemExit(f"Official OpenDesign process could not start: {error}") from error


def build_native_launch(
    *,
    release: OfficialRelease | None = None,
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
    selected = release or load_official_release()
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
        "HOME": str(data / "sandbox/agent-home"),
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
        "PATH": ":".join(
            (
                "/app/service",
                str(root / "usr/local/sbin"),
                str(root / "usr/local/bin"),
                str(root / "usr/sbin"),
                str(root / "usr/bin"),
                str(root / "sbin"),
                str(root / "bin"),
            )
        ),
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
    loader = root / "lib/ld-musl-x86_64.so.1"
    tini = root / selected.entrypoint[0].removeprefix("/")
    node = root / "usr/local/bin/node"
    script = root / selected.working_directory.removeprefix("/") / selected.command[1]
    command = [
        str(loader),
        "--library-path",
        f"{root / 'lib'}:{root / 'usr/lib'}",
        str(tini),
        *selected.entrypoint[1:],
        str(loader),
        "--library-path",
        f"{root / 'lib'}:{root / 'usr/lib'}",
        str(node),
        str(script),
        *selected.command[2:],
    ]
    return command, environment, root / selected.working_directory.removeprefix("/")


def _configure_model_access(
    data_dir: Path,
    *,
    artifact_root: Path,
) -> tuple[ModelAccessHttpBridge | None, dict[str, Any], Path | None]:
    remove_model_access_profiles(data_dir)
    mode = os.environ.get("MAVERICK_OPENDESIGN_MODEL_BRIDGE", "disabled")
    if mode == "disabled":
        return None, {
            "state": "disabled",
            "reason": "disabled_by_configuration",
            "semantic_enrichment": False,
        }, None
    if mode not in {"auto", "enabled"}:
        return None, {
            "state": "degraded",
            "reason": "invalid_configuration",
            "semantic_enrichment": False,
        }, None
    try:
        configuration = ModelAccessConfiguration.from_environment()
        client = ModelAccessClient(configuration)
    except ModelAccessClientError:
        return None, {
            "state": "degraded",
            "reason": "core_broker_unavailable",
            "semantic_enrichment": False,
        }, None

    try:
        verify_opencode_runtime(artifact_root / RUNTIME_RELATIVE_PATH)
        opencode_available = True
        opencode_reason = ""
    except OpenCodeRuntimeError:
        opencode_available = False
        opencode_reason = "opencode_runtime_unavailable"

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

    profile_path: Path | None = None
    try:
        api_profile_available = opencode_available and api_status["state"] == "ready"
        unavailable_reason = (
            opencode_reason
            if not opencode_available
            else "api_endpoint_unavailable"
        )
        _host_profile, profile = write_model_access_profiles(
            data_dir,
            client,
            opencode_available=api_profile_available,
            api_unavailable_reason=unavailable_reason,
        )
        profile_path = SANDBOX_PROFILE_PATH
        profile_status: dict[str, Any] = profile
    except Exception:
        remove_model_access_profiles(data_dir)
        profile_status = {"state": "degraded", "reason": "native_profiles_unavailable"}
    state = (
        "ready"
        if api_status["state"] == profile_status["state"] == "ready"
        else "degraded"
    )
    return bridge, {
        "state": state,
        "semantic_enrichment": False,
        "api": api_status,
        "profiles": profile_status,
    }, profile_path


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


def _required_status_file() -> Path:
    path = Path(_required_env(SIDECAR_STATUS_ENV))
    if path != SIDECAR_STATUS_MOUNT:
        raise OfficialReleaseError(
            "sidecar status must use the declared diagnostics capability"
        )
    try:
        metadata = path.lstat()
    except OSError as error:
        raise OfficialReleaseError("sidecar diagnostics capability is unavailable") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise OfficialReleaseError("sidecar diagnostics capability is unsafe")
    return path


def _host_status_reporter(
    status_file: Path,
    base_status: dict[str, Any],
) -> Callable[[str, int | None], None]:
    """Return the lifecycle callback for Core's single-file status capability."""

    def report(state: str, exit_code: int | None) -> None:
        payload = {**base_status, "state": state}
        if exit_code is not None:
            payload["process_exit_code"] = exit_code
        _write_bound_status(status_file, payload)

    return report


def _write_bound_status(path: Path, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    if len(body) > 64 * 1024:
        raise OfficialReleaseError("sidecar diagnostics payload is too large")
    try:
        before = path.lstat()
    except OSError as error:
        raise OfficialReleaseError("sidecar diagnostics capability is unavailable") from error
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.geteuid()
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) != 0o600
    ):
        raise OfficialReleaseError("sidecar diagnostics capability is unsafe")
    flags = os.O_WRONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise OfficialReleaseError(
            "sidecar diagnostics capability could not be opened"
        ) from error
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or opened.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) != 0o600
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise OfficialReleaseError("sidecar diagnostics capability changed")
        os.ftruncate(descriptor, 0)
        remaining = memoryview(body)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("sidecar diagnostics write made no progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
    except OSError as error:
        raise OfficialReleaseError(
            "sidecar diagnostics capability could not be updated"
        ) from error
    finally:
        os.close(descriptor)


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise SystemExit("OD_PORT must be an integer.") from error
    if not 1 <= port <= 65535:
        raise SystemExit("OD_PORT is outside the valid range.")
    return port


def _launch_configuration() -> tuple[OfficialRelease, dict[str, Any]]:
    raw = _required_env(LAUNCH_CONFIGURATION_ENV)
    if len(raw.encode("utf-8")) > 64 * 1024:
        raise OfficialReleaseError("official OpenDesign launch configuration is too large")
    try:
        payload = json.loads(raw, object_pairs_hook=reject_duplicate_pairs)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
        raise OfficialReleaseError(
            "official OpenDesign launch configuration is unreadable"
        ) from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "release", "delegation"}
        or payload.get("schema_version") != "1"
        or not isinstance(payload.get("release"), dict)
    ):
        raise OfficialReleaseError(
            "official OpenDesign launch configuration schema is invalid"
        )
    release = load_official_release_payload(
        payload["release"],
        require_bundled_pin=False,
    )
    try:
        delegation = validate_delegation_status(payload.get("delegation"))
    except ValueError as error:
        raise OfficialReleaseError(
            "official OpenDesign launch delegation status is invalid"
        ) from error
    return release, delegation


if __name__ == "__main__":
    try:
        main()
    except OfficialReleaseError as error:
        raise SystemExit(str(error)) from error
