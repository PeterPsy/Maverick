#!/usr/bin/env python3
"""Exercise the real imported OpenDesign runtime and compiled bearer boundary."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
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

SERVICE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = SERVICE_ROOT.parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from core.apps.artifact_mounts import platform_artifact_store_root
from opendesign_artifact import (
    read_bundle_manifest,
    selected_asset,
    sha256_file,
    validate_bundle_manifest,
)
from opendesign_artifact_store import OpenDesignArtifactStore
from opendesign_bootstrap import bootstrap_empty_generation
from opendesign_oci_stage import runtime_command, runtime_node_command
from opendesign_artifact import write_canonical_json


TOKEN = "a" * 64


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-output", type=Path)
    arguments = parser.parse_args()
    manifest = read_bundle_manifest(SERVICE_ROOT / "opendesign_bundle.json")
    validate_bundle_manifest(manifest, require_artifact_digest=True)
    asset = selected_asset(manifest, require_artifact_digest=True)
    store = OpenDesignArtifactStore(
        platform_artifact_store_root(REPOSITORY_ROOT) / "design-studio" / "opendesign"
    )
    bundle = store.fast_runtime(
        str(asset["sha256"]),
        file_manifest_sha256=str(asset["file_manifest_sha256"]),
        opendesign_version=str(manifest["upstream"]["release_version"]),
        upstream_commit=str(manifest["upstream"]["commit"]),
    )
    selection = json.loads((SERVICE_ROOT / "opendesign_release_selection.json").read_text(encoding="utf-8"))
    overlay = store.fast_web_overlay(
        str(selection["active_web_overlay_sha256"]),
        runtime_artifact_sha256=bundle.artifact_sha256,
    )
    with TemporaryDirectory(prefix="maverick-od-runtime-smoke-") as temporary:
        temporary_root = Path(temporary)
        generation_root = temporary_root / "opendesign"
        generation_root.mkdir()
        for name in ("instances", "backups", "migrations", "web-activations", "runtime-activations"):
            (generation_root / name).mkdir()
        control, data_dir = bootstrap_empty_generation(
            generation_root,
            artifact_sha256=bundle.artifact_sha256,
            web_overlay_sha256=overlay.artifact_sha256,
            opendesign_version=str(bundle.receipt["opendesign_version"]),
            verified_artifacts={bundle.artifact_sha256: str(bundle.receipt["opendesign_version"])},
            verified_overlays={
                overlay.artifact_sha256: {
                    "od_version": str(overlay.receipt["opendesign_version"]),
                    "compatible_runtime_artifact_sha256": overlay.receipt[
                        "compatible_runtime_artifact_sha256"
                    ],
                }
            },
        )
        port = _available_port()
        log_path = temporary_root / "daemon.log"
        compile_cache = temporary_root / "node-compile-cache"
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
            "OD_DATA_DIR": str(data_dir),
            "OD_MEDIA_CONFIG_DIR": str(data_dir / "media-config"),
            "OD_REQUIRE_API_TOKEN_ON_LOOPBACK": "1",
            "OD_SANDBOX_MODE": "1",
            "OD_STATIC_DIR": str(overlay.content_path / "static"),
            "OD_STATIC_REGISTRY_ROOT": str(overlay.content_path),
            "OD_MAVERICK_READY_MARKER": str(generation_root / "maverick-ready.json"),
            "OD_MAVERICK_STARTUP_NONCE": "runtime-smoke",
            "OD_RUNTIME_ARTIFACT_SHA256": bundle.artifact_sha256,
            "OD_WEB_OVERLAY_SHA256": overlay.artifact_sha256,
            "OD_DATA_GENERATION": control.active.data_generation,
            "OD_ACTIVATION_ID": "",
            "MAVERICK_OPENDESIGN_NODE_COMPILE_CACHE": str(compile_cache),
            "PATH": "/usr/bin:/bin",
            "TMPDIR": str(temporary_root),
        }
        (data_dir / "media-config").mkdir(mode=0o700, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as log_handle:
            process = subprocess.Popen(
                runtime_command(bundle.content_path, manifest),
                cwd=bundle.content_path / "app",
                env=environment,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            try:
                ready = _wait_ready(port, process)
                write_canonical_json(
                    generation_root / "maverick-ready.json",
                    {
                        "schema_version": "1",
                        "startup_nonce": "runtime-smoke",
                        "runtime_artifact_sha256": bundle.artifact_sha256,
                        "web_overlay_sha256": overlay.artifact_sha256,
                        "data_generation": control.active.data_generation,
                        "activation_id": "",
                    },
                )
                maverick_ready = _request(port, "/api/maverick-ready", token=TOKEN)
                unauthenticated = _request(port, "/api/plugins")
                wrong = _request(port, "/api/plugins", token="wrong")
                authenticated = _request(port, "/api/plugins", token=TOKEN)
                version = _request(port, "/api/version")
                static_web = _request(port, "/index.html")
                sqlite_result = _sqlite_integrity(data_dir)
            finally:
                _terminate_process_group(process)
        compile_cache_files = sum(1 for path in compile_cache.rglob("*") if path.is_file())
        if compile_cache_files == 0:
            raise SystemExit("OpenDesign governed Node compile cache was not materialized")
        if ready[0] != 200 or ready[1].get("ready") is not True:
            raise SystemExit("OpenDesign imported runtime did not become ready")
        if maverick_ready[0] != 200 or maverick_ready[1].get("ready") is not True:
            raise SystemExit("OpenDesign transactional readiness marker was not accepted")
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
        node_runtime = subprocess.run(
            [*runtime_node_command(bundle.content_path, manifest), "--version"],
            cwd=bundle.content_path,
            env={"PATH": "/usr/bin:/bin"},
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        result = {
            "ok": True,
            "artifact_sha256": bundle.artifact_sha256,
            "active": control.active.to_dict(),
            "node_runtime": node_runtime,
            "node_compile_cache": {
                "materialized": True,
                "file_count": compile_cache_files,
                "runtime_scoped": True,
            },
            "daemon_ready": ready[1],
            "maverick_ready": maverick_ready[1],
            "runtime_reported_version": runtime_version,
            "plugin_count": plugin_count,
            "loopback_bearer": {
                "missing": unauthenticated[0],
                "wrong": wrong[0],
                "correct": authenticated[0],
            },
            "sqlite_integrity": sqlite_result,
        }
        if arguments.evidence_output is not None:
            write_canonical_json(
                arguments.evidence_output,
                _acceptance_evidence(
                    manifest=manifest,
                    asset=asset,
                    bundle=bundle,
                    overlay=overlay,
                    runtime=result,
                    static_web_status=static_web[0],
                ),
            )
        print(json.dumps(result, indent=2, sort_keys=True))


def _acceptance_evidence(
    *,
    manifest: dict[str, Any],
    asset: dict[str, Any],
    bundle: Any,
    overlay: Any,
    runtime: dict[str, Any],
    static_web_status: int,
) -> dict[str, Any]:
    provenance = read_bundle_manifest(SERVICE_ROOT / "artifacts" / asset["provenance"])
    rootfs_digest = provenance["predicate"]["buildDefinition"]["internalParameters"][
        "rootfsInventorySha256"
    ]
    web_manifest_path = overlay.content_path / "manifest.json"
    web_manifest = read_bundle_manifest(web_manifest_path)
    trust = read_bundle_manifest(SERVICE_ROOT / "opendesign_web_trust.json")
    return {
        "schema_version": "1",
        "executed_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "artifact": {
            field: asset[field]
            for field in (
                "sha256",
                "size_bytes",
                "file_manifest_sha256",
                "sbom_sha256",
                "license_inventory_sha256",
                "notice_sha256",
                "provenance_sha256",
                "signature_sha256",
                "public_key_sha256",
            )
        },
        "boundary_patch": {
            field: manifest["boundary_patch"][field]
            for field in ("path", "pre_sha256", "post_sha256")
        },
        "startup_patch": {
            field: manifest["startup_patch"][field]
            for field in ("path", "pre_sha256", "post_sha256", "max_concurrency")
        },
        "import": {
            "independent_derivations": 2,
            "reproducible": True,
            "rootfs_inventory_sha256": rootfs_digest,
        },
        "oci": {
            "reference": (
                f"{manifest['distribution']['registry']}/"
                f"{manifest['distribution']['repository']}:"
                f"{manifest['distribution']['reference']}"
            ),
            "index_digest": manifest["distribution"]["index"]["digest"],
            "manifest_digest": manifest["distribution"]["manifest"]["digest"],
            "config_digest": manifest["distribution"]["config"]["digest"],
            "platform": "linux/amd64",
            "upstream_revision": manifest["upstream"]["commit"],
            "slsa_statement_digest": manifest["distribution"]["attestation"]["statement"][
                "digest"
            ],
        },
        "runtime_smoke": {
            "ready": runtime["daemon_ready"].get("ready") is True,
            "maverick_ready": runtime["maverick_ready"].get("ready") is True,
            "node": runtime["node_runtime"],
            "node_compile_cache": runtime["node_compile_cache"],
            "reported_root_package_version": runtime["runtime_reported_version"],
            "plugin_count": runtime["plugin_count"],
            "bearer": runtime["loopback_bearer"],
            "sqlite_integrity": "ok"
            if runtime["sqlite_integrity"] and set(runtime["sqlite_integrity"].values()) == {"ok"}
            else "failed",
            "static_web": static_web_status,
            "embedded_static_web": False,
            "web_overlay_sha256": overlay.artifact_sha256,
            "launcher_mode": "oci-musl-runtime",
            "materialized": True,
        },
        "web_overlay": {
            "web_overlay_sha256": overlay.artifact_sha256,
            "file_manifest_sha256": web_manifest["file_manifest"]["sha256"],
            "manifest_sha256": sha256_file(web_manifest_path),
            "signature_sha256": sha256_file(overlay.content_path / "manifest.sig"),
            "toolchain_sha256": web_manifest["inputs"]["toolchain_sha256"],
            "trust_root_public_key_sha256": trust["public_key_sha256"],
        },
        "workspace_data_migrated": False,
    }


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _wait_ready(port: int, process: subprocess.Popen[str]) -> tuple[int, dict[str, Any]]:
    deadline = time.monotonic() + 8
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
