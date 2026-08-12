"""Resolve one verified OpenDesign bundle and data generation for launch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opendesign_artifact import ArtifactError, selected_asset, validate_bundle_manifest
from opendesign_generation_control import (
    load_generation_control_metadata,
    load_runtime_generation_control,
    resolve_generation_data_dir,
)
from opendesign_generation_model import (
    GenerationControl,
    GenerationControlError,
    LaunchSelection,
)
from opendesign_materialization import MaterializedBundle, discover_verified_bundles
from opendesign_web_overlay import VerifiedWebOverlay, discover_verified_overlays


@dataclass(frozen=True)
class RuntimeBinding:
    bundle: MaterializedBundle
    overlay: VerifiedWebOverlay
    data_dir: Path
    control: GenerationControl

    @property
    def active(self) -> LaunchSelection:
        return self.control.active


def resolve_runtime_binding(
    *,
    registry_root: Path,
    web_registry_root: Path,
    web_trust_contract: Path,
    generation_root: Path,
    manifest: dict[str, Any],
) -> RuntimeBinding:
    """Select only the exact active runtime/overlay/data launch selection."""
    validate_bundle_manifest(manifest, require_artifact_digest=True)
    current_asset = selected_asset(manifest, require_artifact_digest=True)
    current_digest = current_asset["sha256"]
    try:
        preliminary_control = load_generation_control_metadata(generation_root)
    except GenerationControlError as exc:
        raise ArtifactError(f"OpenDesign generation control is invalid: {exc}") from exc
    required_digests = {current_digest, preliminary_control.active.runtime_artifact_sha256}
    bundles = discover_verified_bundles(
        registry_root,
        required_digests=required_digests,
    )
    current = bundles.get(current_digest)
    if current is None:
        raise ArtifactError("Pinned OpenDesign artifact is not materialized")
    current_version = manifest["upstream"]["release_version"]
    if current.opendesign_version != current_version:
        raise ArtifactError("Pinned OpenDesign artifact version does not match its materialization")
    if current.file_manifest_sha256 != current_asset["file_manifest_sha256"]:
        raise ArtifactError("Pinned OpenDesign file manifest does not match its materialization")
    if current.upstream_commit != manifest["upstream"]["commit"]:
        raise ArtifactError("Pinned OpenDesign commit does not match its materialization")

    verified_artifacts = {
        digest: bundle.opendesign_version
        for digest, bundle in bundles.items()
    }
    required_overlays = {preliminary_control.active.web_overlay_sha256}
    if preliminary_control.previous_web is not None:
        required_overlays.add(preliminary_control.previous_web.web_overlay_sha256)
    overlays = discover_verified_overlays(
        web_registry_root,
        trust_contract=web_trust_contract,
        required_digests=required_overlays,
    )
    try:
        control = load_runtime_generation_control(
            generation_root,
            verified_artifacts=verified_artifacts,
            verified_overlays=overlays,
        )
        data_dir = resolve_generation_data_dir(generation_root, control.active)
    except GenerationControlError as exc:
        raise ArtifactError(f"OpenDesign generation control is invalid: {exc}") from exc
    bundle = bundles.get(control.active.runtime_artifact_sha256)
    if bundle is None or bundle.opendesign_version != control.active.od_version:
        raise ArtifactError("Active OpenDesign runtime/data selection is not verified")
    overlay = overlays.get(control.active.web_overlay_sha256)
    if overlay is None:
        raise ArtifactError("Active OpenDesign web overlay is not verified")
    if overlay.upstream_commit != bundle.upstream_commit:
        raise ArtifactError("Active OpenDesign overlay upstream pin does not match the runtime")
    return RuntimeBinding(bundle=bundle, overlay=overlay, data_dir=data_dir, control=control)
