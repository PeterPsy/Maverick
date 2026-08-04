"""Resolve one verified OpenDesign bundle and data generation for launch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opendesign_artifact import ArtifactError, selected_asset, validate_bundle_manifest
from opendesign_generation_control import load_generation_control, resolve_generation_data_dir
from opendesign_generation_model import (
    GenerationControl,
    GenerationControlError,
    GenerationTriple,
)
from opendesign_materialization import MaterializedBundle, discover_verified_bundles


@dataclass(frozen=True)
class RuntimeBinding:
    bundle: MaterializedBundle
    data_dir: Path
    control: GenerationControl

    @property
    def active(self) -> GenerationTriple:
        return self.control.active


def resolve_runtime_binding(
    *,
    registry_root: Path,
    generation_root: Path,
    manifest: dict[str, Any],
) -> RuntimeBinding:
    """Select only the exact active triple from strict control metadata."""
    validate_bundle_manifest(manifest, require_artifact_digest=True)
    current_asset = selected_asset(manifest, require_artifact_digest=True)
    bundles = discover_verified_bundles(registry_root)
    current_digest = current_asset["sha256"]
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
    try:
        control = load_generation_control(
            generation_root,
            verified_artifacts=verified_artifacts,
        )
        data_dir = resolve_generation_data_dir(generation_root, control.active)
    except GenerationControlError as exc:
        raise ArtifactError(f"OpenDesign generation control is invalid: {exc}") from exc
    bundle = bundles.get(control.active.bundle_artifact_sha256)
    if bundle is None or bundle.opendesign_version != control.active.od_version:
        raise ArtifactError("Active OpenDesign bundle/data triple is not verified")
    return RuntimeBinding(bundle=bundle, data_dir=data_dir, control=control)
