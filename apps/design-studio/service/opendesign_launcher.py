"""Launch the curated OpenDesign daemon bundle for Design Studio."""

from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
import os
from pathlib import Path
import stat
import subprocess
import time
from typing import Any
from uuid import uuid4

from opendesign_artifact import (
    ArtifactError,
    read_bundle_manifest,
    validate_bundle_manifest,
    write_canonical_json,
)
from opendesign_artifact_store import ArtifactStoreError
from opendesign_artifact_store import OpenDesignArtifactStore
from opendesign_runtime import RuntimeBinding, resolve_protected_runtime_binding, verified_overlay_from_store
from opendesign_oci_stage import OciStageError, runtime_command
from opendesign_runtime_activation import finalize_runtime_activation_after_verified_sidecar_start
from opendesign_web_activation import finalize_web_activation_after_verified_sidecar_start
from opendesign_web_overlay import VerifiedWebOverlay

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
SERVICE_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = SERVICE_ROOT / "opendesign_bundle.json"
READY_MARKER_NAME = "maverick-ready.json"
DAEMON_READY_TIMEOUT_SECONDS = 8.0
STATUS_HEARTBEAT_SECONDS = 1.0


@dataclass(frozen=True)
class LaunchPlan:
    mode: str
    command: list[str]
    cwd: Path
    detail: str


class LauncherError(RuntimeError):
    """Typed launcher failure safe to persist and surface."""

    def __init__(self, code: str, phase: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.phase = phase


def main() -> None:
    host = os.environ.get("OD_BIND_HOST") or "127.0.0.1"
    if host not in LOOPBACK_HOSTS:
        raise SystemExit(f"OpenDesign sidecar must bind to loopback, got {host!r}.")
    _required_env("OD_API_TOKEN")
    generation_root = _required_dir("MAVERICK_OPENDESIGN_DATA_ROOT", create=True)
    startup_id = uuid4().hex
    timings: dict[str, float] = {}
    marker_path = generation_root / READY_MARKER_NAME
    marker_path.unlink(missing_ok=True)
    _write_starting_status(generation_root, startup_id=startup_id)
    started = time.monotonic()
    try:
        store_root = _store_root()
        phase_started = time.monotonic()
        manifest = _manifest()
        binding = _runtime_binding(
            store_root=store_root,
            generation_root=generation_root,
            manifest=manifest,
        )
        timings["artifact_fast_verify_ms"] = _elapsed_ms(phase_started)
        _emit_timing("artifact_fast_verify_ms", timings["artifact_fast_verify_ms"], startup_id)
        data_dir = binding.data_dir
        media_config_dir = data_dir / "media-config"
        node_compile_cache_dir = _node_compile_cache_dir(
            data_dir,
            binding.active.runtime_artifact_sha256,
        )
        phase_started = time.monotonic()
        _ensure_runtime_dirs(
            data_dir,
            media_config_dir,
            node_compile_cache_dir=node_compile_cache_dir,
        )
        timings["sandbox_prepare_ms"] = _elapsed_ms(phase_started)
        plan = _resolve_launch_plan(binding, manifest)
        _write_launcher_status(
            generation_root,
            plan,
            binding,
            store_root,
            manifest=manifest,
            startup_id=startup_id,
            timings=timings,
        )
        _run_daemon(
            plan,
            _daemon_env(
                data_dir=data_dir,
                media_config_dir=media_config_dir,
                static_dir=binding.overlay.static_dir,
                static_registry_root=binding.overlay.path,
                generation_root=generation_root,
                binding=binding,
                startup_nonce=startup_id,
                node_compile_cache_dir=node_compile_cache_dir,
            ),
            generation_root=generation_root,
            binding=binding,
            web_registry_root=store_root / "web",
            startup_id=startup_id,
            timings=timings,
        )
    except BaseException as error:
        marker_path.unlink(missing_ok=True)
        code, phase = _failure_identity(error)
        _write_failed_status(
            generation_root,
            startup_id=startup_id,
            code=code,
            phase=phase,
            duration_ms=_elapsed_ms(started),
            timings=timings,
            difference_count=getattr(error, "differences", 0),
        )
        raise


def _store_root() -> Path:
    value = _required_env("MAVERICK_OPENDESIGN_STORE_ROOT")
    path = Path(value)
    if not path.is_absolute() or path.as_posix() != "/artifacts/opendesign":
        raise LauncherError(
            "runtime_binding_invalid",
            "artifact_resolve",
            "MAVERICK_OPENDESIGN_STORE_ROOT must be the declared artifact capability mount",
        )
    try:
        return path.resolve(strict=True)
    except FileNotFoundError as error:
        raise ArtifactStoreError(
            "artifact_missing",
            "artifact_resolve",
            "The declared OpenDesign artifact capability is unavailable",
        ) from error


def _resolve_launch_plan(binding: RuntimeBinding, manifest: dict[str, Any]) -> LaunchPlan:
    bundle_dir = binding.bundle.path
    daemon_package = bundle_dir / "app" / "apps" / "daemon" / "package.json"
    if not daemon_package.is_file():
        raise SystemExit("Curated OpenDesign daemon unavailable: bundle is missing the daemon package manifest.")
    if not (bundle_dir / "app" / "apps" / "daemon" / "node_modules").is_dir():
        raise SystemExit("Curated OpenDesign daemon unavailable: imported runtime dependencies are missing.")
    try:
        command = runtime_command(bundle_dir, manifest)
    except OciStageError as error:
        raise SystemExit(f"Curated OpenDesign daemon unavailable: {error}") from error
    return LaunchPlan(
        "oci-musl-runtime",
        command,
        bundle_dir / "app",
        "using pinned imported musl loader, Node, and compiled daemon",
    )


def _daemon_env(
    *,
    data_dir: Path,
    media_config_dir: Path,
    static_dir: Path,
    static_registry_root: Path,
    generation_root: Path,
    binding: RuntimeBinding,
    startup_nonce: str,
    node_compile_cache_dir: Path | None = None,
) -> dict[str, str]:
    allowed = {
        "CI",
        "DO_NOT_TRACK",
        "LANG",
        "LC_ALL",
        "NEXT_TELEMETRY_DISABLED",
        "NO_COLOR",
        "OD_API_TOKEN",
        "OD_BIND_HOST",
        "OD_PORT",
        "OD_REQUIRE_API_TOKEN_ON_LOOPBACK",
        "OD_SANDBOX_MODE",
        "PATH",
        "TMPDIR",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env["OD_DATA_DIR"] = str(data_dir)
    env["OD_MEDIA_CONFIG_DIR"] = str(media_config_dir)
    env["OD_STATIC_DIR"] = str(static_dir)
    env["OD_STATIC_REGISTRY_ROOT"] = str(static_registry_root)
    env["OD_MAVERICK_READY_MARKER"] = str(generation_root / READY_MARKER_NAME)
    env["OD_MAVERICK_DEFER_PLUGIN_CATALOG"] = "1"
    env["OD_MAVERICK_STARTUP_NONCE"] = startup_nonce
    env["OD_RUNTIME_ARTIFACT_SHA256"] = binding.active.runtime_artifact_sha256
    env["OD_WEB_OVERLAY_SHA256"] = binding.active.web_overlay_sha256
    env["OD_DATA_GENERATION"] = binding.active.data_generation
    env["OD_ACTIVATION_ID"] = _activation_id(binding)
    env["MAVERICK_OPENDESIGN_NODE_COMPILE_CACHE"] = str(
        node_compile_cache_dir
        or _node_compile_cache_dir(data_dir, binding.active.runtime_artifact_sha256)
    )
    env["OD_SANDBOX_MODE"] = "1"
    env["OD_REQUIRE_API_TOKEN_ON_LOOPBACK"] = "1"
    env["DO_NOT_TRACK"] = "1"
    env["NEXT_TELEMETRY_DISABLED"] = "1"
    env.setdefault("CI", "1")
    env.setdefault("NO_COLOR", "1")
    return env


def _required_dir(name: str, *, create: bool = False) -> Path:
    value = _required_env(name)
    path = Path(value)
    if create:
        try:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as error:
            raise LauncherError("runtime_binding_invalid", "data_prepare", f"{name} cannot be prepared") from error
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise LauncherError("runtime_binding_invalid", "data_prepare", f"{name} is missing") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise LauncherError("runtime_binding_invalid", "data_prepare", f"{name} must be a real directory")
    return path.resolve(strict=True)


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value or not value.strip() or value.strip() != value:
        raise SystemExit(f"{name} is required for the OpenDesign sidecar.")
    return value


def _ensure_runtime_dirs(
    data_dir: Path,
    media_config_dir: Path,
    *,
    node_compile_cache_dir: Path | None = None,
) -> None:
    paths = [
        data_dir / "db",
        data_dir / "projects",
        data_dir / "temp",
        media_config_dir,
    ]
    if node_compile_cache_dir is not None:
        paths.extend(
            (
                data_dir / "cache",
                data_dir / "cache" / "node-compile",
                node_compile_cache_dir,
            )
        )
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise SystemExit(f"OpenDesign runtime path must be a real directory: {path.name}")
        try:
            path.resolve(strict=True).relative_to(data_dir.resolve(strict=True))
        except (FileNotFoundError, ValueError) as error:
            raise SystemExit(f"OpenDesign runtime path escapes the active data generation: {path.name}") from error


def _node_compile_cache_dir(data_dir: Path, runtime_artifact_sha256: str) -> Path:
    if (
        len(runtime_artifact_sha256) != 64
        or any(character not in "0123456789abcdef" for character in runtime_artifact_sha256)
    ):
        raise LauncherError(
            "runtime_binding_invalid",
            "data_prepare",
            "OpenDesign runtime digest is invalid for its compile cache",
        )
    return data_dir / "cache" / "node-compile" / runtime_artifact_sha256


def _write_launcher_status(
    generation_root: Path,
    plan: LaunchPlan,
    binding: RuntimeBinding,
    store_root: Path,
    *,
    manifest: dict[str, Any],
    startup_id: str,
    timings: dict[str, float],
) -> None:
    status_path = generation_root / "launcher-status.json"
    payload = {
        "schema_version": "3",
        "startup_id": startup_id,
        "opendesign_version": binding.active.od_version,
        "opendesign_commit": binding.bundle.upstream_commit,
        "active": binding.active.to_dict(),
        "runtime_artifact_sha256": binding.active.runtime_artifact_sha256,
        "web_overlay_sha256": binding.active.web_overlay_sha256,
        "bundle": _bundle_status(binding.bundle.path, store_root / "runtime"),
        "web_overlay": _bundle_status(binding.overlay.path, store_root / "web"),
        "bundle_configured": True,
        "mode": plan.mode,
        "detail": plan.detail,
        "manifest": _manifest_summary(manifest),
        "technical_token_present": bool(os.environ.get("OD_API_TOKEN")),
        "health": {
            "adapter_configured": True,
            "artifact_available": True,
            "artifact_verified": True,
            "artifact_protected": True,
            "repair_state": "idle",
            "sidecar_process_running": False,
            "daemon_ready": False,
            "activation_committed": False,
            "browser_ready": False,
        },
        "phase": "artifact_verified",
        "timings_ms": dict(timings),
        "last_failure": None,
        "updated_at_epoch_ms": int(time.time() * 1000),
    }
    write_canonical_json(status_path, payload)


def _bundle_status(bundle_dir: Path, registry_root: Path) -> dict[str, str]:
    try:
        relative = bundle_dir.parent.resolve().relative_to(registry_root.resolve()).as_posix()
    except ValueError:
        return {"location": "external", "relative_path": ""}
    return {"location": "verified_registry", "relative_path": relative}


def _manifest() -> dict[str, Any]:
    try:
        payload = read_bundle_manifest(MANIFEST_PATH)
        validate_bundle_manifest(payload, require_artifact_digest=True)
    except ArtifactError as error:
        raise SystemExit(f"Curated OpenDesign daemon unavailable: bundle manifest is invalid: {error}") from error
    return payload


def _runtime_binding(
    *,
    store_root: Path,
    generation_root: Path,
    manifest: dict[str, Any],
) -> RuntimeBinding:
    try:
        return resolve_protected_runtime_binding(
            store_root=store_root,
            generation_root=generation_root,
            manifest=manifest,
            require_read_only_mount=True,
        )
    except ArtifactStoreError:
        raise
    except ArtifactError as error:
        raise LauncherError("runtime_binding_invalid", "artifact_fast_verify", str(error)) from error


def _manifest_summary(payload: dict[str, Any]) -> dict[str, object]:
    return {
        "upstream": payload["upstream"],
        "distribution": payload["distribution"],
        "runtime_closure": payload["runtime_closure"],
        "artifact": payload["artifact"],
    }


def _run_daemon(
    plan: LaunchPlan,
    env: dict[str, str],
    *,
    generation_root: Path,
    binding: RuntimeBinding,
    web_registry_root: Path,
    startup_id: str,
    timings: dict[str, float],
) -> None:
    phase_started = time.monotonic()
    try:
        daemon = subprocess.Popen(plan.command, cwd=plan.cwd, env=env)
    except OSError as error:
        raise LauncherError("daemon_spawn_failed", "process_spawn", "OpenDesign daemon spawn failed") from error
    timings["process_spawn_ms"] = _elapsed_ms(phase_started)
    _emit_timing("process_spawn_ms", timings["process_spawn_ms"], startup_id)
    _update_health_status(
        generation_root,
        startup_id=startup_id,
        phase="daemon_starting",
        timings=timings,
        sidecar_process_running=True,
    )
    try:
        phase_started = time.monotonic()
        readiness = _wait_for_sidecar_readiness(daemon, env=env)
        timings["daemon_ready_ms"] = _elapsed_ms(phase_started)
        _emit_timing("daemon_ready_ms", timings["daemon_ready_ms"], startup_id)
        phase_started = time.monotonic()
        _finalize_pending_activations(
            generation_root,
            binding=binding,
            web_registry_root=web_registry_root,
            readiness=readiness,
        )
        timings["activation_commit_ms"] = _elapsed_ms(phase_started)
        _emit_timing("activation_commit_ms", timings["activation_commit_ms"], startup_id)
        _write_readiness_marker(generation_root, binding=binding, startup_nonce=startup_id)
        _wait_for_maverick_readiness(daemon, env=env)
        _update_health_status(
            generation_root,
            startup_id=startup_id,
            phase="browser_ready",
            timings=timings,
            sidecar_process_running=True,
            daemon_ready=True,
            activation_committed=True,
            browser_ready=True,
        )
        return_code = _wait_for_daemon_exit(
            daemon,
            generation_root=generation_root,
            startup_id=startup_id,
            timings=timings,
        )
    except BaseException:
        _terminate_daemon(daemon)
        raise
    finally:
        (generation_root / READY_MARKER_NAME).unlink(missing_ok=True)
        _update_health_status(
            generation_root,
            startup_id=startup_id,
            phase="daemon_stopped",
            timings=timings,
            sidecar_process_running=False,
            daemon_ready=False,
            activation_committed=False,
            browser_ready=False,
        )
    raise LauncherError(
        "daemon_spawn_failed",
        "daemon_exit",
        f"OpenDesign daemon exited with status {return_code}",
    )


def _wait_for_daemon_exit(
    daemon: subprocess.Popen[bytes],
    *,
    generation_root: Path,
    startup_id: str,
    timings: dict[str, float],
) -> int:
    while True:
        try:
            return daemon.wait(timeout=STATUS_HEARTBEAT_SECONDS)
        except subprocess.TimeoutExpired:
            _update_health_status(
                generation_root,
                startup_id=startup_id,
                phase="browser_ready",
                timings=timings,
                sidecar_process_running=True,
                daemon_ready=True,
                activation_committed=True,
                browser_ready=True,
            )


def _wait_for_sidecar_readiness(
    daemon: subprocess.Popen[bytes],
    *,
    env: dict[str, str],
) -> dict[str, object]:
    host = str(env.get("OD_BIND_HOST") or "127.0.0.1")
    try:
        port = int(str(env.get("OD_PORT") or ""))
    except ValueError as error:
        raise RuntimeError("OpenDesign sidecar port is invalid") from error
    if not 1 <= port <= 65535:
        raise RuntimeError("OpenDesign sidecar port is invalid")
    token = str(env.get("OD_API_TOKEN") or "")
    deadline = time.monotonic() + DAEMON_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if daemon.poll() is not None:
            raise RuntimeError("OpenDesign daemon exited before verified readiness")
        connection = http.client.HTTPConnection(host, port, timeout=1.5)
        try:
            connection.request(
                "GET",
                "/api/ready",
                headers={"Authorization": f"Bearer {token}", "Connection": "close"},
            )
            response = connection.getresponse()
            body = response.read(65_537)
            if 200 <= response.status < 300 and len(body) <= 65_536:
                payload = json.loads(body.decode("utf-8"))
                if isinstance(payload, dict) and payload.get("ready") is True:
                    return {"ready": True, "service_count": 1}
        except (OSError, http.client.HTTPException, UnicodeDecodeError, json.JSONDecodeError):
            pass
        finally:
            connection.close()
        time.sleep(0.1)
    raise LauncherError("daemon_ready_timeout", "daemon_ready", "OpenDesign daemon did not reach readiness")


def _wait_for_maverick_readiness(
    daemon: subprocess.Popen[bytes],
    *,
    env: dict[str, str],
) -> None:
    payload = _wait_for_json_readiness(
        daemon,
        env=env,
        path="/api/maverick-ready",
        timeout_seconds=2.0,
    )
    if payload.get("ready") is not True:
        raise LauncherError("activation_incomplete", "activation_commit", "Transactional readiness was not committed")


def _wait_for_json_readiness(
    daemon: subprocess.Popen[bytes],
    *,
    env: dict[str, str],
    path: str,
    timeout_seconds: float,
) -> dict[str, object]:
    host = str(env.get("OD_BIND_HOST") or "127.0.0.1")
    try:
        port = int(str(env.get("OD_PORT") or ""))
    except ValueError as error:
        raise LauncherError("runtime_binding_invalid", "daemon_ready", "OpenDesign sidecar port is invalid") from error
    token = str(env.get("OD_API_TOKEN") or "")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if daemon.poll() is not None:
            raise LauncherError("daemon_spawn_failed", "daemon_ready", "OpenDesign daemon exited before readiness")
        connection = http.client.HTTPConnection(host, port, timeout=0.5)
        try:
            connection.request(
                "GET",
                path,
                headers={"Authorization": f"Bearer {token}", "Connection": "close"},
            )
            response = connection.getresponse()
            body = response.read(65_537)
            if 200 <= response.status < 300 and len(body) <= 65_536:
                payload = json.loads(body.decode("utf-8"))
                if isinstance(payload, dict):
                    return payload
        except (OSError, http.client.HTTPException, UnicodeDecodeError, json.JSONDecodeError):
            pass
        finally:
            connection.close()
        time.sleep(0.05)
    raise LauncherError("activation_incomplete", "activation_commit", "Transactional readiness timed out")


def _finalize_pending_activations(
    generation_root: Path,
    *,
    binding: RuntimeBinding,
    web_registry_root: Path,
    readiness: dict[str, object],
) -> None:
    if binding.control.web_activation_id is None and binding.control.runtime_activation_id is None:
        return
    store = OpenDesignArtifactStore(web_registry_root.parent, require_read_only_mount=True)
    selections = [binding.active]
    if binding.control.previous_web is not None:
        selections.append(binding.control.previous_web)
    if binding.control.previous_runtime is not None:
        selections.append(binding.control.previous_runtime)
    overlays: dict[str, VerifiedWebOverlay] = {}
    for selection in selections:
        if selection.web_overlay_sha256 in overlays:
            continue
        stored = store.fast_web_overlay(
            selection.web_overlay_sha256,
            runtime_artifact_sha256=selection.runtime_artifact_sha256,
        )
        overlays[selection.web_overlay_sha256] = verified_overlay_from_store(stored)
    artifacts = {binding.active.runtime_artifact_sha256: binding.bundle.opendesign_version}
    if binding.control.previous_runtime is not None:
        previous = binding.control.previous_runtime
        stored_runtime = store.fast_runtime(
            previous.runtime_artifact_sha256,
            file_manifest_sha256=None,
            opendesign_version=previous.od_version,
            upstream_commit=None,
        )
        artifacts[previous.runtime_artifact_sha256] = str(stored_runtime.receipt["opendesign_version"])
    if binding.control.runtime_activation_id is not None:
        finalize_runtime_activation_after_verified_sidecar_start(
            generation_root,
            readiness=readiness,
            verified_artifacts=artifacts,
            verified_overlays=overlays,
        )
    if binding.control.web_activation_id is not None:
        finalize_web_activation_after_verified_sidecar_start(
            generation_root,
            readiness=readiness,
            verified_artifacts=artifacts,
            verified_overlays=overlays,
        )


def _write_readiness_marker(
    generation_root: Path,
    *,
    binding: RuntimeBinding,
    startup_nonce: str,
) -> None:
    write_canonical_json(
        generation_root / READY_MARKER_NAME,
        {
            "schema_version": "1",
            "startup_nonce": startup_nonce,
            "runtime_artifact_sha256": binding.active.runtime_artifact_sha256,
            "web_overlay_sha256": binding.active.web_overlay_sha256,
            "data_generation": binding.active.data_generation,
            "activation_id": _activation_id(binding),
        },
    )


def _activation_id(binding: RuntimeBinding) -> str:
    return (
        getattr(binding.control, "runtime_activation_id", None)
        or getattr(binding.control, "web_activation_id", None)
        or ""
    )


def _write_starting_status(generation_root: Path, *, startup_id: str) -> None:
    write_canonical_json(
        generation_root / "launcher-status.json",
        {
            "schema_version": "3",
            "startup_id": startup_id,
            "phase": "bootstrap",
            "health": {
                "adapter_configured": True,
                "artifact_available": False,
                "artifact_verified": False,
                "artifact_protected": False,
                "repair_state": "idle",
                "sidecar_process_running": False,
                "daemon_ready": False,
                "activation_committed": False,
                "browser_ready": False,
            },
            "timings_ms": {},
            "last_failure": None,
            "updated_at_epoch_ms": int(time.time() * 1000),
        },
    )


def _update_health_status(
    generation_root: Path,
    *,
    startup_id: str,
    phase: str,
    timings: dict[str, float],
    **health_updates: object,
) -> None:
    path = generation_root / "launcher-status.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if payload.get("startup_id") != startup_id:
        return
    health = payload.get("health") if isinstance(payload.get("health"), dict) else {}
    health.update(health_updates)
    payload["health"] = health
    payload["phase"] = phase
    payload["timings_ms"] = dict(timings)
    payload["updated_at_epoch_ms"] = int(time.time() * 1000)
    write_canonical_json(path, payload)


def _write_failed_status(
    generation_root: Path,
    *,
    startup_id: str,
    code: str,
    phase: str,
    duration_ms: float,
    timings: dict[str, float],
    difference_count: int = 0,
) -> None:
    path = generation_root / "launcher-status.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {"schema_version": "3", "startup_id": startup_id}
    if payload.get("startup_id") != startup_id:
        return
    health = payload.get("health") if isinstance(payload.get("health"), dict) else {}
    health.update(
        {
            "sidecar_process_running": False,
            "daemon_ready": False,
            "activation_committed": False,
            "browser_ready": False,
        }
    )
    payload.update(
        {
            "phase": phase,
            "health": health,
            "timings_ms": dict(timings),
            "last_failure": {
                "code": code,
                "phase": phase,
                "startup_id": startup_id,
                "duration_ms": round(duration_ms, 3),
                "difference_count": max(0, int(difference_count)),
                "auto_repairable": code in {"artifact_missing", "artifact_integrity_mismatch"},
                "observed_at_epoch_ms": int(time.time() * 1000),
            },
            "updated_at_epoch_ms": int(time.time() * 1000),
        }
    )
    write_canonical_json(path, payload)


def _failure_identity(error: BaseException) -> tuple[str, str]:
    if isinstance(error, ArtifactStoreError):
        return error.code, error.phase
    if isinstance(error, LauncherError):
        return error.code, error.phase
    if isinstance(error, ArtifactError):
        return "runtime_binding_invalid", "artifact_fast_verify"
    if isinstance(error, OSError):
        return "daemon_spawn_failed", "process_spawn"
    return "daemon_spawn_failed", "launcher_unhandled"


def _elapsed_ms(started_at: float) -> float:
    return round((time.monotonic() - started_at) * 1000, 3)


def _emit_timing(metric: str, value: float, startup_id: str) -> None:
    print(
        json.dumps(
            {"event": metric, "value_ms": value, "startup_id": startup_id},
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )


def _terminate_daemon(daemon: subprocess.Popen[bytes]) -> None:
    if daemon.poll() is not None:
        return
    daemon.terminate()
    try:
        daemon.wait(timeout=5)
    except subprocess.TimeoutExpired:
        daemon.kill()
        daemon.wait(timeout=5)


if __name__ == "__main__":
    main()
