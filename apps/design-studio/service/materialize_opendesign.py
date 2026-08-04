"""Verify and atomically materialize the pinned OpenDesign runtime artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opendesign_artifact import (
    ArtifactError,
    platform_key,
    read_bundle_manifest,
)
from opendesign_attestation import verify_artifact_set
from opendesign_materialization import materialize_archive


SERVICE_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = SERVICE_ROOT / "opendesign_bundle.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-directory", default=str(SERVICE_ROOT / "artifacts"))
    parser.add_argument("--registry-root", default=str(SERVICE_ROOT / "vendor" / "open-design"))
    args = parser.parse_args()

    manifest = read_bundle_manifest(MANIFEST_PATH)
    artifact_directory = Path(args.artifact_directory).resolve()
    registry_root = Path(args.registry_root).resolve()
    asset = verify_artifact_set(manifest, artifact_directory)
    result = materialize_archive(
        artifact_directory / asset["file"],
        registry_root,
        expected_artifact_sha256=asset["sha256"],
        expected_file_manifest_sha256=asset["file_manifest_sha256"],
        opendesign_version=manifest["upstream"]["release_version"],
        upstream_commit=manifest["upstream"]["commit"],
    )
    print(
        json.dumps(
            {
                "artifact_sha256": result.artifact_sha256,
                "file_manifest_sha256": result.file_manifest_sha256,
                "opendesign_version": result.opendesign_version,
                "upstream_commit": result.upstream_commit,
                "path": str(result.path),
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
