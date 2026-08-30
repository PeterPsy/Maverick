"""Parser helpers for protected sidecar artifacts and lifecycle policy."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from core.apps.contract_validation import (
    _expect_bool,
    _expect_mapping,
    _expect_relative_contract_path,
    _expect_string,
    _expect_slug,
    _expect_timeout,
    _reject_unexpected_fields,
)
from core.apps.errors import AppContractValidationError
from core.apps.models import (
    HttpSidecarArtifactMountSpec,
    HttpSidecarDataMountSpec,
    HttpSidecarDiagnosticsSpec,
    HttpSidecarHostPrepareSpec,
    HttpSidecarPrewarmSpec,
    HttpSidecarRootFilesystemSpec,
)


def parse_sidecar_data_mount(
    payload: dict[str, Any], *, label: str
) -> HttpSidecarDataMountSpec:
    """Parse one canonical app-data subtree exposed as the sandbox `/data`."""
    mount_label = f"{label}.data_mount"
    _reject_unexpected_fields(payload, {"subpath"}, label=mount_label)
    value = _expect_string(payload, "subpath")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
        or len(value) > 256
    ):
        raise AppContractValidationError(
            f"`{mount_label}.subpath` must be a canonical path inside app data."
        )
    return HttpSidecarDataMountSpec(subpath=path.as_posix())


def parse_sidecar_host_prepare(
    source_root,
    payload: dict[str, Any],
    *,
    label: str,
) -> HttpSidecarHostPrepareSpec:
    """Parse a bounded host-only prelaunch hook and its explicit output keys."""
    prepare_label = f"{label}.host_prepare"
    fields = {"entrypoint", "timeout_seconds", "environment_keys"}
    _reject_unexpected_fields(payload, fields, label=prepare_label)
    if set(payload) != fields:
        raise AppContractValidationError(
            f"`{prepare_label}` must declare entrypoint, timeout_seconds, and environment_keys."
        )
    entrypoint = _expect_relative_contract_path(
        source_root,
        _expect_string(payload, "entrypoint"),
        label=f"{prepare_label}.entrypoint",
    )
    timeout_seconds = _expect_timeout(payload, "timeout_seconds", default=30)
    raw_keys = payload.get("environment_keys")
    if not isinstance(raw_keys, list) or not raw_keys or len(raw_keys) > 16:
        raise AppContractValidationError(
            f"`{prepare_label}.environment_keys` must be a non-empty bounded list."
        )
    keys: list[str] = []
    platform_keys = {
        "MAVERICK_APP_ID",
        "MAVERICK_APP_DATA_ROOT",
        "MAVERICK_APP_SOURCE_ROOT",
    }
    for key in raw_keys:
        if (
            not isinstance(key, str)
            or not key.startswith("MAVERICK_APP_")
            or key in platform_keys
            or len(key) > 96
            or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for character in key)
        ):
            raise AppContractValidationError(
                f"`{prepare_label}.environment_keys` contains an invalid app-owned key."
            )
        if key in keys:
            raise AppContractValidationError(
                f"`{prepare_label}.environment_keys` must not contain duplicates."
            )
        keys.append(key)
    return HttpSidecarHostPrepareSpec(
        entrypoint=entrypoint,
        timeout_seconds=timeout_seconds,
        environment_keys=keys,
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


def parse_sidecar_root_filesystem(
    payload: dict[str, Any],
    *,
    artifact_ids: set[str],
    label: str,
) -> HttpSidecarRootFilesystemSpec:
    """Parse an immutable artifact-relative execution root declaration."""
    root_label = f"{label}.root_filesystem"
    _reject_unexpected_fields(payload, {"artifact_id", "subpath"}, label=root_label)
    artifact_id = _expect_slug(payload, "artifact_id")
    if artifact_id not in artifact_ids:
        raise AppContractValidationError(
            f"`{root_label}.artifact_id` must reference a declared artifact mount."
        )
    value = _expect_string(payload, "subpath")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or len(value) > 512
    ):
        raise AppContractValidationError(
            f"`{root_label}.subpath` must be a canonical path inside the artifact namespace."
        )
    return HttpSidecarRootFilesystemSpec(artifact_id=artifact_id, subpath=path.as_posix())


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
