"""Core-owned persistence adapter administration helpers."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import RLock
from typing import Any

from core.api.control_store import (
    DEFAULT_JSON_CONTROL_STORE_ROOT,
    DEFAULT_MONGO_DATABASE,
    ControlPlaneCollections,
    ControlStoreSettings,
    build_control_plane_collections,
    control_plane_collection_specs,
)
from core.api.http import StartResponse, json_response, status_line
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession
from core.observability.service import record_platform_audit, record_platform_event
from core.recovery.backend_service import restart_backend_service
from core.shared.env_file import quote_env_value, read_env_file


_MIGRATION_LOCK = RLock()
_DEFAULT_SERVICE_NAME = "maverick-core.service"
_DEFAULT_HEALTH_URL = "http://127.0.0.1:8014/health"
_CONTROL_STORE_ENV_KEYS = {
    "MAVERICK_CONTROL_STORE",
    "MAVERICK_JSON_CONTROL_STORE_ROOT",
    "MAVERICK_LOCAL_STATE_ROOT",
    "MAVERICK_ALLOW_LOCAL_JSON_CONTROL_STORE",
    "MAVERICK_MONGODB_URI",
    "MAVERICK_MONGODB_DATABASE",
    "MAVERICK_MONGODB_USERNAME",
    "MAVERICK_MONGODB_PASSWORD_REF",
}


def handle_persistence_admin_api(
    state: PlatformState,
    context: RequestSession,
    path: str,
    method: str,
    body: dict[str, Any],
    start_response: StartResponse,
) -> list[bytes] | None:
    """Handle app-agnostic admin routes for persistence adapter operations."""
    if not path.startswith("/api/admin/persistence"):
        return None
    if path == "/api/admin/persistence" and method == "GET":
        return json_response(
            start_response,
            persistence_status_payload(
                repository_root=state.repository_root,
                active_settings=state.control_store_settings,
                active_collections=state.control_plane_collections,
            ),
        )
    if path == "/api/admin/persistence/migrations/dry-run" and method == "POST":
        try:
            payload = dry_run_persistence_migration(
                repository_root=state.repository_root,
                source_settings=state.control_store_settings,
                source_collections=state.control_plane_collections,
                target_payload=body,
            )
        except (RuntimeError, ValueError) as error:
            return json_response(
                start_response,
                {"error": "invalid_persistence_migration", "detail": str(error)},
                status="400 Bad Request",
            )
        return json_response(start_response, payload)
    if path == "/api/admin/persistence/migrations/apply" and method == "POST":
        try:
            payload = apply_persistence_migration(
                repository_root=state.repository_root,
                source_settings=state.control_store_settings,
                source_collections=state.control_plane_collections,
                target_payload=body,
            )
        except (RuntimeError, ValueError) as error:
            return json_response(
                start_response,
                {"error": "invalid_persistence_migration", "detail": str(error)},
                status="400 Bad Request",
            )
        _audit_persistence_action(
            state,
            context,
            action="persistence.migration.apply",
            payload={"target_adapter": payload["target_adapter"], "collections": payload["collections"]},
        )
        return json_response(start_response, payload)
    if path == "/api/admin/persistence/restart-backend" and method == "POST":
        result = restart_backend_service(
            service_name=os.environ.get("MAVERICK_CORE_SERVICE_NAME", "maverick-core.service"),
            health_url=os.environ.get("MAVERICK_CORE_HEALTH_URL", "http://127.0.0.1:8014/health"),
        )
        _audit_persistence_action(
            state,
            context,
            action="persistence.backend.restart",
            payload=result.to_payload(),
        )
        return json_response(start_response, result.to_payload())
    return json_response(start_response, {"error": "not_found"}, status=status_line(404))


def _audit_persistence_action(
    state: PlatformState,
    context: RequestSession,
    *,
    action: str,
    payload: dict[str, Any],
) -> None:
    record_platform_audit(
        state.observability_store,
        action=action,
        status="succeeded",
        source_domain="persistence",
        detail=f"Admin `{context.user.user_id}` performed `{action}`.",
        payload={"actor_user_id": context.user.user_id, **payload},
    )
    record_platform_event(
        state.observability_store,
        event_type=f"{action}.succeeded",
        event_plane="platform",
        source_domain="persistence",
        payload={"actor_user_id": context.user.user_id, **payload},
    )


def persistence_status_payload(
    *,
    repository_root: Path,
    active_settings: ControlStoreSettings,
    active_collections: ControlPlaneCollections,
) -> dict[str, Any]:
    """Return operator-visible persistence adapter status."""
    return {
        "active_adapter": _settings_payload(repository_root, active_settings),
        "supported_adapters": [
            {
                "kind": "json",
                "label": "JSON",
                "default": True,
                "requires": [],
                "default_json_root": DEFAULT_JSON_CONTROL_STORE_ROOT,
            },
            {
                "kind": "mongo",
                "label": "MongoDB",
                "default": False,
                "requires": ["pymongo", "MAVERICK_MONGODB_URI"],
                "available": _mongo_driver_available(),
                "default_database": DEFAULT_MONGO_DATABASE,
            },
        ],
        "collections": _collection_counts(active_collections),
        "restart_required_for_cutover": True,
    }


def dry_run_persistence_migration(
    *,
    repository_root: Path,
    source_settings: ControlStoreSettings,
    source_collections: ControlPlaneCollections,
    target_payload: dict[str, Any],
) -> dict[str, Any]:
    """Validate a target adapter and return the full control-plane copy plan."""
    target_settings = target_settings_from_payload(repository_root=repository_root, payload=target_payload)
    target_collections = build_control_plane_collections(target_settings)
    return {
        "status": "dry_run",
        "source_adapter": _settings_payload(repository_root, source_settings),
        "target_adapter": _settings_payload(repository_root, target_settings),
        "same_adapter": _same_adapter(source_settings, target_settings),
        "collections": _collection_counts(source_collections),
        "target_collections": _collection_counts(target_collections),
        "restart_required_for_cutover": True,
        "env_file": str(_service_env_file(repository_root)),
    }


def apply_persistence_migration(
    *,
    repository_root: Path,
    source_settings: ControlStoreSettings,
    source_collections: ControlPlaneCollections,
    target_payload: dict[str, Any],
) -> dict[str, Any]:
    """Copy every control-plane collection to one target adapter and prepare cutover."""
    target_settings = target_settings_from_payload(repository_root=repository_root, payload=target_payload)
    delete_source = bool(target_payload.get("delete_source"))
    restart_backend = bool(target_payload.get("restart_backend"))
    service_name = os.environ.get("MAVERICK_CORE_SERVICE_NAME", _DEFAULT_SERVICE_NAME)
    health_url = os.environ.get("MAVERICK_CORE_HEALTH_URL", _DEFAULT_HEALTH_URL)
    if _same_adapter(source_settings, target_settings):
        raise ValueError("Target adapter is already active.")
    if delete_source and not restart_backend:
        raise ValueError("Deleting source storage requires `restart_backend=true`.")
    with _MIGRATION_LOCK:
        target_collections = build_control_plane_collections(target_settings)
        copied = _copy_collections(source_collections, target_collections)
        env_result = _write_cutover_env_file(repository_root=repository_root, target_settings=target_settings)
        if delete_source and not env_result["updated"]:
            raise ValueError("Deleting source storage requires an updated service env file for cutover.")
        cleanup_result = (
            _schedule_source_cleanup_after_restart(
                repository_root=repository_root,
                source_settings=source_settings,
                target_settings=target_settings,
                service_name=service_name,
                health_url=health_url,
            )
            if delete_source
            else None
        )
        restart_result = (
            restart_backend_service(service_name=service_name, health_url=health_url).to_payload()
            if restart_backend
            else None
        )
    payload = {
        "status": "prepared",
        "source_adapter": _settings_payload(repository_root, source_settings),
        "target_adapter": _settings_payload(repository_root, target_settings),
        "collections": copied,
        "env_file": env_result,
        "restart_required_for_cutover": True,
        "active_adapter_changed": False,
        "source_cleanup": cleanup_result,
    }
    if restart_result is not None:
        payload["backend_restart"] = restart_result
    return payload


def target_settings_from_payload(*, repository_root: Path, payload: dict[str, Any]) -> ControlStoreSettings:
    """Build target settings from an app-agnostic operator payload."""
    kind = str(payload.get("kind") or payload.get("adapter") or "").strip().lower()
    if kind == "mongodb":
        kind = "mongo"
    if kind not in {"json", "mongo"}:
        raise ValueError("Target adapter kind must be `json` or `mongo`.")
    json_root = Path(str(payload.get("json_root") or DEFAULT_JSON_CONTROL_STORE_ROOT).strip())
    if not json_root.is_absolute():
        json_root = repository_root / json_root
    mongo_uri = str(payload.get("mongodb_uri") or payload.get("mongo_uri") or "").strip() or None
    mongo_database = str(payload.get("mongodb_database") or payload.get("mongo_database") or "").strip()
    mongo_username = str(payload.get("mongodb_username") or payload.get("mongo_username") or "").strip() or None
    mongo_password_ref = str(payload.get("mongodb_password_ref") or payload.get("mongo_password_ref") or "").strip() or None
    if kind == "mongo" and not mongo_uri:
        raise ValueError("MongoDB target requires `mongodb_uri`.")
    return ControlStoreSettings(
        kind=kind,
        json_root=json_root,
        mongo_uri=mongo_uri,
        mongo_database=mongo_database or DEFAULT_MONGO_DATABASE,
        mongo_username=mongo_username,
        mongo_password_ref=mongo_password_ref,
    )


def _copy_collections(
    source_collections: ControlPlaneCollections,
    target_collections: ControlPlaneCollections,
) -> list[dict[str, Any]]:
    source_specs = {spec.name: spec for spec in control_plane_collection_specs(source_collections)}
    copied: list[dict[str, Any]] = []
    for target_spec in control_plane_collection_specs(target_collections):
        source_spec = source_specs[target_spec.name]
        documents = source_spec.collection.find({})
        if not isinstance(documents, list):
            documents = list(documents)
        replace_all = getattr(target_spec.collection, "replace_all", None)
        if replace_all is None:
            raise RuntimeError(f"Target collection `{target_spec.name}` does not support full replacement.")
        replace_all(documents)
        copied.append({"name": target_spec.name, "count": len(documents)})
    return copied


def _collection_counts(collections: ControlPlaneCollections) -> list[dict[str, Any]]:
    counts: list[dict[str, Any]] = []
    for spec in control_plane_collection_specs(collections):
        documents = spec.collection.find({})
        if not isinstance(documents, list):
            documents = list(documents)
        counts.append({"name": spec.name, "count": len(documents)})
    return counts


def _settings_payload(repository_root: Path, settings: ControlStoreSettings) -> dict[str, Any]:
    payload = asdict(settings)
    payload["json_root"] = _display_path(repository_root, settings.json_root)
    if settings.kind != "mongo":
        payload["mongo_uri"] = None
    return payload


def _display_path(repository_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(repository_root))
    except ValueError:
        return str(path)


def _same_adapter(left: ControlStoreSettings, right: ControlStoreSettings) -> bool:
    if left.kind != right.kind:
        return False
    if left.kind == "json":
        return _same_path(left.json_root, right.json_root)
    return (
        left.mongo_uri == right.mongo_uri
        and left.mongo_database == right.mongo_database
        and left.mongo_username == right.mongo_username
        and left.mongo_password_ref == right.mongo_password_ref
    )


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve(strict=False) == right.resolve(strict=False)
    except OSError:
        return str(left) == str(right)


def _mongo_driver_available() -> bool:
    return importlib.util.find_spec("pymongo") is not None


def _service_env_file(repository_root: Path) -> Path:
    configured = os.environ.get("MAVERICK_SERVICE_ENV_FILE", "").strip()
    return Path(configured) if configured else repository_root / ".env.maverick"


def _write_cutover_env_file(*, repository_root: Path, target_settings: ControlStoreSettings) -> dict[str, Any]:
    env_file = _service_env_file(repository_root)
    updates = _target_env_values(repository_root=repository_root, target_settings=target_settings)
    if not env_file.exists():
        return {
            "path": str(env_file),
            "updated": False,
            "missing": True,
            "updates": updates,
        }
    existing = read_env_file(env_file)
    for key in _CONTROL_STORE_ENV_KEYS:
        existing.pop(key, None)
    existing.update(updates)
    lines = [
        "# Generated by scripts/install_maverick.py.",
        "# Contains local bootstrap credentials and secret refs; keep permissions restricted.",
    ]
    lines.extend(f"{key}={quote_env_value(str(value))}" for key, value in existing.items())
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env_file.chmod(0o600)
    return {
        "path": str(env_file),
        "updated": True,
        "missing": False,
        "updates": updates,
    }


def _target_env_values(*, repository_root: Path, target_settings: ControlStoreSettings) -> dict[str, str]:
    values = {
        "MAVERICK_CONTROL_STORE": target_settings.kind,
        "MAVERICK_JSON_CONTROL_STORE_ROOT": _display_path(repository_root, target_settings.json_root),
    }
    if target_settings.kind == "mongo":
        assert target_settings.mongo_uri is not None
        values["MAVERICK_MONGODB_URI"] = target_settings.mongo_uri
        values["MAVERICK_MONGODB_DATABASE"] = target_settings.mongo_database
        if target_settings.mongo_username:
            values["MAVERICK_MONGODB_USERNAME"] = target_settings.mongo_username
        if target_settings.mongo_password_ref:
            values["MAVERICK_MONGODB_PASSWORD_REF"] = target_settings.mongo_password_ref
    return values


def _schedule_source_cleanup_after_restart(
    *,
    repository_root: Path,
    source_settings: ControlStoreSettings,
    target_settings: ControlStoreSettings,
    service_name: str,
    health_url: str,
) -> dict[str, Any]:
    plan_root = repository_root / ".maverick" / "persistence-cleanup"
    plan_root.mkdir(parents=True, exist_ok=True)
    plan_root.chmod(0o700)
    plan_path = plan_root / f"{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%S%f')}.json"
    plan = {
        "repository_root": str(repository_root),
        "source_adapter": _raw_settings_payload(source_settings),
        "target_adapter": _raw_settings_payload(target_settings),
        "service_name": service_name,
        "health_url": health_url,
        "previous_pid": os.getpid(),
        "timeout_seconds": 120.0,
    }
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    plan_path.chmod(0o600)
    subprocess.Popen(
        [sys.executable, "-m", "core.api.persistence_cleanup_worker", str(plan_path)],
        cwd=repository_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {
        "scheduled": True,
        "plan_path": str(plan_path),
        "mode": "after_restart_health",
    }


def _raw_settings_payload(settings: ControlStoreSettings) -> dict[str, Any]:
    return {
        "kind": settings.kind,
        "json_root": str(settings.json_root),
        "mongo_uri": settings.mongo_uri,
        "mongo_database": settings.mongo_database,
        "mongo_username": settings.mongo_username,
        "mongo_password_ref": settings.mongo_password_ref,
    }
