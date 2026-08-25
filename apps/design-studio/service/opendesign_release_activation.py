"""Governed same-data activation of one protected OpenDesign runtime/web pair."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from opendesign_artifact import selected_asset
from opendesign_artifact_store import ArtifactStoreError, OpenDesignArtifactStore, StoredArtifact
from opendesign_generation_control import load_generation_control_metadata
from opendesign_generation_model import GenerationControl, LaunchSelection
from opendesign_runtime_activation import (
    RuntimeActivationOutcome,
    activate_runtime_binding,
    retry_runtime_activation_candidate,
    runtime_activation_recovery_state,
)
from opendesign_web_overlay import VerifiedWebOverlay


Restart = Callable[[], Mapping[str, object]]


@dataclass(frozen=True)
class ReleaseActivationResult:
    outcome: RuntimeActivationOutcome
    retired_unavailable_runtime_references: tuple[str, ...]


def activate_protected_release(
    generation_root: Path,
    *,
    store: OpenDesignArtifactStore,
    manifest: dict[str, Any],
    target_web_overlay_sha256: str,
    restart_sidecars: Restart,
) -> ReleaseActivationResult:
    """Atomically cut over without migrating data and keep the prior active pair as rollback."""
    control = load_generation_control_metadata(generation_root)
    target_runtime_sha256 = str(selected_asset(manifest, require_artifact_digest=True)["sha256"])
    target_runtime = store.fast_runtime(
        target_runtime_sha256,
        file_manifest_sha256=str(
            selected_asset(manifest, require_artifact_digest=True)["file_manifest_sha256"]
        ),
        opendesign_version=str(manifest["upstream"]["release_version"]),
        upstream_commit=str(manifest["upstream"]["commit"]),
    )
    target_web = store.fast_web_overlay(
        target_web_overlay_sha256,
        runtime_artifact_sha256=target_runtime_sha256,
    )

    artifacts: dict[str, str] = {target_runtime_sha256: str(target_runtime.receipt["opendesign_version"])}
    overlays: dict[str, VerifiedWebOverlay] = {
        target_web_overlay_sha256: _verified_overlay(target_web)
    }
    retired: list[str] = []
    for selection in _control_selections(control):
        try:
            runtime = store.fast_runtime(
                selection.runtime_artifact_sha256,
                file_manifest_sha256=None,
                opendesign_version=selection.od_version,
                upstream_commit=None,
            )
        except ArtifactStoreError:
            if selection == control.active:
                raise ArtifactStoreError(
                    "artifact_missing",
                    "activation",
                    "The active rollback source is not protected",
                )
            # Legacy controls may name an already-retired ancestor. It is admitted only
            # as non-executable metadata so the activation can replace it atomically.
            artifacts[selection.runtime_artifact_sha256] = selection.od_version
            retired.append(selection.runtime_artifact_sha256)
        else:
            artifacts[selection.runtime_artifact_sha256] = str(runtime.receipt["opendesign_version"])
        if selection.web_overlay_sha256 not in overlays:
            web = store.fast_web_overlay(
                selection.web_overlay_sha256,
                runtime_artifact_sha256=selection.runtime_artifact_sha256,
            )
            overlays[selection.web_overlay_sha256] = _verified_overlay(web)

    source_generation = control.active.data_generation
    recovery_state = runtime_activation_recovery_state(
        generation_root,
        verified_artifacts=artifacts,
        verified_overlays=overlays,
    )
    pending_target = control.previous_runtime
    if (
        recovery_state == "rollback_restart_pending"
        and control.runtime_activation_id is not None
        and pending_target is not None
        and pending_target.runtime_artifact_sha256 == target_runtime_sha256
        and pending_target.web_overlay_sha256 == target_web_overlay_sha256
    ):
        outcome = retry_runtime_activation_candidate(
            generation_root,
            runtime_activation_id=control.runtime_activation_id,
            verified_artifacts=artifacts,
            verified_overlays=overlays,
            restart_sidecars=restart_sidecars,
        )
    else:
        outcome = activate_runtime_binding(
            generation_root,
            target_runtime_artifact_sha256=target_runtime_sha256,
            target_web_overlay_sha256=target_web_overlay_sha256,
            runtime_activation_id=f"runtime_release_{uuid4().hex[:16]}",
            verified_artifacts=artifacts,
            verified_overlays=overlays,
            restart_sidecars=restart_sidecars,
        )
    if outcome.rolled_back or not outcome.activated:
        raise ArtifactStoreError(
            "activation_incomplete",
            "activation",
            "The protected release failed readiness and was rolled back",
        )
    if outcome.control.active.data_generation != source_generation:
        raise ArtifactStoreError(
            "runtime_binding_invalid",
            "activation",
            "Runtime activation unexpectedly changed the data generation",
        )
    return ReleaseActivationResult(outcome, tuple(sorted(set(retired))))


def _control_selections(control: GenerationControl) -> tuple[LaunchSelection, ...]:
    candidates = (
        control.active,
        control.previous_release,
        control.previous_web,
        control.previous_runtime,
    )
    unique: dict[tuple[str, str, str], LaunchSelection] = {}
    for selection in candidates:
        if selection is not None:
            key = (
                selection.runtime_artifact_sha256,
                selection.web_overlay_sha256,
                selection.data_generation,
            )
            unique[key] = selection
    return tuple(unique.values())


def _verified_overlay(stored: StoredArtifact) -> VerifiedWebOverlay:
    receipt = stored.receipt
    return VerifiedWebOverlay(
        web_overlay_sha256=stored.artifact_sha256,
        path=stored.content_path,
        static_dir=stored.content_path / "static",
        od_version=str(receipt["opendesign_version"]),
        upstream_commit=str(receipt["upstream_commit"]),
        compatible_runtime_artifact_sha256=frozenset(
            str(item) for item in receipt["compatible_runtime_artifact_sha256"]
        ),
        file_manifest_sha256=str(receipt["source_file_manifest_sha256"]),
        toolchain_sha256="protected-store-receipt",
    )
