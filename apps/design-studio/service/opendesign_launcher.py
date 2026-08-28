"""Thin process host for the unchanged official OpenDesign OCI rootfs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

from official_opendesign_release import (
    OfficialReleaseError,
    load_official_release,
    verify_official_installation,
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
    release = load_official_release()
    installation_path = store_root / "official" / release.digest_key
    installation = verify_official_installation(installation_path, expected_release=release)
    command, environment, cwd = build_native_launch(
        rootfs=installation.rootfs,
        data_dir=data_dir,
        host=host,
        port=port,
        api_token=api_token,
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
            "model_bridge": os.environ.get("MAVERICK_OPENDESIGN_MODEL_BRIDGE", "disabled"),
            "delegation_bridge": os.environ.get("MAVERICK_OPENDESIGN_DELEGATION_BRIDGE", "disabled"),
        },
    )
    try:
        os.chdir(cwd)
        os.execve(command[0], command, environment)
    except OSError as error:
        raise SystemExit(f"Official OpenDesign process could not start: {error}") from error


def build_native_launch(
    *,
    rootfs: Path,
    data_dir: Path,
    host: str,
    port: int,
    api_token: str,
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
        "NODE_OPTIONS": "--max-old-space-size=192",
        "OD_API_TOKEN": api_token,
        "OD_BIND_HOST": host,
        "OD_DATA_DIR": str(data),
        "OD_PORT": str(port),
        "OD_REQUIRE_API_TOKEN_ON_LOOPBACK": "1",
        "OD_SANDBOX_MODE": "1",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "TMPDIR": "/tmp",
        "TINI_SUBREAPER": "1",
        "TZ": "UTC",
    }
    command = [*release.entrypoint, *release.command]
    return command, environment, Path(release.working_directory)


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
    path = root / HOST_STATUS_FILE
    temporary = root / f".{HOST_STATUS_FILE}.{os.getpid()}.tmp"
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
