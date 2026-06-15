"""Launch the curated OpenDesign daemon bundle for Design Studio."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path


OPENDESIGN_VERSION = "0.10.1"
OPENDESIGN_COMMIT = "eb245799adf07e7727ad5f970485d809bad5780e"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
SERVICE_ROOT = Path(__file__).resolve().parent
APP_ROOT = SERVICE_ROOT.parent
DEFAULT_BUNDLE_DIR = SERVICE_ROOT / "vendor" / "open-design"
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
    data_dir = _required_dir("OD_DATA_DIR")
    media_config_dir = _required_dir("OD_MEDIA_CONFIG_DIR")
    if data_dir != media_config_dir and data_dir not in media_config_dir.parents:
        raise SystemExit("OD_MEDIA_CONFIG_DIR must stay below OD_DATA_DIR in sandbox mode.")
    _ensure_runtime_dirs(data_dir, media_config_dir)

    bundle_dir = _bundle_dir()
    plan = _resolve_launch_plan(bundle_dir)
    _write_launcher_status(data_dir, plan, bundle_dir)
    _exec(plan, _daemon_env(data_dir=data_dir, media_config_dir=media_config_dir))


def _bundle_dir() -> Path:
    raw = os.environ.get("MAVERICK_OPENDESIGN_BUNDLE_DIR")
    path = Path(raw).expanduser() if raw else DEFAULT_BUNDLE_DIR
    resolved = path.resolve()
    if os.environ.get("MAVERICK_OPENDESIGN_ALLOW_EXTERNAL_BUNDLE") == "1":
        return resolved
    app_root = APP_ROOT.resolve()
    if app_root != resolved and app_root not in resolved.parents:
        raise SystemExit("MAVERICK_OPENDESIGN_BUNDLE_DIR must stay inside the Design Studio app source.")
    return resolved


def _resolve_launch_plan(bundle_dir: Path) -> LaunchPlan:
    if not bundle_dir.exists():
        raise SystemExit("Curated OpenDesign daemon unavailable: curated bundle directory is missing.")
    package_json = bundle_dir / "package.json"
    daemon_package = bundle_dir / "apps" / "daemon" / "package.json"
    if not package_json.is_file() or not daemon_package.is_file():
        raise SystemExit("Curated OpenDesign daemon unavailable: bundle is missing OpenDesign package manifests.")
    cli = bundle_dir / "apps" / "daemon" / "dist" / "cli.js"
    if cli.is_file() and _has_node_modules(bundle_dir):
        return LaunchPlan("curated-dist", ["node", str(cli), "--no-open"], bundle_dir, "using built daemon dist")
    raise SystemExit("Curated OpenDesign daemon unavailable: curated bundle exists but is not installed and built.")


def _has_node_modules(bundle_dir: Path) -> bool:
    return (bundle_dir / "node_modules" / ".modules.yaml").is_file()


def _daemon_env(*, data_dir: Path, media_config_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["OD_DATA_DIR"] = str(data_dir)
    env["OD_MEDIA_CONFIG_DIR"] = str(media_config_dir)
    env["OD_SANDBOX_MODE"] = "1"
    env.setdefault("CI", "1")
    env.setdefault("NO_COLOR", "1")
    return env


def _required_dir(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required for the OpenDesign sidecar.")
    return Path(value).resolve()


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required for the OpenDesign sidecar.")
    return value


def _ensure_runtime_dirs(data_dir: Path, media_config_dir: Path) -> None:
    for relative in ("db", "projects", "temp"):
        (data_dir / relative).mkdir(parents=True, exist_ok=True)
    media_config_dir.mkdir(parents=True, exist_ok=True)


def _write_launcher_status(data_dir: Path, plan: LaunchPlan, bundle_dir: Path) -> None:
    status_path = data_dir / "launcher-status.json"
    payload = {
        "schema_version": "1",
        "opendesign_version": OPENDESIGN_VERSION,
        "opendesign_commit": OPENDESIGN_COMMIT,
        "bundle": _bundle_status(bundle_dir),
        "bundle_configured": True,
        "mode": plan.mode,
        "detail": plan.detail,
        "manifest": _read_manifest_summary(),
        "technical_token_present": bool(os.environ.get("OD_API_TOKEN")),
    }
    status_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _bundle_status(bundle_dir: Path) -> dict[str, str]:
    try:
        relative = bundle_dir.resolve().relative_to(APP_ROOT.resolve()).as_posix()
    except ValueError:
        return {"location": "external", "relative_path": ""}
    return {"location": "app_source", "relative_path": relative}


def _read_manifest_summary() -> dict[str, object]:
    try:
        payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    upstream = payload.get("upstream") if isinstance(payload, dict) else {}
    bundle = payload.get("bundle") if isinstance(payload, dict) else {}
    return {
        "upstream": upstream if isinstance(upstream, dict) else {},
        "bundle": bundle if isinstance(bundle, dict) else {},
    }


def _exec(plan: LaunchPlan, env: dict[str, str]) -> None:
    os.chdir(plan.cwd)
    os.execvpe(plan.command[0], plan.command, env)


if __name__ == "__main__":
    main()
