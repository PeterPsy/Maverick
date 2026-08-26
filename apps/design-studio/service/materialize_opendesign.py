"""Verify and atomically materialize the pinned OpenDesign runtime artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.apps.artifact_mounts import create_artifact_namespace
from opendesign_artifact import ArtifactError, platform_key, selected_asset
from opendesign_artifact_store import OpenDesignArtifactStore
from opendesign_runtime_sources import RuntimeSourceCatalog, load_runtime_source_catalog


SERVICE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = SERVICE_ROOT.parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-directory", default=str(SERVICE_ROOT / "artifacts"))
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    args = parser.parse_args()

    artifact_directory = Path(args.artifact_directory).resolve()
    namespace = create_artifact_namespace(
        repository_root=args.repository_root.resolve(),
        app_id="design-studio",
        artifact_id="opendesign",
    )
    store = OpenDesignArtifactStore(namespace)
    catalog = load_runtime_source_catalog()
    published = materialize_declared_runtimes(
        store,
        artifact_directory=artifact_directory,
        catalog=catalog,
    )
    current = next(item for item in published if item["role"] == "current")
    print(
        json.dumps(
            {
                "artifact_sha256": current["artifact_sha256"],
                "file_manifest_sha256": current["file_manifest_sha256"],
                "opendesign_version": current["opendesign_version"],
                "upstream_commit": current["upstream_commit"],
                "store_generation": current["store_generation"],
                "mount_path": current["mount_path"],
                "platform": platform_key(),
                "runtime_sources": published,
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
