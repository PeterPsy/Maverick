"""Verify and atomically materialize the pinned OpenDesign runtime artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.apps.artifact_mounts import create_artifact_namespace
from opendesign_artifact import ArtifactError, platform_key, read_bundle_manifest
from opendesign_artifact_store import OpenDesignArtifactStore


SERVICE_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = SERVICE_ROOT / "opendesign_bundle.json"
REPOSITORY_ROOT = SERVICE_ROOT.parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-directory", default=str(SERVICE_ROOT / "artifacts"))
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    args = parser.parse_args()

    manifest = read_bundle_manifest(MANIFEST_PATH)
    artifact_directory = Path(args.artifact_directory).resolve()
    namespace = create_artifact_namespace(
        repository_root=args.repository_root.resolve(),
        app_id="design-studio",
        artifact_id="opendesign",
    )
    store = OpenDesignArtifactStore(namespace)
    result = store.publish_runtime(artifact_directory, manifest=manifest)
    print(
        json.dumps(
            {
                "artifact_sha256": result.artifact_sha256,
                "file_manifest_sha256": result.receipt["source_file_manifest_sha256"],
                "opendesign_version": result.receipt["opendesign_version"],
                "upstream_commit": result.receipt["upstream_commit"],
                "store_generation": result.receipt["store_generation"],
                "mount_path": f"/artifacts/opendesign/runtime/{result.artifact_sha256}/content",
                "platform": platform_key(),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except ArtifactError as error:
        raise SystemExit(str(error)) from error
