"""Core-owned audit authority for hosted built-in app read effects."""

from __future__ import annotations

from functools import lru_cache
import hashlib
import hmac
import json
from pathlib import Path
from typing import Literal

from core.apps.surface_descriptors import (
    app_cli_command_execution_metadata,
    app_mcp_tool_execution_metadata,
)
from core.shared.tool_effects import resolve_tool_effect_class


HOSTED_BUILTIN_APP_EFFECT_AUDIT_REVISION = "2026-09-02-p4-builtin-effects"
_AUDIT_PATH = Path(__file__).with_name("hosted_builtin_app_effect_audit.json")
_REPOSITORY_APPS_ROOT = Path(__file__).resolve().parents[2] / "apps"
_DESCRIPTOR_PATHS = {
    "cli": Path("cli/command_schemas.json"),
    "mcp": Path("mcp/tool_schemas.json"),
}
_ENTRYPOINT_PATHS = {
    "cli": Path("cli/app_cli.py"),
    "mcp": Path("mcp/server.py"),
}


def app_read_effect_has_core_audit_authority(
    definition,
    arguments: dict[str, object],
    *,
    surface: Literal["cli", "mcp"],
) -> bool:
    """Require exact platform source and audited descriptor bytes for app reads."""
    if getattr(definition, "owner_kind", None) != "app":
        return False
    resolved = _platform_builtin_surface(definition, surface=surface)
    if resolved is None:
        return False
    app_id, surface_name, app_root = resolved
    expected = _audited_descriptor_digests().get(app_id, {}).get(surface)
    descriptor_path = app_root / _DESCRIPTOR_PATHS[surface]
    if expected is None or not descriptor_path.is_file():
        return False
    try:
        observed = hashlib.sha256(descriptor_path.read_bytes()).hexdigest()
    except OSError:
        return False
    if not hmac.compare_digest(expected, observed):
        return False
    try:
        metadata = (
            app_cli_command_execution_metadata(app_root, surface_name)
            if surface == "cli"
            else app_mcp_tool_execution_metadata(app_root, surface_name)
        )
    except (OSError, UnicodeError):
        return False
    if (
        metadata.effect_class != getattr(definition, "effect_class", None)
        or metadata.supports_idempotency
        != getattr(definition, "supports_idempotency", None)
        or metadata.safe_to_retry != getattr(definition, "safe_to_retry", None)
        or metadata.argument_effects != getattr(definition, "argument_effects", None)
    ):
        return False
    return resolve_tool_effect_class(definition, arguments) == "read"


def audited_builtin_app_effect_descriptor_digests() -> dict[str, dict[str, str]]:
    """Return a copy of the exact descriptor audit inventory for contract tests."""
    return {
        app_id: dict(digests)
        for app_id, digests in _audited_descriptor_digests().items()
    }


def _platform_builtin_surface(
    definition,
    *,
    surface: Literal["cli", "mcp"],
) -> tuple[str, str, Path] | None:
    raw_entrypoint = getattr(definition, "entrypoint_path", None)
    if not isinstance(raw_entrypoint, str) or not raw_entrypoint:
        return None
    entrypoint = Path(raw_entrypoint)
    if not entrypoint.is_absolute() or not entrypoint.is_file():
        return None
    try:
        relative = entrypoint.resolve().relative_to(_REPOSITORY_APPS_ROOT.resolve())
    except (OSError, ValueError):
        return None
    if len(relative.parts) < 2:
        return None
    app_id = relative.parts[0]
    if getattr(definition, "owner_id", None) != app_id:
        return None
    app_root = _REPOSITORY_APPS_ROOT / app_id
    try:
        expected_entrypoint = (app_root / _ENTRYPOINT_PATHS[surface]).resolve(
            strict=True
        )
    except OSError:
        return None
    if entrypoint.resolve() != expected_entrypoint:
        return None
    identity = getattr(
        definition,
        "command_id" if surface == "cli" else "tool_name",
        None,
    )
    prefix = f"app.{app_id}."
    if not isinstance(identity, str) or not identity.startswith(prefix):
        return None
    surface_name = identity.removeprefix(prefix)
    if not surface_name:
        return None
    return app_id, surface_name, app_root


@lru_cache(maxsize=1)
def _audited_descriptor_digests() -> dict[str, dict[str, str]]:
    try:
        payload = json.loads(_AUDIT_PATH.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema_version", "audit_revision", "apps"}
            or payload.get("schema_version") != "1"
            or payload.get("audit_revision")
            != HOSTED_BUILTIN_APP_EFFECT_AUDIT_REVISION
            or not isinstance(payload.get("apps"), dict)
        ):
            return {}
        audited: dict[str, dict[str, str]] = {}
        for app_id, raw_digests in payload["apps"].items():
            if (
                not isinstance(app_id, str)
                or not app_id
                or not isinstance(raw_digests, dict)
                or not raw_digests
                or not set(raw_digests).issubset(_DESCRIPTOR_PATHS)
            ):
                return {}
            digests: dict[str, str] = {}
            for surface, digest in raw_digests.items():
                if (
                    not isinstance(digest, str)
                    or len(digest) != 64
                    or any(character not in "0123456789abcdef" for character in digest)
                ):
                    return {}
                digests[surface] = digest
            audited[app_id] = digests
        return audited
    except (OSError, json.JSONDecodeError):
        return {}


__all__ = [
    "HOSTED_BUILTIN_APP_EFFECT_AUDIT_REVISION",
    "app_read_effect_has_core_audit_authority",
    "audited_builtin_app_effect_descriptor_digests",
]
