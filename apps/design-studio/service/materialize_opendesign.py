"""Verify and atomically materialize the pinned OpenDesign runtime artifact."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from opendesign_artifact import ArtifactError, platform_key, selected_asset
from opendesign_artifact_operations import run_artifact_operation
from opendesign_artifact_store import OpenDesignArtifactStore
from opendesign_runtime_sources import RuntimeSourceCatalog


SERVICE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = SERVICE_ROOT.parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-directory", default=str(SERVICE_ROOT / "artifacts"))
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--workspace-id", default="default")
    args = parser.parse_args()

    artifact_directory = Path(args.artifact_directory).resolve()
    expected_source = Path(
        os.environ.get("MAVERICK_OPENDESIGN_ARTIFACT_SOURCE_ROOT", SERVICE_ROOT / "artifacts")
    ).resolve(strict=False)
    if artifact_directory != expected_source:
        raise ArtifactError("artifact directory must match the authority-configured source root")
    result = run_artifact_operation(
        "provision",
        data_root=(
            args.repository_root.resolve()
            / "workspaces"
            / args.workspace_id
            / "data/design-studio"
        ),
        workspace_id=args.workspace_id,
        repository_root=args.repository_root.resolve(),
    )
    print(
        json.dumps(
            {
                **result,
                "platform": platform_key(),
            },
            indent=2,
            sort_keys=True,
        )
    )


def materialize_declared_runtimes(
    store: OpenDesignArtifactStore,
    *,
    artifact_directory: Path,
    catalog: RuntimeSourceCatalog,
) -> list[dict[str, object]]:
    """Publish and independently audit current and rollback into one new store."""
    published: list[dict[str, object]] = []
    for role in ("current", "rollback"):
        source = catalog.by_role[role]
        result = store.publish_runtime(
            source.artifact_directory(artifact_directory),
            manifest=source.manifest,
            artifact_verifier=source.verify_artifact_directory,
        )
        store.full_audit("runtime", result.artifact_sha256)
        asset = selected_asset(source.manifest, require_artifact_digest=True)
        published.append(
            {
                "role": role,
                "artifact_sha256": result.artifact_sha256,
                "file_manifest_sha256": asset["file_manifest_sha256"],
                "opendesign_version": result.receipt["opendesign_version"],
                "upstream_commit": result.receipt["upstream_commit"],
                "store_generation": result.receipt["store_generation"],
                "mount_path": f"/artifacts/opendesign/runtime/{result.artifact_sha256}/content",
            }
        )
    return published


if __name__ == "__main__":
    try:
        main()
    except ArtifactError as error:
        raise SystemExit(str(error)) from error
