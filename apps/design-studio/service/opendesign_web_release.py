"""Build a reproducible overlay or resolve the canonical verified release overlay."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from opendesign_artifact import read_bundle_manifest, selected_asset
from opendesign_process import activate_runtime_attachment, signal_guard
from opendesign_web_builder import build_release_overlay
from opendesign_web_overlay import VerifiedWebOverlay, discover_verified_overlays


SERVICE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = SERVICE_ROOT.parents[2]


def canonical_web_overlay(
    registry_root: Path,
    *,
    trust_contract: Path,
    runtime_artifact_sha256: str,
    od_version: str,
    upstream_commit: str,
) -> tuple[VerifiedWebOverlay, dict[str, VerifiedWebOverlay]]:
    overlays = discover_verified_overlays(registry_root, trust_contract=trust_contract)
    compatible = [
        overlay
        for overlay in overlays.values()
        if overlay.od_version == od_version
        and overlay.upstream_commit == upstream_commit
        and runtime_artifact_sha256 in overlay.compatible_runtime_artifact_sha256
    ]
    if len(compatible) != 1:
        raise RuntimeError("OpenDesign bootstrap requires exactly one canonical compatible web overlay")
    return compatible[0], overlays


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repository", type=Path, required=True)
    parser.add_argument("--signing-key", type=Path, required=True)
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=REPOSITORY_ROOT / "tmp/opendesign-web-cache",
    )
    parser.add_argument(
        "--registry-root",
        type=Path,
        default=SERVICE_ROOT / "vendor/open-design-web",
    )
    parser.add_argument("--work-parent", type=Path)
    parser.add_argument(
        "--compatible-runtime-artifact-sha256",
        action="append",
        default=[],
    )
    parser.add_argument("--allow-operator-detached", action="store_true")
    arguments = parser.parse_args()
    try:
        manifest = read_bundle_manifest(SERVICE_ROOT / "opendesign_bundle.json")
        runtime_digest = str(selected_asset(manifest)["sha256"])
        compatible = frozenset(
            {runtime_digest, *arguments.compatible_runtime_artifact_sha256}
        )
        cache_root = arguments.cache_root
        work_parent = arguments.work_parent or cache_root / "work"
        for directory in (cache_root, work_parent, arguments.registry_root):
            directory.mkdir(parents=True, exist_ok=True)
        with signal_guard():
            runtime_session_id = activate_runtime_attachment(
                allow_operator_detached=arguments.allow_operator_detached
            )
            result = build_release_overlay(
                arguments.source_repository,
                manifest=manifest,
                service_root=SERVICE_ROOT,
                cache_root=cache_root,
                registry_root=arguments.registry_root,
                signing_key=arguments.signing_key,
                trust_contract=SERVICE_ROOT / "opendesign_web_trust.json",
                work_parent=work_parent,
                runtime_session_id=runtime_session_id,
                compatible_runtime_artifact_sha256=compatible,
            )
    except Exception as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "opendesign_web_release_failed",
                    "error_code": type(error).__name__,
                },
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "web_overlay_sha256": result.overlay.web_overlay_sha256,
                "compatible_runtime_artifact_sha256": sorted(
                    result.overlay.compatible_runtime_artifact_sha256
                ),
                "derivations": result.derivations,
                "reproducible": result.reproducible,
                "materialization_cache_hit": result.cache_hit,
                "cache_keys": asdict(result.keys),
                "metrics": [asdict(metric) for metric in result.metrics],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
