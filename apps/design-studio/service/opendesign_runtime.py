"""Resolve one verified OpenDesign bundle and data generation for launch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opendesign_artifact import ArtifactError, selected_asset, validate_bundle_manifest
from opendesign_artifact_audit import (
    fully_audited_runtime,
    fully_audited_web_overlay,
)
from opendesign_generation_control import (
    load_generation_control,
    load_generation_control_metadata,
    load_migration_journal_metadata,
    load_runtime_activation_journal_metadata,
    load_runtime_generation_control,
    load_web_activation_journal_metadata,
    resolve_generation_data_dir,
)
from opendesign_generation_model import (
    GenerationControl,
    GenerationControlError,
    LaunchSelection,
)
from opendesign_materialization import MaterializedBundle, discover_verified_bundles
from opendesign_artifact_store import OpenDesignArtifactStore, StoredArtifact
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


def materialized_bundle_from_store(stored: StoredArtifact) -> MaterializedBundle:
    return MaterializedBundle(
        stored.artifact_sha256,
        str(stored.receipt["source_file_manifest_sha256"]),
        str(stored.receipt["opendesign_version"]),
        str(stored.receipt["upstream_commit"]),
        stored.content_path,
    )


def verified_overlay_from_store(stored: StoredArtifact) -> VerifiedWebOverlay:
    return VerifiedWebOverlay(
        web_overlay_sha256=stored.artifact_sha256,
        path=stored.content_path,
        static_dir=stored.content_path / "static",
        od_version=str(stored.receipt["opendesign_version"]),
        upstream_commit=str(stored.receipt["upstream_commit"]),
        compatible_runtime_artifact_sha256=frozenset(
            str(value) for value in stored.receipt["compatible_runtime_artifact_sha256"]
        ),
        file_manifest_sha256=str(stored.receipt["source_file_manifest_sha256"]),
        toolchain_sha256="protected-store-receipt",
    )


def protected_activation_inventory(
    *,
    store: OpenDesignArtifactStore,
    generation_root: Path,
) -> tuple[GenerationControl, dict[str, str], dict[str, VerifiedWebOverlay]]:
    """Full-audit every exact store generation needed by activation/recovery."""
    preliminary = load_generation_control_metadata(generation_root)
    selections = activation_inventory_selections(preliminary, generation_root)
    artifacts: dict[str, str] = {}
    overlays: dict[str, VerifiedWebOverlay] = {}
    for selection in selections:
        if selection.runtime_artifact_sha256 not in artifacts:
            runtime = fully_audited_runtime(
                store,
                selection.runtime_artifact_sha256,
                file_manifest_sha256=None,
                opendesign_version=selection.od_version,
                upstream_commit=None,
            )
            artifacts[selection.runtime_artifact_sha256] = str(
                runtime.receipt["opendesign_version"]
            )
        if selection.web_overlay_sha256 not in overlays:
            web = fully_audited_web_overlay(
                store,
                selection.web_overlay_sha256,
                runtime_artifact_sha256=selection.runtime_artifact_sha256,
            )
            overlays[selection.web_overlay_sha256] = verified_overlay_from_store(web)
    control = load_generation_control(
        generation_root,
        verified_artifacts=artifacts,
        verified_overlays=overlays,
    )
    return control, artifacts, overlays


def activation_inventory_selections(
    control: GenerationControl,
    generation_root: Path,
) -> tuple[LaunchSelection, ...]:
    """Return every control or retained-journal selection needed for recovery."""
    selections = [control.active]
    for selection in (
        control.previous_release,
        control.previous_web,
        control.previous_runtime,
    ):
        if selection is not None:
            selections.append(selection)
    if control.migration_id is not None:
        journal = load_migration_journal_metadata(generation_root, control.migration_id)
        selections.extend((journal.source, journal.target))
    if control.web_activation_id is not None:
        journal = load_web_activation_journal_metadata(
            generation_root,
            control.web_activation_id,
        )
        selections.extend((journal.source, journal.target))
    if control.runtime_activation_id is not None:
        journal = load_runtime_activation_journal_metadata(
            generation_root,
            control.runtime_activation_id,
        )
        selections.extend((journal.source, journal.target))
    return tuple(selections)


def resolve_protected_runtime_binding(
    *,
    store_root: Path,
    generation_root: Path,
    manifest: dict[str, Any],
    require_read_only_mount: bool = True,
) -> RuntimeBinding:
    """Resolve only protected receipts for the exact launch selection."""
    validate_bundle_manifest(manifest, require_artifact_digest=True)
    current_asset = selected_asset(manifest, require_artifact_digest=True)
    try:
        preliminary_control = load_generation_control_metadata(generation_root)
    except GenerationControlError as exc:
        raise ArtifactError(f"OpenDesign generation control is invalid: {exc}") from exc
    store = OpenDesignArtifactStore(store_root, require_read_only_mount=require_read_only_mount)
    runtime_digests = {
        current_asset["sha256"],
        preliminary_control.active.runtime_artifact_sha256,
    }
    bundles: dict[str, MaterializedBundle] = {}
    for digest in runtime_digests:
        expected_source_manifest = (
            current_asset["file_manifest_sha256"]
            if digest == current_asset["sha256"]
            else None
        )
        stored = store.fast_runtime(
            digest,
            file_manifest_sha256=(str(expected_source_manifest) if expected_source_manifest is not None else None),
            opendesign_version=(
                manifest["upstream"]["release_version"]
                if digest == current_asset["sha256"]
                else preliminary_control.active.od_version
            ),
            upstream_commit=(manifest["upstream"]["commit"] if digest == current_asset["sha256"] else None),
        )
        bundles[digest] = materialized_bundle_from_store(stored)
    current = bundles[current_asset["sha256"]]
    if current.file_manifest_sha256 != current_asset["file_manifest_sha256"]:
        raise ArtifactError("Pinned OpenDesign file manifest does not match its protected receipt")

    overlay_selections = [preliminary_control.active]
    if preliminary_control.previous_web is not None:
        overlay_selections.append(preliminary_control.previous_web)
    overlays: dict[str, VerifiedWebOverlay] = {}
    for selection in overlay_selections:
        if selection.web_overlay_sha256 in overlays:
            continue
        stored = store.fast_web_overlay(
            selection.web_overlay_sha256,
            runtime_artifact_sha256=selection.runtime_artifact_sha256,
        )
        overlays[selection.web_overlay_sha256] = verified_overlay_from_store(stored)
    try:
        control = load_runtime_generation_control(
            generation_root,
            verified_artifacts={digest: bundle.opendesign_version for digest, bundle in bundles.items()},
            verified_overlays=overlays,
        )
        data_dir = resolve_generation_data_dir(generation_root, control.active)
    except GenerationControlError as exc:
        raise ArtifactError(f"OpenDesign generation control is invalid: {exc}") from exc
    bundle = bundles.get(control.active.runtime_artifact_sha256)
    overlay = overlays.get(control.active.web_overlay_sha256)
    if bundle is None or overlay is None:
        raise ArtifactError("Active OpenDesign runtime binding is unavailable")
    if overlay.upstream_commit != bundle.upstream_commit:
        raise ArtifactError("Active OpenDesign overlay upstream pin does not match the runtime")
    return RuntimeBinding(bundle=bundle, overlay=overlay, data_dir=data_dir, control=control)


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
