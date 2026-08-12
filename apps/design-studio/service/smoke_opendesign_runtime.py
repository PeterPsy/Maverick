#!/usr/bin/env python3
"""Exercise the real imported OpenDesign runtime and compiled bearer boundary."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from opendesign_artifact import read_bundle_manifest, selected_asset, validate_bundle_manifest
from opendesign_bootstrap import bootstrap_empty_generation
from opendesign_materialization import discover_verified_bundles
from opendesign_web_release import canonical_web_overlay


SERVICE_ROOT = Path(__file__).resolve().parent
REGISTRY_ROOT = SERVICE_ROOT / "vendor/open-design"
WEB_REGISTRY_ROOT = SERVICE_ROOT / "vendor/open-design-web"
WEB_TRUST_CONTRACT = SERVICE_ROOT / "opendesign_web_trust.json"
TOKEN = "a" * 64


def main() -> None:
    manifest = read_bundle_manifest(SERVICE_ROOT / "opendesign_bundle.json")
    validate_bundle_manifest(manifest, require_artifact_digest=True)
    asset = selected_asset(manifest, require_artifact_digest=True)
    bundle = discover_verified_bundles(REGISTRY_ROOT).get(asset["sha256"])
    if bundle is None:
        raise SystemExit("Pinned OpenDesign artifact is not materialized")
    overlay, overlays = canonical_web_overlay(
        WEB_REGISTRY_ROOT,
        trust_contract=WEB_TRUST_CONTRACT,
        runtime_artifact_sha256=bundle.artifact_sha256,
        od_version=bundle.opendesign_version,
        upstream_commit=bundle.upstream_commit,
    )
    with TemporaryDirectory(prefix="maverick-od-runtime-smoke-") as temporary:
        temporary_root = Path(temporary)
        generation_root = temporary_root / "opendesign"
        generation_root.mkdir()
        for name in ("instances", "backups", "migrations", "web-activations"):
            (generation_root / name).mkdir()
        control, data_dir = bootstrap_empty_generation(
            generation_root,
            artifact_sha256=bundle.artifact_sha256,
            web_overlay_sha256=overlay.web_overlay_sha256,
            opendesign_version=bundle.opendesign_version,
            verified_artifacts={bundle.artifact_sha256: bundle.opendesign_version},
            verified_overlays=overlays,
        )
        port = _available_port()
        log_path = temporary_root / "daemon.log"
        environment = {
            "CI": "1",
            "DO_NOT_TRACK": "1",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "NEXT_TELEMETRY_DISABLED": "1",
            "NO_COLOR": "1",
            "OD_API_TOKEN": TOKEN,
            "OD_BIND_HOST": "127.0.0.1",
            "OD_PORT": str(port),
            "OD_REQUIRE_API_TOKEN_ON_LOOPBACK": "1",
            "OD_SANDBOX_MODE": "1",
            "PATH": "/usr/bin:/bin",
            "TMPDIR": str(temporary_root),
            "MAVERICK_OPENDESIGN_BUNDLE_ROOT": str(REGISTRY_ROOT),
            "MAVERICK_OPENDESIGN_DATA_ROOT": str(generation_root),
        }
        with log_path.open("w", encoding="utf-8") as log_handle:
            process = subprocess.Popen(
                [sys.executable, str(SERVICE_ROOT / "opendesign_launcher.py")],
                cwd=SERVICE_ROOT,
                env=environment,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            try:
                ready = _wait_ready(port, process)
                unauthenticated = _request(port, "/api/plugins")
                wrong = _request(port, "/api/plugins", token="wrong")
                authenticated = _request(port, "/api/plugins", token=TOKEN)
                version = _request(port, "/api/version")
                sqlite_result = _sqlite_integrity(data_dir)
            finally:
                _terminate_process_group(process)
        if ready[0] != 200 or ready[1].get("ready") is not True:
            raise SystemExit("OpenDesign imported runtime did not become ready")
        if unauthenticated[0] != 401 or wrong[0] != 401 or authenticated[0] != 200:
            raise SystemExit("OpenDesign compiled loopback bearer boundary failed")
        reported = version[1].get("version")
        runtime_version = reported.get("version") if isinstance(reported, dict) else reported
        if version[0] != 200 or runtime_version != manifest["upstream"]["root_package_version"]:
            raise SystemExit("OpenDesign imported runtime version endpoint changed")
        plugins = authenticated[1].get("plugins")
        plugin_count = len(plugins) if isinstance(plugins, list) else None
        if plugin_count is None or plugin_count < 400:
            raise SystemExit("OpenDesign imported runtime plugin registry is incomplete")
        print(
            json.dumps(
                {
                    "ok": True,
                    "artifact_sha256": bundle.artifact_sha256,
                    "active": control.active.to_dict(),
                    "node_runtime": "v24.18.0",
                    "ready": ready[1],
                    "runtime_reported_version": runtime_version,
                    "plugin_count": plugin_count,
                    "loopback_bearer": {
                        "missing": unauthenticated[0],
                        "wrong": wrong[0],
                        "correct": authenticated[0],
                    },
                    "sqlite_integrity": sqlite_result,
                },
                indent=2,
                sort_keys=True,
            )
        )


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _wait_ready(port: int, process: subprocess.Popen[str]) -> tuple[int, dict[str, Any]]:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"OpenDesign imported runtime exited before readiness ({process.returncode})")
        status, payload = _request(port, "/api/ready")
        if status == 200:
            return status, payload
        time.sleep(0.2)
    raise SystemExit("OpenDesign imported runtime readiness timed out")


def _request(port: int, path: str, *, token: str | None = None) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"http://127.0.0.1:{port}{path}", headers=headers)
    try:
        with urlopen(request, timeout=5) as response:
            status = response.status
            body = response.read(4 * 1024 * 1024)
    except HTTPError as error:
        status = error.code
        body = error.read(1024 * 1024)
    except (URLError, TimeoutError, OSError):
        return 0, {}
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    return status, payload if isinstance(payload, dict) else {}


def _sqlite_integrity(data_dir: Path) -> dict[str, str]:
    databases = sorted(path for path in data_dir.rglob("*.sqlite") if path.is_file() and not path.is_symlink())
    if not databases:
        raise SystemExit("OpenDesign imported runtime did not create a SQLite database")
    results: dict[str, str] = {}
    for database in databases:
        relative = database.relative_to(data_dir).as_posix()
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        results[relative] = str(row[0]) if row else "missing"
    if any(value != "ok" for value in results.values()):
        raise SystemExit("OpenDesign imported runtime SQLite integrity check failed")
    return results


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


if __name__ == "__main__":
    main()
