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
from opendesign_artifact import sha256_file

SHA256 = re.compile(r"^[0-9a-f]{64}$")


def aggregate(ui: dict, migration: dict, benchmark: dict) -> dict:
    scenarios = ui.get("scenarios")
    if (
        ui.get("profile") != "release"
        or ui.get("status") != "passed"
        or not isinstance(scenarios, list)
        or len(scenarios) != 13
        or any(
            not isinstance(scenario, dict) or scenario.get("status") != "passed"
            for scenario in scenarios
        )
    ):
        raise ValueError("release UI evidence must contain exactly 13 passed scenarios")
    if migration.get("ok") is not True or migration.get("workspace_data_migrated") is not False:
        raise ValueError("migration/rollback smoke evidence did not pass independently")
    opendesign = ui.get("opendesign") if isinstance(ui.get("opendesign"), dict) else {}
    runtime_digest = opendesign.get("runtime_artifact_sha256")
    web_digest = opendesign.get("web_overlay_sha256")
    if not isinstance(runtime_digest, str) or not SHA256.fullmatch(runtime_digest):
        raise ValueError("release UI evidence runtime digest is invalid")
    if not isinstance(web_digest, str) or not SHA256.fullmatch(web_digest):
        raise ValueError("release UI evidence web overlay digest is invalid")
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
                "source_generation_preserved": (
                    migration.get("source_tree_sha256_before")
                    == migration.get("source_tree_sha256_after")
                ),
                "forward_generation_preserved": bool(
                    migration.get("real_rollback", {}).get("forward_generation_preserved")
                ),
            },
        }
    )
    identifiers = [item.get("id") for item in aggregated]
    if len(aggregated) != 14 or len(set(identifiers)) != 14:
        raise ValueError("aggregated release scenario inventory is incomplete or duplicated")
    return {
        "schema_version": "3",
        "gate": "design-studio-opendesign-release",
        "status": "passed",
        "opendesign": opendesign,
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
    result = aggregate(ui, migration, benchmark)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
