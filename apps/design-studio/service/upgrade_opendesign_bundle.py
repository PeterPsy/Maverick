#!/usr/bin/env python3
"""Atomically upgrade one explicitly controlled OpenDesign data root."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opendesign_artifact import read_bundle_manifest, selected_asset, validate_bundle_manifest
from opendesign_generation_model import GenerationTriple
from opendesign_migration import upgrade_controlled_copy
from opendesign_migration_oci_runtime import OciMigrationRuntime


SERVICE_ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--registry-root", type=Path, required=True)
    parser.add_argument("--migration-id", required=True)
    parser.add_argument("--target-generation", required=True)
    parser.add_argument("--minimum-free-bytes", type=int, default=64 * 1024 * 1024)
    args = parser.parse_args()

    manifest = read_bundle_manifest(SERVICE_ROOT / "opendesign_bundle.json")
    validate_bundle_manifest(manifest, require_artifact_digest=True)
    asset = selected_asset(manifest, require_artifact_digest=True)
    target = GenerationTriple(
        bundle_artifact_sha256=str(asset["sha256"]),
        od_version=str(manifest["upstream"]["release_version"]),
        data_generation=args.target_generation,
    )
    runtime = OciMigrationRuntime(
        args.data_root.resolve(),
        args.registry_root.resolve(),
        manifest,
    )
    try:
        outcome = upgrade_controlled_copy(
            args.data_root.resolve(),
            target=target,
            migration_id=args.migration_id,
            verified_artifacts=runtime.verified_artifacts,
            runtime=runtime,
            minimum_free_bytes=args.minimum_free_bytes,
        )
        evidence = runtime.evidence()
    finally:
        runtime.stop_sidecar()
    print(
        json.dumps(
            {
                "schema_version": "1",
                "migration_id": outcome.migration_id,
                "active": outcome.control.active.to_dict(),
                "previous": outcome.control.previous.to_dict() if outcome.control.previous else None,
                "project_count": outcome.project_count,
                "evidence": evidence,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
