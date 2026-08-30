#!/usr/bin/env python3
"""Run a disposable native OpenDesign proof with Maverick bridges disabled."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import tempfile
import time
from typing import Any

from official_opendesign_release import (
    OfficialInstallation,
    OfficialReleaseError,
    verify_official_installation,
)
from official_inventory_process import OfficialApiClient, running_official_api


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
    log_path = data_dir / "official-smoke.log"
    data_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with running_official_api(
        installation,
        data_dir=data_dir,
        log_path=log_path,
        timeout_seconds=timeout_seconds,
    ) as client:
        probes = _probe_native_surfaces(client)
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


def _probe_native_surfaces(client: OfficialApiClient) -> dict[str, dict[str, Any]]:
    probes: dict[str, dict[str, Any]] = {}
    for path in PROBE_PATHS:
        status, headers, body = client.request_details("GET", path)
        if not 200 <= status < 300:
            raise OfficialReleaseError(f"official OpenDesign native surface {path} returned HTTP {status}")
        probes[path] = {
            "status": status,
            "content_type": headers.get("content-type", "").split(";", 1)[0],
            "body_bytes": len(body),
            "body_excerpt": body[:2048].decode("utf-8", errors="replace"),
        }
    return probes


if __name__ == "__main__":
    try:
        main()
    except OfficialReleaseError as error:
        raise SystemExit(str(error)) from error
