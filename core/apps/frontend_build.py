"""Official frontend build operation for mounted apps."""

from __future__ import annotations

from pathlib import Path
import json
import subprocess
from typing import Any

from core.apps.errors import AppHostingError, AppLifecycleError
from core.apps.models import WorkspaceAppBindingRecord
from core.apps.store import AppStore
from core.apps.surfaces import resolve_workspace_app_surface
from core.shared.node_runtime import NODE_RUNTIME_REQUIREMENT, require_supported_node_runtime


def build_workspace_app_frontend(
    store: AppStore,
    *,
    workspace_id: str,
    app_id: str,
    start_path: Path | None = None,
    app_event_bus=None,
) -> dict[str, Any]:
    """Run the declared frontend build for one installed workspace app and publish a refresh event."""
    binding = store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    source_root, parsed = resolve_workspace_app_surface(store, binding=binding, start_path=start_path)
    frontend_mount = parsed.contract.entrypoints.frontend
    if frontend_mount is None:
        raise AppLifecycleError(f"App `{app_id}` does not declare a frontend entrypoint.")

    build_root = _frontend_build_root(source_root=source_root, frontend_mount=frontend_mount)
    _run_npm_build(build_root, app_id=app_id)
    frontend_root = (source_root / frontend_mount).resolve()
    if not frontend_root.exists() or not frontend_root.is_dir():
        raise AppLifecycleError(f"Frontend build for app `{app_id}` did not produce `{frontend_mount}`.")

    event = {
        "type": "maverick.app.frontend-changed",
        "workspace_id": workspace_id,
        "owner_app_id": app_id,
        "resource": "frontend",
    }
    if app_event_bus is not None:
        app_event_bus.publish(event)

    return {
        "status": "built",
        "workspace_id": workspace_id,
        "app_id": app_id,
        "source_kind": binding.source_kind,
        "source_record_id": binding.source_record_id,
        "frontend_mount": frontend_mount,
        "build_root": str(build_root),
        "event": event,
    }


def app_supports_frontend_build(store: AppStore, *, binding: WorkspaceAppBindingRecord, start_path: Path | None = None) -> bool:
    """Return whether a workspace app binding exposes the official frontend build operation."""
    try:
        source_root, parsed = resolve_workspace_app_surface(store, binding=binding, start_path=start_path)
    except AppHostingError:
        return False
    if parsed.contract.entrypoints.frontend is None:
        return False
    try:
        _frontend_build_root(source_root=source_root, frontend_mount=parsed.contract.entrypoints.frontend)
    except AppLifecycleError:
        return False
    return True


def _frontend_build_root(*, source_root: Path, frontend_mount: str) -> Path:
    frontend_source_root = source_root / frontend_mount.split("/", 1)[0]
    if (frontend_source_root / "package.json").is_file():
        return frontend_source_root
    if (source_root / "package.json").is_file():
        return source_root
    raise AppLifecycleError("Frontend build requires a package.json with a build script.")


def _run_npm_build(build_root: Path, *, app_id: str) -> None:
    package_payload = json.loads((build_root / "package.json").read_text(encoding="utf-8"))
    scripts = package_payload.get("scripts") if isinstance(package_payload, dict) else None
    if not isinstance(scripts, dict) or not scripts.get("build"):
        raise AppLifecycleError(f"App `{app_id}` package.json does not declare a build script.")
    try:
        require_supported_node_runtime()
    except RuntimeError as exc:
        raise AppLifecycleError(f"Frontend build for app `{app_id}` requires {NODE_RUNTIME_REQUIREMENT}: {exc}") from exc
    _ensure_node_dependencies(build_root, app_id=app_id)
    completed = subprocess.run(
        ["npm", "run", "build"],
        cwd=build_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise AppLifecycleError(f"Frontend build failed for app `{app_id}`: {detail}")


def _ensure_node_dependencies(build_root: Path, *, app_id: str) -> None:
    if (build_root / "node_modules").is_dir() and not _declared_dependency_dirs_missing(build_root):
        return
    if not (build_root / "package-lock.json").is_file():
        raise AppLifecycleError(f"Frontend build for app `{app_id}` requires npm ci; package-lock.json is missing.")
    completed = subprocess.run(
        ["npm", "ci"],
        cwd=build_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise AppLifecycleError(f"Frontend dependency install failed for app `{app_id}`: {detail}")


def _declared_dependency_dirs_missing(build_root: Path) -> bool:
    package_payload = json.loads((build_root / "package.json").read_text(encoding="utf-8"))
    dependencies: list[str] = []
    for key in ("dependencies", "devDependencies"):
        section = package_payload.get(key) if isinstance(package_payload, dict) else None
        if isinstance(section, dict):
            dependencies.extend(str(name) for name in section)
    return any(not (build_root / "node_modules" / dependency).exists() for dependency in dependencies)
