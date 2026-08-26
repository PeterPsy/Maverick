"""Real governed runtime adapter for controlled OpenDesign OCI migrations."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import sqlite3
import stat
import subprocess
import time
from typing import Any, BinaryIO, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from opendesign_artifact import is_sha256, selected_asset, validate_bundle_manifest
from opendesign_artifact_audit import (
    fully_audited_runtime,
    fully_audited_web_overlay,
)
from opendesign_artifact_store import ArtifactStoreError, OpenDesignArtifactStore
from opendesign_generation_control import load_generation_control
from opendesign_generation_model import LaunchSelection
from opendesign_materialization import MaterializedBundle, discover_verified_bundles
from opendesign_migration_files import controlled_root, require_real_directory
from opendesign_migration_runtime import MigrationError
from opendesign_oci_stage import runtime_command
from opendesign_runtime import materialized_bundle_from_store, verified_overlay_from_store
from opendesign_web_overlay import VerifiedWebOverlay, discover_verified_overlays


MAX_RESPONSE_BYTES = 4 * 1024 * 1024
START_TIMEOUT_SECONDS = 60


class OciMigrationRuntime:
    """Drive a materialized daemon against one marked controlled-copy root."""

    def __init__(
        self,
        root: Path,
        registry_root: Path,
        web_registry_root: Path,
        web_trust_contract: Path,
        manifest: Mapping[str, Any],
    ) -> None:
        self.root = controlled_root(root)
        supplied_registry = require_real_directory(
            registry_root,
            root=registry_root,
            label="OpenDesign verified bundle registry",
        )
        self.manifest = dict(manifest)
        validate_bundle_manifest(self.manifest, require_artifact_digest=True)
        selected = selected_asset(self.manifest, require_artifact_digest=True)
        if (supplied_registry / ".maverick-artifact-namespace.json").is_file():
            self.registry_root, self.web_registry_root, self.bundles, self.overlays = (
                self._protected_store_inventory(
                    supplied_registry,
                    selected=selected,
                    web_trust_contract=web_trust_contract,
                )
            )
        else:
            self.registry_root = supplied_registry
            self.bundles = discover_verified_bundles(self.registry_root)
            self.web_registry_root = require_real_directory(
                web_registry_root,
                root=web_registry_root,
                label="OpenDesign verified web overlay registry",
            )
            self.overlays = discover_verified_overlays(
                self.web_registry_root,
                trust_contract=web_trust_contract,
            )
        if selected["sha256"] not in self.bundles:
            raise MigrationError("pinned OpenDesign migration artifact is not materialized")
        self._selected_artifact_sha256 = str(selected["sha256"])
        self.verified_artifacts = {
            digest: bundle.opendesign_version for digest, bundle in self.bundles.items()
        }
        self.verified_overlays = dict(self.overlays)
        self._frozen = False
        self._process: subprocess.Popen[bytes] | None = None
        self._log_handle: BinaryIO | None = None
        self._port: int | None = None
        self._token: str | None = None
        self._active_data_dir: Path | None = None
        self._database_integrity: dict[str, str] = {}
        self.events: list[str] = []

    def _protected_store_inventory(
        self,
        root: Path,
        *,
        selected: Mapping[str, Any],
        web_trust_contract: Path,
    ) -> tuple[Path, Path, dict[str, MaterializedBundle], dict[str, VerifiedWebOverlay]]:
        try:
            store = OpenDesignArtifactStore(root)
            stored_runtime = fully_audited_runtime(
                store,
                str(selected["sha256"]),
                file_manifest_sha256=str(selected["file_manifest_sha256"]),
                opendesign_version=str(self.manifest["upstream"]["release_version"]),
                upstream_commit=str(self.manifest["upstream"]["commit"]),
            )
            bundles = {stored_runtime.artifact_sha256: materialized_bundle_from_store(stored_runtime)}
            overlays: dict[str, VerifiedWebOverlay] = {}
            for candidate in (store.root / "web").iterdir():
                if candidate.is_symlink() or not candidate.is_dir() or not is_sha256(candidate.name):
                    continue
                try:
                    stored = fully_audited_web_overlay(
                        store,
                        candidate.name,
                        runtime_artifact_sha256=stored_runtime.artifact_sha256,
                        trust_contract=web_trust_contract,
                    )
                except ArtifactStoreError:
                    continue
                overlays[candidate.name] = verified_overlay_from_store(stored)
        except ArtifactStoreError as error:
            raise MigrationError("protected OpenDesign migration store is invalid") from error
        if not overlays:
            raise MigrationError("protected OpenDesign migration store has no compatible web overlay")
        return store.root / "runtime", store.root / "web", bundles, overlays

    def freeze_mutations(self) -> None:
        if self._frozen:
            raise MigrationError("OpenDesign mutations are already frozen")
        self._frozen = True
        self.events.append("mutations_frozen")

    def unfreeze_mutations(self) -> None:
        self._frozen = False
        self.events.append("mutations_unfrozen")

    def drain_or_cancel_runs(self) -> None:
        self._require_frozen()
        if self._process is not None and self._process.poll() is None:
            status, payload = self._request_json("GET", "/api/runs")
            runs = payload.get("runs")
            if status != 200 or not isinstance(runs, list):
                raise MigrationError("OpenDesign active run inventory failed before migration")
            active_ids = [
                str(run.get("id"))
                for run in runs
                if isinstance(run, dict)
                and run.get("id")
                and run.get("status") not in {"succeeded", "failed", "canceled", "cancelled"}
            ]
            for run_id in active_ids:
                cancel_status, _ = self._request_json(
                    "POST",
                    f"/api/runs/{quote(run_id, safe='')}/cancel",
                    {},
                )
                if cancel_status != 200:
                    raise MigrationError("OpenDesign active run cancellation failed")
            if active_ids:
                self._wait_runs_terminal(set(active_ids))
        self.events.append("runs_drained")

    def stop_sidecar(self) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        if self._log_handle is not None:
            self._log_handle.close()
        self._process = None
        self._log_handle = None
        self._port = None
        self._token = None
        self._active_data_dir = None
        self.events.append("sidecar_stopped")

    def prove_sidecar_stopped(self, data_dir: Path) -> None:
        if self._process is not None and self._process.poll() is None:
            raise MigrationError("OpenDesign sidecar still owns the controlled generation")
        data_dir = self._controlled_data_dir(data_dir)
        for database in self._database_paths(data_dir):
            try:
                with sqlite3.connect(database, timeout=0.2) as connection:
                    connection.execute("BEGIN EXCLUSIVE")
                    connection.rollback()
            except sqlite3.Error as exc:
                raise MigrationError("OpenDesign database still has an active owner") from exc
        self.events.append("sidecar_stop_proved")

    def start_sidecar(self, triple: LaunchSelection, data_dir: Path, *, staging: bool) -> None:
        self._require_frozen()
        if self._process is not None:
            raise MigrationError("OpenDesign migration runtime already owns a daemon")
        bundle, overlay = self._bundle_for(triple)
        data_dir = self._controlled_data_dir(data_dir)
        if data_dir.parent.name != triple.data_generation:
            raise MigrationError("OpenDesign target triple does not own the staging data directory")
        if not staging:
            control = load_generation_control(
                self.root,
                verified_artifacts=self.verified_artifacts,
                verified_overlays=self.verified_overlays,
            )
            if control.active != triple:
                raise MigrationError("OpenDesign production start does not match active control")

        runtime_temp = self.root / "migrations" / "runtime-tmp"
        runtime_temp.mkdir(mode=0o700, exist_ok=True)
        require_real_directory(runtime_temp, root=self.root, label="migration runtime temp")
        compile_cache = runtime_temp / "node-compile" / triple.runtime_artifact_sha256
        compile_cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        require_real_directory(compile_cache, root=runtime_temp, label="migration Node compile cache")
        log_path = self.root / "migrations" / "runtime.log"
        port = _available_port()
        token = secrets.token_urlsafe(48)
        command = runtime_command(bundle.path, self.manifest)
        environment = {
            "CI": "1",
            "DO_NOT_TRACK": "1",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "NEXT_TELEMETRY_DISABLED": "1",
            "NO_COLOR": "1",
            "OD_API_TOKEN": token,
            "OD_BIND_HOST": "127.0.0.1",
            "OD_DATA_DIR": str(data_dir),
            "OD_MEDIA_CONFIG_DIR": str(data_dir / "media-config"),
            "OD_PORT": str(port),
            "OD_REQUIRE_API_TOKEN_ON_LOOPBACK": "1",
            "OD_SANDBOX_MODE": "1",
            "OD_STATIC_DIR": str(overlay.static_dir),
            "OD_STATIC_REGISTRY_ROOT": str(self.web_registry_root),
            "MAVERICK_OPENDESIGN_NODE_COMPILE_CACHE": str(compile_cache),
            "PATH": "/usr/bin:/bin",
            "TMPDIR": str(runtime_temp),
        }
        media_config_dir = data_dir / "media-config"
        media_config_dir.mkdir(mode=0o700, exist_ok=True)
        require_real_directory(media_config_dir, root=data_dir, label="migration media config")
        log_handle = _open_append_log(log_path)
        try:
            process = subprocess.Popen(
                command,
                cwd=bundle.path / "app",
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except Exception:
            log_handle.close()
            raise
        self._process = process
        self._log_handle = log_handle
        self._port = port
        self._token = token
        self._active_data_dir = data_dir
        try:
            self._wait_ready()
        except Exception:
            self.stop_sidecar()
            raise
        self.events.append("staging_started" if staging else "active_started")

    def health_check(self) -> None:
        status, payload = self._request_json("GET", "/api/ready")
        if status != 200 or payload.get("ready") is not True:
            raise MigrationError("OpenDesign staging health check failed")
        self.events.append("health_passed")

    def verify_database(self) -> None:
        data_dir = self._require_running_data_dir()
        results: dict[str, str] = {}
        for database in self._database_paths(data_dir):
            relative = database.relative_to(data_dir).as_posix()
            try:
                with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=2) as connection:
                    row = connection.execute("PRAGMA integrity_check").fetchone()
            except sqlite3.Error as exc:
                raise MigrationError("OpenDesign staging database verification failed") from exc
            results[relative] = str(row[0]) if row else "missing"
        if not results or any(value != "ok" for value in results.values()):
            raise MigrationError("OpenDesign staging database integrity check failed")
        self._database_integrity = results
        self.events.append("database_verified")

    def list_project_ids(self) -> list[str]:
        status, payload = self._request_json("GET", "/api/projects")
        projects = payload.get("projects")
        if status != 200 or not isinstance(projects, list):
            raise MigrationError("OpenDesign staging project inventory failed")
        identifiers = [str(item.get("id")) for item in projects if isinstance(item, dict) and item.get("id")]
        self.events.append("projects_listed")
        return identifiers

    def smoke_project(self, project_id: str) -> None:
        status, payload = self._request_json("GET", f"/api/projects/{quote(project_id, safe='')}")
        project = payload.get("project")
        if status != 200 or not isinstance(project, dict) or project.get("id") != project_id:
            raise MigrationError("OpenDesign staging project smoke failed")
        self.events.append("project_smoked")

    def create_legacy_project(self, project: Mapping[str, object], *, idempotency_key: str) -> str:
        self._require_frozen()
        legacy_id = str(project.get("id") or "")
        project_id = f"od_migrated_{hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()[:16]}"
        status, payload = self._request_json("GET", f"/api/projects/{project_id}")
        if status == 200:
            existing = payload.get("project")
            if isinstance(existing, dict) and existing.get("id") == project_id:
                return project_id
            raise MigrationError("OpenDesign idempotent project lookup changed")
        body: dict[str, object] = {
            "id": project_id,
            "name": str(project.get("name") or "Migrated design"),
            "metadata": {
                "kind": "prototype",
                "importedFrom": "maverick-controlled-migration",
                "legacySourceId": legacy_id,
            },
            "skipDiscoveryBrief": True,
        }
        prompt = project.get("prompt")
        if isinstance(prompt, str) and prompt.strip():
            body["pendingPrompt"] = prompt
        status, payload = self._request_json("POST", "/api/projects", body)
        created = payload.get("project")
        if status != 200 or not isinstance(created, dict) or created.get("id") != project_id:
            raise MigrationError("OpenDesign legacy project API migration failed")
        self.events.append("legacy_project_created")
        return project_id

    def upload_legacy_import(
        self,
        project_id: str,
        *,
        name: str,
        media_type: str,
        content: bytes,
        sha256: str,
    ) -> None:
        del media_type
        if hashlib.sha256(content).hexdigest() != sha256:
            raise MigrationError("legacy import digest changed before OpenDesign upload")
        path = f"/api/projects/{quote(project_id, safe='')}/files"
        status, payload = self._request_json(
            "POST",
            path,
            {
                "name": name,
                "content": base64.b64encode(content).decode("ascii"),
                "encoding": "base64",
                "overwrite": True,
            },
        )
        uploaded = payload.get("file")
        if status != 200 or not isinstance(uploaded, dict) or uploaded.get("name") != name:
            raise MigrationError("OpenDesign legacy import upload failed")
        raw_status, downloaded = self._request_bytes(
            "GET",
            f"/api/projects/{quote(project_id, safe='')}/raw/{quote(name, safe='')}",
        )
        if raw_status != 200 or downloaded != content:
            raise MigrationError("OpenDesign legacy import read-back verification failed")
        self.events.append("legacy_import_verified")

    def evidence(self) -> dict[str, object]:
        return {
            "events": list(self.events),
            "database_integrity": dict(self._database_integrity),
        }

    def _bundle_for(
        self,
        triple: LaunchSelection,
    ) -> tuple[MaterializedBundle, VerifiedWebOverlay]:
        if triple.runtime_artifact_sha256 != self._selected_artifact_sha256:
            raise MigrationError("OpenDesign migration runtime received a non-current artifact")
        bundle = self.bundles.get(triple.runtime_artifact_sha256)
        if bundle is None or bundle.opendesign_version != triple.od_version:
            raise MigrationError("OpenDesign migration selection has no verified materialized runtime")
        overlay = self.overlays.get(triple.web_overlay_sha256)
        if (
            overlay is None
            or overlay.od_version != triple.od_version
            or triple.runtime_artifact_sha256 not in overlay.compatible_runtime_artifact_sha256
        ):
            raise MigrationError("OpenDesign migration selection has no compatible verified web overlay")
        return bundle, overlay

    def _controlled_data_dir(self, data_dir: Path) -> Path:
        resolved = require_real_directory(data_dir, root=self.root, label="OpenDesign generation data")
        if resolved.parent.parent != self.root / "instances" or resolved.name != "data":
            raise MigrationError("OpenDesign generation data has an invalid controlled layout")
        return resolved

    def _require_frozen(self) -> None:
        if not self._frozen:
            raise MigrationError("OpenDesign mutations must be frozen during migration")

    def _require_running_data_dir(self) -> Path:
        if self._process is None or self._process.poll() is not None or self._active_data_dir is None:
            raise MigrationError("OpenDesign migration daemon is not running")
        return self._active_data_dir

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._process is None or self._process.poll() is not None:
                raise MigrationError("OpenDesign migration daemon exited before readiness")
            try:
                status, payload = self._request_json("GET", "/api/ready")
            except MigrationError:
                time.sleep(0.2)
                continue
            if status == 200 and payload.get("ready") is True:
                return
            time.sleep(0.2)
        raise MigrationError("OpenDesign migration daemon readiness timed out")

    def _wait_runs_terminal(self, run_ids: set[str]) -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status, payload = self._request_json("GET", "/api/runs")
            runs = payload.get("runs")
            if status != 200 or not isinstance(runs, list):
                raise MigrationError("OpenDesign active run drain verification failed")
            active = {
                str(run.get("id"))
                for run in runs
                if isinstance(run, dict)
                and str(run.get("id")) in run_ids
                and run.get("status") not in {"succeeded", "failed", "canceled", "cancelled"}
            }
            if not active:
                return
            time.sleep(0.2)
        raise MigrationError("OpenDesign active runs did not drain before migration")

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        status, content = self._request(method, path, body=body, content_type="application/json")
        try:
            decoded = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded = {}
        return status, decoded if isinstance(decoded, dict) else {}

    def _request_bytes(
        self,
        method: str,
        path: str,
    ) -> tuple[int, bytes]:
        return self._request(method, path, body=None, content_type=None)

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None,
        content_type: str | None,
    ) -> tuple[int, bytes]:
        self._require_running_data_dir()
        if self._port is None or self._token is None or not path.startswith("/"):
            raise MigrationError("OpenDesign migration request boundary is unavailable")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
        }
        if content_type is not None:
            headers["Content-Type"] = content_type
        request = Request(
            f"http://127.0.0.1:{self._port}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=10) as response:
                status = response.status
                content = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            status = error.code
            content = error.read(MAX_RESPONSE_BYTES + 1)
        except (URLError, TimeoutError, OSError) as exc:
            raise MigrationError("OpenDesign migration API request failed") from exc
        if len(content) > MAX_RESPONSE_BYTES:
            raise MigrationError("OpenDesign migration API response exceeds its limit")
        return status, content

    @staticmethod
    def _database_paths(data_dir: Path) -> list[Path]:
        return sorted(
            path
            for path in data_dir.rglob("*.sqlite")
            if path.is_file() and not path.is_symlink()
        )


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _open_append_log(path: Path) -> BinaryIO:
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise MigrationError("OpenDesign migration runtime log path is unsafe") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise MigrationError("OpenDesign migration runtime log must be a regular file")
        return os.fdopen(descriptor, "ab", closefd=True)
    except Exception:
        os.close(descriptor)
        raise
