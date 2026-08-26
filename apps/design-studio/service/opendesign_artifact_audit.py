"""Mandatory full-audit gates for OpenDesign lifecycle transitions."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from opendesign_artifact_store import (
    ArtifactStoreError,
    OpenDesignArtifactStore,
    StoredArtifact,
)


DEFAULT_WEB_TRUST_CONTRACT = Path(__file__).resolve().with_name("opendesign_web_trust.json")


def fully_audited_runtime(
    store: OpenDesignArtifactStore,
    digest: str,
    *,
    file_manifest_sha256: str | None,
    opendesign_version: str,
    upstream_commit: str | None,
    max_workers: int | None = None,
) -> StoredArtifact:
    """Full-audit one runtime, then enforce its exact release binding."""
    store.full_audit("runtime", digest, max_workers=max_workers)
    return store.fast_runtime(
        digest,
        file_manifest_sha256=file_manifest_sha256,
        opendesign_version=opendesign_version,
        upstream_commit=upstream_commit,
    )


def fully_audited_web_overlay(
    store: OpenDesignArtifactStore,
    digest: str,
    *,
    runtime_artifact_sha256: str,
    trust_contract: Path = DEFAULT_WEB_TRUST_CONTRACT,
    max_workers: int | None = None,
) -> StoredArtifact:
    """Full-audit one signed overlay, then enforce runtime compatibility."""
    store.full_audit(
        "web",
        digest,
        trust_contract=trust_contract,
        max_workers=max_workers,
    )
    return store.fast_web_overlay(
        digest,
        runtime_artifact_sha256=runtime_artifact_sha256,
    )


def fully_audited_web_overlay_for_any_runtime(
    store: OpenDesignArtifactStore,
    digest: str,
    *,
    runtime_artifact_sha256: Iterable[str],
    trust_contract: Path = DEFAULT_WEB_TRUST_CONTRACT,
    max_workers: int | None = None,
) -> StoredArtifact:
    """Audit an overlay once and require one exact retained runtime binding."""
    store.full_audit(
        "web",
        digest,
        trust_contract=trust_contract,
        max_workers=max_workers,
    )
    last_error: ArtifactStoreError | None = None
    seen: set[str] = set()
    for runtime_digest in runtime_artifact_sha256:
        if runtime_digest in seen:
            continue
        seen.add(runtime_digest)
        try:
            return store.fast_web_overlay(
                digest,
                runtime_artifact_sha256=runtime_digest,
            )
        except ArtifactStoreError as error:
            last_error = error
    if last_error is not None:
        raise last_error
    raise ArtifactStoreError(
        "runtime_binding_invalid",
        "artifact_full_verify",
        "OpenDesign web overlay has no retained runtime binding",
    )
