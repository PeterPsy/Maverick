"""Bootstrap the first empty OpenDesign generation after materialization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opendesign_artifact import read_bundle_manifest, selected_asset, validate_bundle_manifest
from opendesign_bootstrap import BootstrapError, bootstrap_empty_generation
from opendesign_materialization import discover_verified_bundles


SERVICE_ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--registry-root", type=Path, default=SERVICE_ROOT / "vendor" / "open-design")
    args = parser.parse_args()

    manifest = read_bundle_manifest(SERVICE_ROOT / "opendesign_bundle.json")
    validate_bundle_manifest(manifest, require_artifact_digest=True)
    asset = selected_asset(manifest, require_artifact_digest=True)
    bundles = discover_verified_bundles(args.registry_root.resolve())
    current = bundles.get(asset["sha256"])
    if current is None:
        raise BootstrapError("Pinned OpenDesign artifact is not materialized")
    if (
        current.file_manifest_sha256 != asset["file_manifest_sha256"]
        or current.opendesign_version != manifest["upstream"]["release_version"]
        or current.upstream_commit != manifest["upstream"]["commit"]
    ):
        raise BootstrapError("Pinned OpenDesign artifact metadata does not match its materialization")
    verified = {digest: bundle.opendesign_version for digest, bundle in bundles.items()}
    control, data_dir = bootstrap_empty_generation(
        args.data_root.resolve(),
        artifact_sha256=asset["sha256"],
        opendesign_version=manifest["upstream"]["release_version"],
        verified_artifacts=verified,
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
