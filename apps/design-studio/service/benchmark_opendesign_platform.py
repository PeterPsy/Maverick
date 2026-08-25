#!/usr/bin/env python3
"""Record protected-store fast-path, audit, and atomic-repair performance."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import math
import os
from pathlib import Path
import resource
import shutil
import stat
import tempfile
import time
from typing import Any
from uuid import uuid4

from opendesign_artifact import read_bundle_manifest, selected_asset, write_canonical_json
from opendesign_artifact_operations import _clear_invalid_marker, _known_invalid_identity, _mark_invalid
from opendesign_artifact_store import ArtifactStoreError, OpenDesignArtifactStore


SERVICE_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SERVICE_ROOT / "opendesign_platform_benchmark_0_16_1.json"
FAST_SAMPLES = 30
FAST_P95_TARGET_MS = 50.0
REPAIR_TARGET_MS = 30_000.0


class PlatformBenchmarkError(RuntimeError):
    """Raised when the platform benchmark cannot exercise a real artifact."""


def run_platform_benchmark(*, work_parent: Path) -> dict[str, Any]:
    """Exercise a real signed runtime in a disposable platform-owned namespace."""
    manifest = read_bundle_manifest(SERVICE_ROOT / "opendesign_bundle.json")
    asset = selected_asset(manifest, require_artifact_digest=True)
    artifact_digest = str(asset["sha256"])
    source_manifest_digest = str(asset["file_manifest_sha256"])
    version = str(manifest["upstream"]["release_version"])
    upstream_commit = str(manifest["upstream"]["commit"])
    work_parent = work_parent.resolve(strict=True)
    started_usage = resource.getrusage(resource.RUSAGE_SELF)
    temporary = Path(tempfile.mkdtemp(prefix="opendesign-platform-benchmark-", dir=work_parent))
    try:
        namespace = _create_namespace(temporary / "store")
        store = OpenDesignArtifactStore(namespace)
        data_root = temporary / "data"
        data_root.mkdir(mode=0o700)
        sentinel = data_root / "sentinel.json"
        write_canonical_json(sentinel, {"schema_version": "1", "value": "untouched"})
        sentinel_before = sentinel.read_bytes()

        initial_started = time.monotonic()
        published = store.publish_runtime(SERVICE_ROOT / "artifacts", manifest=manifest)
        initial_materialization_ms = _elapsed_ms(initial_started)
        if published.artifact_sha256 != artifact_digest:
            raise PlatformBenchmarkError("The signed runtime publication selected an unexpected digest")

        read_bytes_before = _process_read_bytes()
        fast_samples: list[float] = []
        for _index in range(FAST_SAMPLES):
            sample_started = time.monotonic()
            store.fast_runtime(
                artifact_digest,
                file_manifest_sha256=source_manifest_digest,
                opendesign_version=version,
                upstream_commit=upstream_commit,
            )
            fast_samples.append(_elapsed_ms(sample_started))
        read_bytes_after = _process_read_bytes()

        audit_started = time.monotonic()
        store.full_audit("runtime", artifact_digest)
        full_audit_ms = _elapsed_ms(audit_started)

        mutated_relative = _mutate_one_regular_mode(published.package_path, published.content_path)
        detection_started = time.monotonic()
        try:
            store.full_audit("runtime", artifact_digest)
        except ArtifactStoreError as error:
            if error.code != "artifact_integrity_mismatch":
                raise
        else:
            raise PlatformBenchmarkError("The real full audit accepted a mutated runtime")
        detection_ms = _elapsed_ms(detection_started)
        _mark_invalid(store, kind="runtime", digest=artifact_digest)
        invalid_identity = _known_invalid_identity(store, kind="runtime", digest=artifact_digest)
        if invalid_identity is None:
            raise PlatformBenchmarkError("The full-audit repair handoff was not persisted")
        try:
            store.fast_runtime(
                artifact_digest,
                file_manifest_sha256=source_manifest_digest,
                opendesign_version=version,
                upstream_commit=upstream_commit,
            )
        except ArtifactStoreError as error:
            if error.code != "artifact_integrity_mismatch":
                raise
        else:
            raise PlatformBenchmarkError("The fast path did not fail closed after a rejected audit")

        repair_started = time.monotonic()
        repaired = store.publish_runtime(
            SERVICE_ROOT / "artifacts",
            manifest=manifest,
            repair=True,
            invalid_package_identity=invalid_identity,
        )
        repair_ms = _elapsed_ms(repair_started)
        _clear_invalid_marker(store, kind="runtime", digest=artifact_digest)
        post_repair_started = time.monotonic()
        store.full_audit("runtime", artifact_digest)
        post_repair_audit_ms = _elapsed_ms(post_repair_started)
        quarantine = tuple((store.root / "quarantine" / "runtime").iterdir())
        if repaired.artifact_sha256 != artifact_digest or len(quarantine) != 1:
            raise PlatformBenchmarkError("Atomic repair did not publish one exact replacement and quarantine")
        if sentinel.read_bytes() != sentinel_before:
            raise PlatformBenchmarkError("Artifact repair modified the isolated application data sentinel")

        fast_p95 = _percentile(fast_samples, 95)
        fast_target_met = fast_p95 <= FAST_P95_TARGET_MS
        repair_target_met = repair_ms <= REPAIR_TARGET_MS
        usage = resource.getrusage(resource.RUSAGE_SELF)
        evidence = {
            "schema_version": "1",
            "gate": "design-studio-opendesign-platform-performance",
            "status": "passed" if fast_target_met and repair_target_met else "failed",
            "executed_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
            "runtime_artifact_sha256": artifact_digest,
            "store_generation": store.store_generation,
            "fast_runtime_binding": {
                "samples": len(fast_samples),
                "p50_ms": _percentile(fast_samples, 50),
                "p95_ms": fast_p95,
                "p99_ms": _percentile(fast_samples, 99),
                "max_ms": round(max(fast_samples), 3),
                "target_p95_ms": FAST_P95_TARGET_MS,
                "target_met": fast_target_met,
                "full_content_hashing": False,
                "kernel_read_bytes": max(0, read_bytes_after - read_bytes_before),
            },
            "full_audit": {
                "duration_ms": round(full_audit_ms, 3),
                "outside_launch_critical_path": True,
            },
            "repair": {
                "initial_materialization_ms": round(initial_materialization_ms, 3),
                "detection_full_audit_ms": round(detection_ms, 3),
                "repair_ms": round(repair_ms, 3),
                "post_repair_full_audit_ms": round(post_repair_audit_ms, 3),
                "repair_timer_starts_after_audited_invalid_handoff": True,
                "timer_includes_provenance_extract_verify_receipt_fsync_quarantine_rename": True,
                "target_ms": REPAIR_TARGET_MS,
                "target_met": repair_target_met,
                "cache_state": "uncontrolled_real_archive_cache",
                "mutation": {"kind": "mode_drift", "relative_path": mutated_relative},
                "quarantine_count": len(quarantine),
                "post_repair_full_audit": True,
                "data_root_touched": False,
            },
            "process": {
                "pid_count": 1,
                "max_rss_kib": int(usage.ru_maxrss),
                "user_cpu_seconds": round(max(0.0, usage.ru_utime - started_usage.ru_utime), 6),
                "system_cpu_seconds": round(max(0.0, usage.ru_stime - started_usage.ru_stime), 6),
            },
        }
        return evidence
    finally:
        _make_tree_removable(temporary)
        shutil.rmtree(temporary, ignore_errors=True)


def _create_namespace(root: Path) -> Path:
    namespace = root / "design-studio" / "opendesign"
    namespace.mkdir(parents=True, mode=0o750)
    for path in (root, root / "design-studio", namespace):
        path.chmod(0o750)
    marker = namespace / ".maverick-artifact-namespace.json"
    write_canonical_json(
        marker,
        {
            "schema_version": "1",
            "app_id": "design-studio",
            "artifact_id": "opendesign",
            "store_generation": uuid4().hex,
            "owner_uid": os.geteuid(),
            "owner_gid": os.getegid(),
        },
    )
    marker.chmod(0o640)
    return namespace


def _mutate_one_regular_mode(package: Path, content: Path) -> str:
    manifest = json.loads((package / "manifest-v2.json").read_text(encoding="utf-8"))
    for entry in manifest.get("entries", []):
        if isinstance(entry, dict) and entry.get("kind") == "file" and entry.get("mode") == "0644":
            relative = str(entry["path"])
            target = content / relative
            target.chmod(0o664)
            return relative
    raise PlatformBenchmarkError("The real runtime does not contain a canonical 0644 audit target")


def _process_read_bytes() -> int:
    try:
        lines = Path("/proc/self/io").read_text(encoding="ascii").splitlines()
        value = next(line.split(":", 1)[1].strip() for line in lines if line.startswith("read_bytes:"))
        return int(value)
    except (OSError, UnicodeDecodeError, StopIteration, ValueError):
        return 0


def _percentile(values: list[float], percentile: int) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile / 100 * len(ordered)) - 1))
    return round(ordered[index], 3)


def _elapsed_ms(started: float) -> float:
    return (time.monotonic() - started) * 1000


def _make_tree_removable(root: Path) -> None:
    if not root.exists() or root.is_symlink():
        return
    for current_root, directories, filenames in os.walk(root, topdown=False, followlinks=False):
        current = Path(current_root)
        for name in (*filenames, *directories):
            path = current / name
            if not path.is_symlink():
                try:
                    path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)
                except OSError:
                    pass
        try:
            current.chmod(stat.S_IMODE(current.stat().st_mode) | stat.S_IWUSR | stat.S_IXUSR)
        except OSError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-parent", type=Path, default=Path("/var/tmp"))
    arguments = parser.parse_args()
    evidence = run_platform_benchmark(work_parent=arguments.work_parent)
    write_canonical_json(arguments.output, evidence)
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    if evidence["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
