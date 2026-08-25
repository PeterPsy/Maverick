"""Bootstrap the first empty OpenDesign generation after materialization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.apps.artifact_mounts import platform_artifact_store_root
from opendesign_artifact import read_bundle_manifest, selected_asset, validate_bundle_manifest
from opendesign_artifact_store import OpenDesignArtifactStore
from opendesign_bootstrap import BootstrapError, bootstrap_empty_generation
from opendesign_runtime import verified_overlay_from_store


SERVICE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = SERVICE_ROOT.parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--web-overlay-sha256", required=True)
    args = parser.parse_args()

    manifest = read_bundle_manifest(SERVICE_ROOT / "opendesign_bundle.json")
    validate_bundle_manifest(manifest, require_artifact_digest=True)
    asset = selected_asset(manifest, require_artifact_digest=True)
    store = OpenDesignArtifactStore(
        platform_artifact_store_root(args.repository_root.resolve())
        / "design-studio"
        / "opendesign"
    )
    current = store.fast_runtime(
        str(asset["sha256"]),
        file_manifest_sha256=str(asset["file_manifest_sha256"]),
        opendesign_version=str(manifest["upstream"]["release_version"]),
        upstream_commit=str(manifest["upstream"]["commit"]),
    )
    web = store.fast_web_overlay(
        args.web_overlay_sha256,
        runtime_artifact_sha256=current.artifact_sha256,
    )
    verified = {current.artifact_sha256: str(current.receipt["opendesign_version"])}
    overlays = {web.artifact_sha256: verified_overlay_from_store(web)}
    control, data_dir = bootstrap_empty_generation(
        args.data_root.resolve(),
        artifact_sha256=asset["sha256"],
        web_overlay_sha256=args.web_overlay_sha256,
        opendesign_version=manifest["upstream"]["release_version"],
        verified_artifacts=verified,
        verified_overlays=overlays,
    )
    print(
        json.dumps(
            {"active": control.active.to_dict(), "data_dir": str(data_dir)},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except BootstrapError as error:
        raise SystemExit(str(error)) from error
