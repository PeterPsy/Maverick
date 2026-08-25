"""Parser helpers for protected sidecar artifacts and lifecycle policy."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from core.apps.contract_validation import (
    _expect_bool,
    _expect_mapping,
    _expect_string,
    _expect_slug,
    _reject_unexpected_fields,
)
from core.apps.errors import AppContractValidationError
from core.apps.models import (
    HttpSidecarArtifactMountSpec,
    HttpSidecarDiagnosticsSpec,
    HttpSidecarPrewarmSpec,
)


def parse_sidecar_diagnostics(payload: dict[str, Any], *, label: str) -> HttpSidecarDiagnosticsSpec:
    """Parse one bounded app-data-relative startup status declaration."""
    diagnostics_label = f"{label}.diagnostics"
    _reject_unexpected_fields(payload, {"status_file"}, label=diagnostics_label)
    value = _expect_string(payload, "status_file")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise AppContractValidationError(f"`{diagnostics_label}.status_file` must stay inside app data.")
    if len(value) > 256:
        raise AppContractValidationError(f"`{diagnostics_label}.status_file` is too long.")
    return HttpSidecarDiagnosticsSpec(status_file=path.as_posix())


def parse_sidecar_artifact_mounts(payload: object, *, label: str) -> list[HttpSidecarArtifactMountSpec]:
    """Parse fixed platform-owned read-only artifact mount declarations."""
    mount_label = f"{label}.artifact_mounts"
    if not isinstance(payload, list):
        raise AppContractValidationError(f"`{mount_label}` must be a list.")
    mounts: list[HttpSidecarArtifactMountSpec] = []
    seen: set[str] = set()
    for index, item in enumerate(payload):
        item_label = f"{mount_label}[{index}]"
        item_payload = _expect_mapping(item, label=item_label)
        _reject_unexpected_fields(item_payload, {"id", "mount_path"}, label=item_label)
        artifact_id = _expect_slug(item_payload, "id")
        if artifact_id in seen:
            raise AppContractValidationError(f"Duplicate HTTP sidecar artifact mount id `{artifact_id}`.")
        mount_path = _expect_string(item_payload, "mount_path")
        expected_path = f"/artifacts/{artifact_id}"
        if mount_path != expected_path:
            raise AppContractValidationError(
                f"`{item_label}.mount_path` must be the platform-owned path `{expected_path}`."
            )
        seen.add(artifact_id)
        mounts.append(HttpSidecarArtifactMountSpec(artifact_id=artifact_id, mount_path=mount_path))
    return mounts


def parse_sidecar_prewarm(payload: dict[str, Any], *, label: str) -> HttpSidecarPrewarmSpec:
    """Parse the complete declarative keep-alive prewarm policy."""
    prewarm_label = f"{label}.prewarm"
    fields = {"on_core_start", "on_install", "on_activation", "keep_alive"}
    _reject_unexpected_fields(payload, fields, label=prewarm_label)
    if set(payload) != fields:
        raise AppContractValidationError(f"`{prewarm_label}` must declare every prewarm policy field.")
    prewarm = HttpSidecarPrewarmSpec(
        on_core_start=_expect_bool(payload, "on_core_start"),
        on_install=_expect_bool(payload, "on_install"),
        on_activation=_expect_bool(payload, "on_activation"),
        keep_alive=_expect_bool(payload, "keep_alive"),
    )
    if not (prewarm.on_core_start or prewarm.on_install or prewarm.on_activation):
        raise AppContractValidationError(f"`{prewarm_label}` must enable at least one trigger.")
    if not prewarm.keep_alive:
        raise AppContractValidationError(f"`{prewarm_label}.keep_alive` must be true.")
    return prewarm
