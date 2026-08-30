"""Validate positive Core lifecycle evidence for the workspace-bound writer."""

from __future__ import annotations

from pathlib import Path
from typing import Any


STOPPED_SERVICE_STATES = {"failed", "not_started", "stopped"}


def require_verified_writer_ready(
    response: object,
    *,
    workspace_id: str,
    app_data_root: Path,
    app_id: str = "design-studio",
) -> dict[str, Any]:
    """Require readiness for every service in the exact canonical binding."""
    if not isinstance(response, dict):
        raise ValueError("Core returned no writer-readiness evidence")
    try:
        expected_root = Path(app_data_root).resolve(strict=True)
        observed_root = Path(str(response.get("data_root") or "")).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError("Core writer-readiness binding is unavailable") from error
    declared = response.get("declared_service_count")
    verified = response.get("verified_ready_service_count")
    services = response.get("services")
    if (
        response.get("ready") is not True
        or response.get("workspace_id") != workspace_id
        or response.get("app_id") != app_id
        or observed_root != expected_root
        or isinstance(declared, bool)
        or not isinstance(declared, int)
        or declared < 1
        or isinstance(verified, bool)
        or not isinstance(verified, int)
        or verified != declared
        or not isinstance(services, list)
        or len(services) != declared
    ):
        raise ValueError("Core writer-readiness evidence does not match the requested binding")
    sidecar_ids: set[str] = set()
    instance_ids: set[str] = set()
    for service in services:
        instance_id = service.get("live_instance_id") if isinstance(service, dict) else None
        if (
            not isinstance(service, dict)
            or not isinstance(service.get("sidecar_id"), str)
            or not service["sidecar_id"]
            or service["sidecar_id"] in sidecar_ids
            or not isinstance(instance_id, str)
            or not instance_id
            or instance_id in instance_ids
            or service.get("state") != "ready"
        ):
            raise ValueError("Core did not verify every declared writer service as ready")
        sidecar_ids.add(service["sidecar_id"])
        instance_ids.add(instance_id)
    if "opendesign" not in sidecar_ids:
        raise ValueError("Core did not verify the OpenDesign writer service")
    return response


def require_verified_writer_stop(
    response: object,
    *,
    workspace_id: str,
    app_data_root: Path,
    app_id: str = "design-studio",
) -> dict[str, Any]:
    """Require a resolved binding and one verified stopped declared service."""
    if not isinstance(response, dict):
        raise ValueError("Core returned no writer-stop evidence")
    try:
        expected_root = Path(app_data_root).resolve(strict=True)
        observed_root = Path(str(response.get("data_root") or "")).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError("Core writer-stop binding is unavailable") from error
    declared = response.get("declared_service_count")
    verified = response.get("verified_stopped_service_count")
    services = response.get("services")
    if (
        response.get("ready") is not False
        or response.get("browser_sessions_revoked") is not True
        or response.get("workspace_id") != workspace_id
        or response.get("app_id") != app_id
        or observed_root != expected_root
        or isinstance(declared, bool)
        or not isinstance(declared, int)
        or declared < 1
        or isinstance(verified, bool)
        or not isinstance(verified, int)
        or verified != declared
        or not isinstance(services, list)
        or len(services) != declared
    ):
        raise ValueError("Core writer-stop evidence does not match the requested binding")
    sidecar_ids: set[str] = set()
    for service in services:
        if (
            not isinstance(service, dict)
            or not isinstance(service.get("sidecar_id"), str)
            or not service["sidecar_id"]
            or service["sidecar_id"] in sidecar_ids
            or service.get("live_instance_id") is not None
            or service.get("state") not in STOPPED_SERVICE_STATES
        ):
            raise ValueError("Core did not verify every declared writer service as stopped")
        sidecar_ids.add(service["sidecar_id"])
    if "opendesign" not in sidecar_ids:
        raise ValueError("Core did not verify the OpenDesign writer service")
    return response


def require_verified_writer_status(
    response: object,
    *,
    workspace_id: str,
    app_data_root: Path,
    app_id: str = "design-studio",
) -> dict[str, Any]:
    """Accept a status fallback only when every canonical service is proven stopped."""
    if not isinstance(response, dict):
        raise ValueError("Core returned no writer status evidence")
    try:
        expected_root = Path(app_data_root).resolve(strict=True)
        observed_root = Path(str(response.get("data_root") or "")).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError("Core writer-status binding is unavailable") from error
    declared = response.get("declared_service_count")
    verified = response.get("verified_stopped_service_count")
    services = response.get("services")
    if (
        response.get("workspace_id") != workspace_id
        or response.get("app_id") != app_id
        or observed_root != expected_root
        or isinstance(declared, bool)
        or not isinstance(declared, int)
        or declared < 1
        or isinstance(verified, bool)
        or not isinstance(verified, int)
        or verified != declared
        or not isinstance(services, list)
        or len(services) != declared
    ):
        raise ValueError("Core writer-status evidence does not match the requested binding")
    sidecar_ids: set[str] = set()
    for service in services:
        if (
            not isinstance(service, dict)
            or not isinstance(service.get("sidecar_id"), str)
            or not service["sidecar_id"]
            or service["sidecar_id"] in sidecar_ids
            or service.get("live_instance_id") is not None
            or service.get("state") not in STOPPED_SERVICE_STATES
        ):
            raise ValueError("Core status did not verify every writer service as stopped")
        sidecar_ids.add(service["sidecar_id"])
    if "opendesign" not in sidecar_ids:
        raise ValueError("Core status did not verify the OpenDesign writer service")
    return response


__all__ = [
    "require_verified_writer_ready",
    "require_verified_writer_status",
    "require_verified_writer_stop",
]
