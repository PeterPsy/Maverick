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

from opendesign_artifact import (
    ArtifactError,
    read_bundle_manifest,
    validate_bundle_manifest,
    write_canonical_json,
)
from opendesign_runtime import RuntimeBinding, resolve_runtime_binding
from opendesign_oci_stage import OciStageError, runtime_command
from opendesign_web_activation import finalize_web_activation_after_verified_sidecar_start
from opendesign_web_overlay import discover_verified_overlays

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
SERVICE_ROOT = Path(__file__).resolve().parent
APP_ROOT = SERVICE_ROOT.parent
DEFAULT_BUNDLE_ROOT = SERVICE_ROOT / "vendor" / "open-design"
DEFAULT_WEB_ROOT = SERVICE_ROOT / "vendor" / "open-design-web"
WEB_TRUST_CONTRACT = SERVICE_ROOT / "opendesign_web_trust.json"
MANIFEST_PATH = SERVICE_ROOT / "opendesign_bundle.json"


@dataclass(frozen=True)
class LaunchPlan:
    mode: str
    command: list[str]
    cwd: Path
    detail: str


def main() -> None:
    host = os.environ.get("OD_BIND_HOST") or "127.0.0.1"
    if host not in LOOPBACK_HOSTS:
        raise SystemExit(f"OpenDesign sidecar must bind to loopback, got {host!r}.")
    _required_env("OD_API_TOKEN")
    generation_root = _required_dir("MAVERICK_OPENDESIGN_DATA_ROOT")
    registry_root = _registry_root()
    web_registry_root = _web_registry_root()
    manifest = _manifest()
    binding = _runtime_binding(
        registry_root=registry_root,
        web_registry_root=web_registry_root,
        generation_root=generation_root,
        manifest=manifest,
    )
    data_dir = binding.data_dir
    media_config_dir = data_dir / "media-config"
    _ensure_runtime_dirs(data_dir, media_config_dir)

    plan = _resolve_launch_plan(binding, manifest)
    _write_launcher_status(
        generation_root,
        plan,
        binding,
        registry_root,
        web_registry_root,
        manifest=manifest,
    )
    _run_daemon(
        plan,
        _daemon_env(
            data_dir=data_dir,
            media_config_dir=media_config_dir,
            static_dir=binding.overlay.static_dir,
            static_registry_root=web_registry_root,
        ),
        generation_root=generation_root,
        binding=binding,
        web_registry_root=web_registry_root,
    )


def _registry_root() -> Path:
    raw = os.environ.get("MAVERICK_OPENDESIGN_BUNDLE_ROOT")
    path = Path(raw).expanduser() if raw else DEFAULT_BUNDLE_ROOT
    return _verified_registry_path(
        path,
        variable="MAVERICK_OPENDESIGN_BUNDLE_ROOT",
    )


def _web_registry_root() -> Path:
    raw = os.environ.get("MAVERICK_OPENDESIGN_WEB_ROOT")
    path = Path(raw).expanduser() if raw else DEFAULT_WEB_ROOT
    return _verified_registry_path(
        path,
        variable="MAVERICK_OPENDESIGN_WEB_ROOT",
    )


def _verified_registry_path(path: Path, *, variable: str) -> Path:
    resolved = path.resolve()
    if os.environ.get("MAVERICK_OPENDESIGN_ALLOW_EXTERNAL_BUNDLE") == "1":
        return resolved
    app_root = APP_ROOT.resolve()
    if app_root != resolved and app_root not in resolved.parents:
        raise SystemExit(f"{variable} must stay inside the Design Studio app source.")
    return resolved


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
    env["OD_SANDBOX_MODE"] = "1"
    env["OD_REQUIRE_API_TOKEN_ON_LOOPBACK"] = "1"
    env["DO_NOT_TRACK"] = "1"
    env["NEXT_TELEMETRY_DISABLED"] = "1"
    env.setdefault("CI", "1")
    env.setdefault("NO_COLOR", "1")
    return env


def _required_dir(name: str) -> Path:
    value = _required_env(name)
    return Path(value).resolve()


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value or not value.strip() or value.strip() != value:
        raise SystemExit(f"{name} is required for the OpenDesign sidecar.")
    return value


def _ensure_runtime_dirs(data_dir: Path, media_config_dir: Path) -> None:
    for path in (
        data_dir / "db",
        data_dir / "projects",
        data_dir / "temp",
        media_config_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise SystemExit(f"OpenDesign runtime path must be a real directory: {path.name}")
        try:
            path.resolve(strict=True).relative_to(data_dir.resolve(strict=True))
        except (FileNotFoundError, ValueError) as error:
            raise SystemExit(f"OpenDesign runtime path escapes the active data generation: {path.name}") from error


def _write_launcher_status(
    generation_root: Path,
    plan: LaunchPlan,
    binding: RuntimeBinding,
    registry_root: Path,
    web_registry_root: Path,
    *,
    manifest: dict[str, Any],
) -> None:
    status_path = generation_root / "launcher-status.json"
    payload = {
        "schema_version": "2",
        "opendesign_version": binding.active.od_version,
        "opendesign_commit": binding.bundle.upstream_commit,
        "active": binding.active.to_dict(),
        "runtime_artifact_sha256": binding.active.runtime_artifact_sha256,
        "web_overlay_sha256": binding.active.web_overlay_sha256,
        "bundle": _bundle_status(binding.bundle.path, registry_root),
        "web_overlay": _bundle_status(binding.overlay.path, web_registry_root),
        "bundle_configured": True,
        "mode": plan.mode,
        "detail": plan.detail,
        "manifest": _manifest_summary(manifest),
        "technical_token_present": bool(os.environ.get("OD_API_TOKEN")),
    }
    write_canonical_json(status_path, payload)


def _bundle_status(bundle_dir: Path, registry_root: Path) -> dict[str, str]:
    try:
        relative = bundle_dir.resolve().relative_to(registry_root.resolve()).as_posix()
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
    registry_root: Path,
    web_registry_root: Path,
    generation_root: Path,
    manifest: dict[str, Any],
) -> RuntimeBinding:
    try:
        return resolve_runtime_binding(
            registry_root=registry_root,
            web_registry_root=web_registry_root,
            web_trust_contract=WEB_TRUST_CONTRACT,
            generation_root=generation_root,
            manifest=manifest,
        )
    except ArtifactError as error:
        raise SystemExit(f"Curated OpenDesign daemon unavailable: {error}") from error


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
) -> None:
    daemon = subprocess.Popen(plan.command, cwd=plan.cwd, env=env)
    try:
        readiness = _wait_for_sidecar_readiness(daemon, env=env)
        _finalize_pending_web_activation(
            generation_root,
            binding=binding,
            web_registry_root=web_registry_root,
            readiness=readiness,
        )
        return_code = daemon.wait()
    except BaseException:
        _terminate_daemon(daemon)
        raise
    raise SystemExit(return_code)


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
    deadline = time.monotonic() + 120.0
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
    raise RuntimeError("OpenDesign daemon did not reach verified readiness")


def _finalize_pending_web_activation(
    generation_root: Path,
    *,
    binding: RuntimeBinding,
    web_registry_root: Path,
    readiness: dict[str, object],
) -> None:
    if binding.control.web_activation_id is None:
        return
    required_overlays = {binding.active.web_overlay_sha256}
    if binding.control.previous_web is not None:
        required_overlays.add(binding.control.previous_web.web_overlay_sha256)
    overlays = discover_verified_overlays(
        web_registry_root,
        trust_contract=WEB_TRUST_CONTRACT,
        required_digests=required_overlays,
    )
    finalize_web_activation_after_verified_sidecar_start(
        generation_root,
        readiness=readiness,
        verified_artifacts={
            binding.active.runtime_artifact_sha256: binding.bundle.opendesign_version,
        },
        verified_overlays=overlays,
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
