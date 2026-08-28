#!/usr/bin/env python3
"""Run a disposable native OpenDesign proof with Maverick bridges disabled."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import http.client
import json
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
from typing import Any

from official_opendesign_release import (
    OfficialInstallation,
    OfficialReleaseError,
    launch_disposable_official_release,
    verify_official_installation,
)


PROBE_PATHS = (
    "/",
    "/api/ready",
    "/api/agents",
    "/api/projects",
    "/api/design-systems",
    "/api/skills",
    "/api/app-config",
    "/api/runs",
)
NATIVE_STATIC_MARKERS = ("/_next/static/", "Open Design")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installation", type=Path, required=True)
    parser.add_argument("--data-directory", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()

    installation = verify_official_installation(args.installation)
    if args.data_directory is None:
        with tempfile.TemporaryDirectory(prefix="opendesign-official-smoke-") as temporary:
            evidence = run_native_smoke(
                installation,
                data_dir=Path(temporary),
                timeout_seconds=args.timeout_seconds,
            )
    else:
        args.data_directory.mkdir(parents=True, exist_ok=True)
        evidence = run_native_smoke(
            installation,
            data_dir=args.data_directory,
            timeout_seconds=args.timeout_seconds,
        )
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))


def run_native_smoke(
    installation: OfficialInstallation,
    *,
    data_dir: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Start, probe public native surfaces, and stop the official process."""
    port = _unused_loopback_port()
    token = secrets.token_urlsafe(32)
    log_path = data_dir / "official-smoke.log"
    data_dir.mkdir(parents=True, exist_ok=True)
    process: subprocess.Popen[bytes] | None = None
    started = time.monotonic()
    try:
        with log_path.open("wb") as log:
            process = launch_disposable_official_release(
                installation,
                data_dir=data_dir,
                port=port,
                api_token=token,
                bridge_mode="disabled",
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            probes = _wait_and_probe(
                process,
                port=port,
                token=token,
                timeout_seconds=timeout_seconds,
            )
    finally:
        if process is not None:
            _stop_process(process)
    root_body = str(probes["/"]["body_excerpt"])
    if not any(marker.lower() in root_body.lower() for marker in NATIVE_STATIC_MARKERS):
        raise OfficialReleaseError("official OpenDesign root did not expose the native web application")
    return {
        "schema_version": "1",
        "kind": "official_opendesign_native_smoke",
        "status": "passed",
        "completed_at": datetime.now(tz=UTC).isoformat(),
        "duration_ms": round((time.monotonic() - started) * 1000, 3),
        "official_artifact": {
            "image": installation.release.image,
            "version": installation.release.version,
            "manifest_digest": installation.release.manifest_digest,
            "rootfs_snapshot_sha256": installation.rootfs_snapshot_sha256,
            "customizations": [],
        },
        "bridges": {"model_access": "disabled", "delegation": "disabled"},
        "native_surfaces": probes,
        "maverick_runtime_session_created": False,
        "data_directory": str(data_dir.resolve()),
    }


def _wait_and_probe(
    process: subprocess.Popen[bytes],
    *,
    port: int,
    token: str,
    timeout_seconds: float,
) -> dict[str, dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    last_error = "not ready"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise OfficialReleaseError(f"official OpenDesign exited during native smoke with {process.returncode}")
        try:
            status, headers, body = _request(port, token, "/api/ready")
            if 200 <= status < 300:
                break
            last_error = f"/api/ready returned {status}"
        except (OSError, http.client.HTTPException) as error:
            last_error = str(error)
        time.sleep(0.1)
    else:
        raise OfficialReleaseError(f"official OpenDesign did not become ready: {last_error}")

    probes: dict[str, dict[str, Any]] = {}
    for path in PROBE_PATHS:
        status, headers, body = _request(port, token, path)
        if not 200 <= status < 300:
            raise OfficialReleaseError(f"official OpenDesign native surface {path} returned HTTP {status}")
        probes[path] = {
            "status": status,
            "content_type": headers.get("content-type", "").split(";", 1)[0],
            "body_bytes": len(body),
            "body_excerpt": body[:2048].decode("utf-8", errors="replace"),
        }
    return probes


def _request(port: int, token: str, path: str) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3.0)
    try:
        connection.request(
            "GET",
            path,
            headers={"Authorization": f"Bearer {token}", "Connection": "close"},
        )
        response = connection.getresponse()
        body = response.read(4 * 1024 * 1024 + 1)
        if len(body) > 4 * 1024 * 1024:
            raise OfficialReleaseError(f"official OpenDesign native surface {path} exceeded smoke limit")
        return response.status, {key.lower(): value for key, value in response.getheaders()}, body
    finally:
        connection.close()


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


if __name__ == "__main__":
    try:
        main()
    except OfficialReleaseError as error:
        raise SystemExit(str(error)) from error
