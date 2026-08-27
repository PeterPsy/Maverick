"""Redaction-safe normalization for receipt-fast artifact health."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


ARTIFACT_ERROR_CODES = frozenset(
    {
        "artifact_missing",
        "artifact_integrity_mismatch",
        "artifact_permissions_invalid",
        "runtime_binding_invalid",
    }
)


def artifact_health(status: object) -> dict[str, bool]:
    value = status.get("health") if isinstance(status, dict) else None
    if not isinstance(value, dict):
        return unavailable_artifact_health()
    return {
        "artifact_available": value.get("artifact_available") is True,
        "artifact_verified": value.get("artifact_verified") is True,
        "artifact_protected": value.get("artifact_protected") is True,
    }


def unavailable_artifact_health() -> dict[str, bool]:
    return {
        "artifact_available": False,
        "artifact_verified": False,
        "artifact_protected": False,
    }


def failed_artifact_status(*, code: object, phase: object) -> dict[str, Any]:
    code_value = str(code)
    safe_code = code_value if code_value in ARTIFACT_ERROR_CODES else "artifact_missing"
    phase_value = str(phase)
    safe_phase = (
        phase_value
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", phase_value)
        else "artifact_status"
    )
    if safe_code == "artifact_permissions_invalid":
        health = {
            "artifact_available": True,
            "artifact_verified": False,
            "artifact_protected": False,
        }
    elif safe_code == "artifact_integrity_mismatch":
        health = {
            "artifact_available": True,
            "artifact_verified": False,
            "artifact_protected": True,
        }
    else:
        health = unavailable_artifact_health()
    return {
        "schema_version": "1",
        "operation": "status",
        "status": "invalid",
        "operational": False,
        "health": health,
        "active_error_code": safe_code,
        "active_error_phase": safe_phase,
    }


def artifact_matches_active(status: object, active: object) -> bool:
    artifact_active = status.get("active") if isinstance(status, dict) else None
    return bool(
        isinstance(artifact_active, dict)
        and isinstance(active, dict)
        and artifact_active.get("runtime_artifact_sha256")
        == active.get("runtime_artifact_sha256")
        and artifact_active.get("web_overlay_sha256") == active.get("web_overlay_sha256")
    )


def read_fast_artifact_status(
    data_root: Path,
    *,
    workspace_id: str,
) -> dict[str, Any]:
    """Run the bounded store status operation and normalize every failure."""
    try:
        from opendesign_artifact_operations import run_artifact_operation

        status = run_artifact_operation(
            "status",
            data_root=data_root,
            workspace_id=workspace_id,
        )
    except Exception as error:
        return failed_artifact_status(
            code=getattr(error, "code", "artifact_missing"),
            phase=getattr(error, "phase", "artifact_status"),
        )
    if not _valid_fast_artifact_status(status):
        return failed_artifact_status(
            code="runtime_binding_invalid",
            phase="artifact_status",
        )
    return status


def _valid_fast_artifact_status(status: object) -> bool:
    if not isinstance(status, dict):
        return False
    health = status.get("health")
    active = status.get("active")
    expected_health = {
        "artifact_available",
        "artifact_verified",
        "artifact_protected",
    }
    if (
        status.get("schema_version") != "1"
        or status.get("operation") != "status"
        or not isinstance(status.get("operational"), bool)
        or not isinstance(health, dict)
        or set(health) != expected_health
        or any(not isinstance(health[key], bool) for key in expected_health)
        or status["operational"] != all(health.values())
        or not isinstance(active, dict)
    ):
        return False
    return all(
        isinstance(active.get(key), str)
        and re.fullmatch(r"[0-9a-f]{64}", active[key]) is not None
        for key in ("runtime_artifact_sha256", "web_overlay_sha256")
    )
