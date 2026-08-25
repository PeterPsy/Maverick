"""Validated request contract for recovery health diagnostics."""

from __future__ import annotations

from collections.abc import Mapping

from core.recovery.models import HealthTargetKind


RECOVERY_HEALTH_INPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "target_kind": {"type": "string", "enum": ["runtime", "provider", "app"]},
        "session_id": {"type": "string", "minLength": 1},
        "provider_id": {"type": "string", "minLength": 1},
        "app_id": {"type": "string", "minLength": 1},
        "workspace_id": {"type": "string", "minLength": 1},
    },
    "required": ["target_kind"],
    "oneOf": [
        {
            "properties": {"target_kind": {"const": "runtime"}},
            "required": ["session_id"],
        },
        {
            "properties": {"target_kind": {"const": "provider"}},
            "required": ["provider_id"],
        },
        {
            "properties": {"target_kind": {"const": "app"}},
            "required": ["app_id"],
        },
    ],
}

_TARGET_ID_FIELDS = {
    "runtime": "session_id",
    "provider": "provider_id",
    "app": "app_id",
}


class RecoveryHealthArgumentError(ValueError):
    """Stable invalid-argument result for a recovery health request."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def parse_recovery_health_target(
    arguments: Mapping[str, object],
) -> tuple[HealthTargetKind, str]:
    """Return a validated health target without leaking raw mapping failures."""
    target_kind = str(arguments.get("target_kind") or "").strip()
    if not target_kind:
        raise RecoveryHealthArgumentError("target_kind_required")
    target_id_field = _TARGET_ID_FIELDS.get(target_kind)
    if target_id_field is None:
        raise RecoveryHealthArgumentError("target_kind_invalid")
    target_id = str(arguments.get(target_id_field) or "").strip()
    if not target_id:
        raise RecoveryHealthArgumentError(f"{target_id_field}_required")
    return target_kind, target_id  # type: ignore[return-value]
