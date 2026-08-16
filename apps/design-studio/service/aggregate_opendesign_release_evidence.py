#!/usr/bin/env python3
"""Aggregate independent UI and migration evidence into the 14-scenario release gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from benchmark_opendesign_change_to_live import (
    BENCHMARK_FILE,
    validate_change_to_live_benchmark,
)
from opendesign_artifact import read_bundle_manifest, selected_asset, sha256_file
from opendesign_supply_chain import read_json
from opendesign_web_overlay import discover_verified_overlays

SHA256 = re.compile(r"^[0-9a-f]{64}$")
CANONICAL_UI_SCENARIOS = (
    "login_open",
    "create_project_ui",
    "storage_import",
    "runtime_start",
    "incremental_sse",
    "generated_preview",
    "cancel_long_run",
    "storage_export",
    "restart_reload",
    "deep_link",
    "workspace_isolation",
    "forbidden_routes",
    "secret_boundary",
)


def aggregate(
    ui: dict,
    migration: dict,
    benchmark: dict,
    *,
    release_provenance: dict,
) -> dict:
    scenarios = ui.get("scenarios")
    identifiers = [scenario.get("id") for scenario in scenarios] if isinstance(scenarios, list) else []
    if (
        ui.get("profile") != "release"
        or ui.get("status") != "passed"
        or not isinstance(scenarios, list)
        or len(scenarios) != 13
        or len(set(identifiers)) != len(identifiers)
        or set(identifiers) != set(CANONICAL_UI_SCENARIOS)
        or any(
            not isinstance(scenario, dict) or scenario.get("status") != "passed"
            for scenario in scenarios
        )
        or ui.get("two_workspace_isolation", True) is not True
        or ui.get("restart_covered", True) is not True
    ):
        raise ValueError("release UI evidence must contain the 13 unique canonical passed scenarios")
    if migration.get("ok") is not True or migration.get("workspace_data_migrated") is not False:
        raise ValueError("migration/rollback smoke evidence did not pass independently")
    source_generation_preserved = (
        isinstance(migration.get("source_tree_sha256_before"), str)
        and SHA256.fullmatch(str(migration["source_tree_sha256_before"])) is not None
        and migration.get("source_tree_sha256_before") == migration.get("source_tree_sha256_after")
        and migration.get("source_generation_preserved", True) is True
    )
    real_rollback = migration.get("real_rollback")
    forward_generation_preserved = (
        isinstance(real_rollback, dict)
        and real_rollback.get("forward_generation_preserved") is True
        and migration.get("forward_generation_preserved", True) is True
    )
    if not source_generation_preserved or not forward_generation_preserved:
        raise ValueError("migration/rollback preservation proofs must all be true")
    opendesign = ui.get("opendesign") if isinstance(ui.get("opendesign"), dict) else {}
    runtime_digest = opendesign.get("runtime_artifact_sha256")
    web_digest = opendesign.get("web_overlay_sha256")
    if not isinstance(runtime_digest, str) or not SHA256.fullmatch(runtime_digest):
        raise ValueError("release UI evidence runtime digest is invalid")
    if not isinstance(web_digest, str) or not SHA256.fullmatch(web_digest):
        raise ValueError("release UI evidence web overlay digest is invalid")
    provenance_summary = _validate_release_provenance(
        release_provenance,
        runtime_digest=runtime_digest,
        web_digest=web_digest,
    )
    benchmark_summary = validate_change_to_live_benchmark(
        benchmark,
        expected_runtime_digest=runtime_digest,
        expected_baseline_web_digest=web_digest,
        expected_patch_sha256=sha256_file(Path(__file__).resolve().parents[3] / BENCHMARK_FILE),
    )
    if benchmark_summary["target_met"] is not True:
        raise ValueError("change-to-live benchmark exceeded the release target")
    aggregated = [dict(item) for item in scenarios]
    aggregated.append(
        {
            "id": "upgrade_rollback",
            "name": "Upgrade and rollback the real artifact with fixture data",
            "status": "passed",
            "proof": {
                "migration_smoke": True,
                "source_generation_preserved": source_generation_preserved,
                "forward_generation_preserved": forward_generation_preserved,
            },
        }
    )
    identifiers = [item.get("id") for item in aggregated]
    if len(aggregated) != 14 or len(set(identifiers)) != 14:
        raise ValueError("aggregated release scenario inventory is incomplete or duplicated")
    return {
        "schema_version": "4",
        "gate": "design-studio-opendesign-release",
        "status": "passed",
        "opendesign": opendesign,
        "release_provenance": provenance_summary,
        "scenario_count": 14,
        "two_workspace_isolation": "workspace_isolation" in identifiers,
        "restart_covered": "restart_reload" in identifiers,
        "rollback_gate_separate": True,
        "change_to_live_benchmark": benchmark_summary,
        "scenarios": aggregated,
        "sources": {
            "ui_gate": ui.get("gate"),
            "migration_gate": "design-studio-migration-rollback-smoke",
            "benchmark_gate": benchmark.get("gate"),
        },
    }


def verified_release_provenance(
    service_root: Path,
    *,
    runtime_digest: str,
    web_digest: str,
) -> dict:
    """Load one signed overlay and bind its build inputs to the current reviewed contracts."""
    bundle = read_bundle_manifest(service_root / "opendesign_bundle.json")
    asset = selected_asset(bundle, require_artifact_digest=True)
    supply_chain = read_json(service_root / "opendesign_supply_chain_0_16_1.json")
    series = read_json(service_root / bundle["fallback_build"]["patch_series"])
    web_patches = {
        str(entry.get("component")): str(entry.get("sha256"))
        for entry in series.get("patches", [])
        if isinstance(entry, dict) and entry.get("component") in {"web-build", "web-react"}
    }
    if set(web_patches) != {"web-build", "web-react"}:
        raise ValueError("current patch series web component inventory is incomplete")
    overlays = discover_verified_overlays(
        service_root / "vendor/open-design-web",
        trust_contract=service_root / "opendesign_web_trust.json",
        required_digests={web_digest},
    )
    overlay = overlays[web_digest]
    signed_manifest = read_json(overlay.path / "manifest.json")
    compatibility = signed_manifest.get("compatibility")
    inputs = signed_manifest.get("inputs")
    if not isinstance(compatibility, dict) or not isinstance(inputs, dict):
        raise ValueError("signed web overlay provenance is incomplete")
    expected_lockfile = supply_chain.get("source_tree", {}).get("pnpm_lock_sha256")
    return {
        "signed_overlay_manifest": True,
        "web_overlay_sha256": signed_manifest.get("web_overlay_sha256"),
        "runtime_artifact_sha256": runtime_digest,
        "runtime_compatibility": compatibility.get("runtime_artifact_sha256"),
        "expected_runtime_artifact_sha256": asset.get("sha256"),
        "upstream_commit": compatibility.get("upstream_commit"),
        "expected_upstream_commit": bundle.get("upstream", {}).get("commit"),
        "lockfile_sha256": inputs.get("lockfile_sha256"),
        "expected_lockfile_sha256": expected_lockfile,
        "web_patch_sha256": {
            "web-build": inputs.get("web_build_patch_sha256"),
            "web-react": inputs.get("web_react_patch_sha256"),
        },
        "expected_web_patch_sha256": web_patches,
    }


def _validate_release_provenance(
    provenance: dict,
    *,
    runtime_digest: str,
    web_digest: str,
) -> dict:
    if not isinstance(provenance, dict) or provenance.get("signed_overlay_manifest") is not True:
        raise ValueError("release overlay manifest was not signature-verified")
    compatibility = provenance.get("runtime_compatibility")
    observed_patches = provenance.get("web_patch_sha256")
    expected_patches = provenance.get("expected_web_patch_sha256")
    if (
        provenance.get("web_overlay_sha256") != web_digest
        or provenance.get("runtime_artifact_sha256") != runtime_digest
        or provenance.get("expected_runtime_artifact_sha256") != runtime_digest
        or not isinstance(compatibility, list)
        or runtime_digest not in compatibility
        or provenance.get("upstream_commit") != provenance.get("expected_upstream_commit")
        or provenance.get("lockfile_sha256") != provenance.get("expected_lockfile_sha256")
        or not isinstance(observed_patches, dict)
        or set(observed_patches) != {"web-build", "web-react"}
        or observed_patches != expected_patches
        or any(not isinstance(value, str) or not SHA256.fullmatch(value) for value in observed_patches.values())
    ):
        raise ValueError("signed web overlay provenance does not match the current patch series")
    return {
        "signed_overlay_manifest": True,
        "upstream_commit": provenance["upstream_commit"],
        "lockfile_sha256": provenance["lockfile_sha256"],
        "web_patch_sha256": observed_patches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ui", type=Path, required=True)
    parser.add_argument("--migration", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    ui = json.loads(arguments.ui.read_text(encoding="utf-8"))
    migration = json.loads(arguments.migration.read_text(encoding="utf-8"))
    benchmark = json.loads(arguments.benchmark.read_text(encoding="utf-8"))
    opendesign = ui.get("opendesign") if isinstance(ui.get("opendesign"), dict) else {}
    provenance = verified_release_provenance(
        Path(__file__).resolve().parent,
        runtime_digest=str(opendesign.get("runtime_artifact_sha256") or ""),
        web_digest=str(opendesign.get("web_overlay_sha256") or ""),
    )
    result = aggregate(ui, migration, benchmark, release_provenance=provenance)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
