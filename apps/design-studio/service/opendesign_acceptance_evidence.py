#!/usr/bin/env python3
"""Content-bind OpenDesign production evidence and independently verify launch SLOs."""

from __future__ import annotations

import argparse
from datetime import datetime
import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable


SOURCE_ATTESTATION_ALGORITHM = "sha256-maverick-product-inputs-v1"
SOURCE_ROOTS = (
    "core",
    "apps/base-shell",
    "apps/storage",
    "apps/design-studio",
    "scripts/check-node-runtime.mjs",
)
EVIDENCE_EXCLUDES = (
    "apps/design-studio/service/*acceptance_*.json",
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40,64}$")
UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
SUMMARY_FIELDS = ("count", "p50_ms", "p95_ms", "p99_ms", "max_ms")


def build_source_attestation(repository_root: Path) -> dict[str, object]:
    """Hash the exact working-tree inputs used by the real product gate."""
    root = repository_root.resolve()
    paths = _source_paths(root)
    digest = hashlib.sha256()
    for relative in paths:
        absolute = root / relative
        if absolute.is_symlink():
            kind = b"symlink"
            content = os.readlink(absolute).encode("utf-8")
        elif absolute.is_file():
            kind = b"file"
            content = absolute.read_bytes()
        else:
            raise ValueError(f"Acceptance source input is missing: {relative}")
        digest.update(kind)
        digest.update(b"\0")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).hexdigest().encode("ascii"))
        digest.update(b"\n")
    revision = _git(root, "rev-parse", "HEAD").strip()
    if REVISION.fullmatch(revision) is None:
        raise ValueError("Acceptance source revision is invalid")
    return {
        "algorithm": SOURCE_ATTESTATION_ALGORITHM,
        "sha256": digest.hexdigest(),
        "file_count": len(paths),
        "revision": revision,
        "working_tree_clean": not _relevant_dirty_paths(root),
    }


def validate_source_attestation(value: object, *, repository_root: Path) -> dict[str, object]:
    """Reject evidence generated from any older or locally modified product input."""
    if not isinstance(value, dict):
        raise ValueError("Product evidence source attestation is missing")
    observed = build_source_attestation(repository_root)
    if (
        value.get("algorithm") != SOURCE_ATTESTATION_ALGORITHM
        or not isinstance(value.get("sha256"), str)
        or SHA256.fullmatch(str(value["sha256"])) is None
        or value.get("sha256") != observed["sha256"]
        or value.get("file_count") != observed["file_count"]
        or not isinstance(value.get("revision"), str)
        or REVISION.fullmatch(str(value["revision"])) is None
        or not _revision_is_ancestor(repository_root.resolve(), str(value["revision"]))
        or value.get("working_tree_clean") is not True
    ):
        raise ValueError("Product evidence is stale or was generated from modified source inputs")
    return dict(value)


def validate_execution(value: object, *, repository_root: Path) -> dict[str, object]:
    """Validate execution identity, chronology, canonical command, and source binding."""
    if not isinstance(value, dict) or value.get("schema_version") != "1":
        raise ValueError("Product evidence execution metadata is missing")
    started = _timestamp(value.get("started_at"), "started_at")
    completed = _timestamp(value.get("completed_at"), "completed_at")
    duration_ms = _number(value.get("duration_ms"), "duration_ms")
    elapsed_ms = (completed - started).total_seconds() * 1000
    command = value.get("required_command")
    if (
        completed < started
        or duration_ms <= 0
        or abs(duration_ms - elapsed_ms) > 2_000
        or not isinstance(value.get("run_id"), str)
        or UUID.fullmatch(str(value["run_id"])) is None
        or value.get("runner") != "apps/design-studio/tests/opendesign_product.e2e.mjs"
        or value.get("profile") != "release"
        or command
        != [
            "npm",
            "run",
            "test:e2e",
            "--prefix",
            "apps/design-studio",
            "--",
            "--evidence-output",
            "apps/design-studio/service/opendesign_product_acceptance_0_16_1.json",
        ]
    ):
        raise ValueError("Product evidence execution metadata is invalid")
    validate_source_attestation(value.get("source"), repository_root=repository_root)
    return dict(value)


def validate_migration_execution(
    value: object,
    *,
    repository_root: Path,
    parent_product_run_id: str,
) -> dict[str, object]:
    """Bind the real migration/rollback smoke to the same current-source product run."""
    if not isinstance(value, dict) or value.get("schema_version") != "1":
        raise ValueError("Migration evidence execution metadata is missing")
    started = _timestamp(value.get("started_at"), "started_at")
    completed = _timestamp(value.get("completed_at"), "completed_at")
    duration_ms = _number(value.get("duration_ms"), "duration_ms")
    run_id = value.get("run_id")
    command = value.get("required_command")
    if (
        completed < started
        or duration_ms <= 0
        or abs(duration_ms - (completed - started).total_seconds() * 1000) > 2_000
        or not isinstance(run_id, str)
        or UUID.fullmatch(run_id) is None
        or not isinstance(parent_product_run_id, str)
        or UUID.fullmatch(parent_product_run_id) is None
        or value.get("parent_product_run_id") != parent_product_run_id
        or value.get("runner")
        != "apps/design-studio/service/smoke_opendesign_migration.py"
        or command
        != [
            "python3",
            "apps/design-studio/service/smoke_opendesign_migration.py",
            "--evidence-output",
            "apps/design-studio/service/opendesign_migration_acceptance_0_16_1.json",
            "--parent-product-run-id",
            parent_product_run_id,
        ]
    ):
        raise ValueError("Migration evidence execution metadata is invalid")
    validate_source_attestation(value.get("source"), repository_root=repository_root)
    return dict(value)


def validate_launch_performance(value: object) -> dict[str, Any]:
    """Recompute every release SLO from raw samples instead of trusting passed flags."""
    if not isinstance(value, dict) or value.get("schema_version") != "2":
        raise ValueError("Release launch performance evidence is missing or invalid")
    warm_ticket = _validated_sampled_summary(value.get("warm_browser_ticket"), count=30, label="warm ticket")
    warm_interface = _validated_sampled_summary(value.get("warm_interface"), count=30, label="warm interface")
    full_remount = _validated_sampled_summary(
        warm_interface.get("full_wrapper_remount"), count=30, label="full wrapper remount"
    )
    if warm_interface.get("measurement_scope") != "wrapper_navigation_to_transactional_ui_ready":
        raise ValueError("Warm interface measurement scope is invalid")
    if any(
        abs(_number(warm_interface[field], field) - _number(full_remount[field], field)) > 0.001
        for field in SUMMARY_FIELDS
    ) or warm_interface.get("samples_ms") != full_remount.get("samples_ms"):
        raise ValueError("Warm interface SLO excludes part of the wrapper remount")
    samples = value.get("samples")
    if not isinstance(samples, list) or len(samples) != 10:
        raise ValueError("Core restart samples are missing")
    if [sample.get("iteration") for sample in samples if isinstance(sample, dict)] != list(range(1, 11)):
        raise ValueError("Core restart sample inventory is invalid")
    cold_values = [_sample_number(sample, "cold_maverick_ready_ms") for sample in samples]
    cold_interface_values = [
        _sample_number(sample, "interface_after_transactional_ready_ms") for sample in samples
    ]
    cold = _validated_derived_summary(
        value.get("cold_maverick_ready"), cold_values, label="cold transactional readiness"
    )
    cold_interface = _validated_derived_summary(
        value.get("cold_interface"), cold_interface_values, label="cold interface"
    )
    if cold_interface.get("measurement_scope") != "prewarmed_shell_action_to_transactional_ui_ready":
        raise ValueError("Cold interface measurement scope is invalid")
    resources = value.get("resources")
    if not isinstance(resources, dict):
        raise ValueError("Release resource evidence is missing")
    for sample in samples:
        if not isinstance(sample, dict) or not isinstance(sample.get("resources"), dict):
            raise ValueError("Core restart resource sample is invalid")
        _number(sample["resources"].get("rss_kib"), "rss_kib")
        _number(sample["resources"].get("process_count"), "process_count")
    if (
        value.get("targets_met") is not True
        or value.get("core_restart_count") != 10
        or warm_ticket.get("same_sidecar_instance") is not True
        or _number(warm_ticket.get("p95_ms"), "warm ticket p95") > 300
        or _number(warm_ticket.get("p99_ms"), "warm ticket p99") > 750
        or _number(warm_interface.get("p95_ms"), "warm interface p95") > 1_500
        or _number(warm_interface.get("p99_ms"), "warm interface p99") > 2_500
        or _number(cold.get("p95_ms"), "cold readiness p95") > 4_000
        or _number(cold.get("max_ms"), "cold readiness max") > 8_000
        or _number(cold_interface.get("p95_ms"), "cold interface p95") > 1_500
        or _number(cold_interface.get("p99_ms"), "cold interface p99") > 2_500
        or not 0 < _number(resources.get("rss_kib_max"), "rss_kib_max") < math.inf
        or not 0 < _number(resources.get("process_count_max"), "process_count_max") < math.inf
    ):
        raise ValueError("Release launch performance SLOs did not pass")
    return dict(value)


def _source_paths(root: Path) -> list[str]:
    output = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *SOURCE_ROOTS],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    paths = sorted(
        {
            os.fsdecode(item)
            for item in output.split(b"\0")
            if item and not _excluded(os.fsdecode(item))
        }
    )
    if not paths:
        raise ValueError("Acceptance source inventory is empty")
    return paths


def _relevant_dirty_paths(root: Path) -> list[str]:
    output = _git(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        *SOURCE_ROOTS,
    )
    paths: list[str] = []
    for line in output.splitlines():
        candidate = line[3:]
        if " -> " in candidate:
            candidate = candidate.rsplit(" -> ", 1)[1]
        candidate = candidate.strip('"')
        if candidate and not _excluded(candidate):
            paths.append(candidate)
    return paths


def _excluded(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in EVIDENCE_EXCLUDES)


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def _revision_is_ancestor(root: Path, revision: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", revision, "HEAD"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def _validated_sampled_summary(value: object, *, count: int, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("samples_ms"), list):
        raise ValueError(f"{label} raw samples are missing")
    samples = [_number(item, f"{label} sample") for item in value["samples_ms"]]
    if len(samples) != count or any(item < 0 for item in samples):
        raise ValueError(f"{label} raw samples are invalid")
    _assert_summary(value, _distribution(samples), label=label)
    return value


def _validated_derived_summary(value: object, samples: list[float], *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} summary is missing")
    _assert_summary(value, _distribution(samples), label=label)
    return value


def _assert_summary(observed: dict[str, Any], expected: dict[str, float | int], *, label: str) -> None:
    for field in SUMMARY_FIELDS:
        actual = _number(observed.get(field), f"{label} {field}")
        if abs(actual - float(expected[field])) > 0.001:
            raise ValueError(f"{label} summary does not match its raw samples")


def _distribution(samples: Iterable[float]) -> dict[str, float | int]:
    values = sorted(float(item) for item in samples)
    if not values:
        raise ValueError("Performance sample set is empty")

    def percentile(value: int) -> float:
        return values[max(0, math.ceil((value / 100) * len(values)) - 1)]

    return {
        "count": len(values),
        "p50_ms": percentile(50),
        "p95_ms": percentile(95),
        "p99_ms": percentile(99),
        "max_ms": values[-1],
    }


def _sample_number(sample: object, field: str) -> float:
    if not isinstance(sample, dict):
        raise ValueError("Core restart sample is invalid")
    return _number(sample.get(field), field)


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} must be a UTC timestamp")
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise ValueError(f"{label} must be a UTC timestamp") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("source-attestation",))
    parser.add_argument("--repository-root", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.operation == "source-attestation":
        print(json.dumps(build_source_attestation(arguments.repository_root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
