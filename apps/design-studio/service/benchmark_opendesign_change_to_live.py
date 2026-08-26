#!/usr/bin/env python3
"""Measure a real synthetic React patch from changed bytes through live remount readiness."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import Any
import uuid

from core.apps.artifact_mounts import create_artifact_namespace
from opendesign_artifact import read_bundle_manifest, sha256_file, write_canonical_json
from opendesign_artifact_audit import fully_audited_web_overlay
from opendesign_artifact_store import OpenDesignArtifactStore
from opendesign_dev_apply import _cache_root, _repo_root, _required_path, _restart_sidecars, _work_parent
from opendesign_runtime import protected_activation_inventory, verified_overlay_from_store
from opendesign_source import apply_patch_series, export_source
from opendesign_web_activation import activate_web_overlay, recover_web_activation
from opendesign_web_builder import build_dev_overlay


BENCHMARK_FILE = "apps/design-studio/service/patches/0003-maverick-web-react.patch"
BENCHMARK_CEILING_SECONDS = 180.0
_BASELINE_PATCH_LINE = "+  --mav-bg: #070708;"
_BASELINE_SOURCE_LINE = "  --mav-bg: #070708;"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ChangeToLiveBenchmarkError(RuntimeError):
    """Raised when the benchmark cannot prove a real, restored change-to-live cycle."""


def run_change_to_live_benchmark(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    repo_root = _repo_root(arguments)
    service_root = repo_root / "apps/design-studio/service"
    repository = _required_path(arguments, "source_repository")
    signing_key = _required_path(arguments, "web_signing_key")
    cache_root = _cache_root(arguments, repo_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    work_parent = _work_parent(arguments)
    work_parent.mkdir(parents=True, exist_ok=True)
    registry_root = cache_root / "benchmark-build-registry"
    registry_root.mkdir(parents=True, exist_ok=True)
    manifest = read_bundle_manifest(service_root / "opendesign_bundle.json")
    generation_root = Path(str(payload.get("data_root") or "")) / "opendesign"
    if not generation_root.is_dir() or generation_root.is_symlink():
        raise ChangeToLiveBenchmarkError("benchmark requires a real Design Studio data root")

    namespace = create_artifact_namespace(
        repository_root=repo_root,
        app_id="design-studio",
        artifact_id="opendesign",
    )
    store = OpenDesignArtifactStore(namespace)
    _control, verified_artifacts, overlays = protected_activation_inventory(
        store=store,
        generation_root=generation_root,
    )
    recover_web_activation(
        generation_root,
        verified_artifacts=verified_artifacts,
        verified_overlays=overlays,
        restart_sidecars=lambda: _restart_sidecars(arguments, repo_root=repo_root),
    )
    initial, verified_artifacts, overlays = protected_activation_inventory(
        store=store,
        generation_root=generation_root,
    )
    benchmark_id = uuid.uuid4().hex[:16]

    with tempfile.TemporaryDirectory(prefix="od-change-to-live-", dir=work_parent) as temporary:
        root = Path(temporary)
        session_dependency_root = root / "session-dependencies"
        warmup_started = time.monotonic()
        warmup = build_dev_overlay(
            repository,
            manifest=manifest,
            service_root=service_root,
            cache_root=cache_root,
            registry_root=registry_root,
            signing_key=signing_key,
            trust_contract=service_root / "opendesign_web_trust.json",
            work_parent=work_parent,
            runtime_session_id=str(payload.get("runtime_session_id") or "") or None,
            session_dependency_root=session_dependency_root,
        )
        warmup_duration = round(time.monotonic() - warmup_started, 6)
        warmup_matches_active = warmup.overlay.web_overlay_sha256 == initial.active.web_overlay_sha256

        benchmark_service = _prepare_benchmark_service(
            repository,
            service_root=service_root,
            manifest=manifest,
            root=root,
        )
        changed_started = time.monotonic()
        mutation_started = time.monotonic()
        change = _mutate_benchmark_patch(
            benchmark_service,
            prepared_source=root / "prepared-source",
            nonce=benchmark_id,
        )
        mutation_duration = round(time.monotonic() - mutation_started, 6)

        build_started = time.monotonic()
        candidate = build_dev_overlay(
            repository,
            manifest=manifest,
            service_root=benchmark_service,
            cache_root=cache_root,
            registry_root=registry_root,
            signing_key=signing_key,
            trust_contract=benchmark_service / "opendesign_web_trust.json",
            work_parent=work_parent,
            runtime_session_id=str(payload.get("runtime_session_id") or "") or None,
            session_dependency_root=session_dependency_root,
        )
        build_duration = round(time.monotonic() - build_started, 6)
        candidate_metric = candidate.metrics[0]
        if candidate_metric.source_build_cache_hit:
            raise ChangeToLiveBenchmarkError("benchmark reused a compiled source/build cache result")
        if candidate.keys.source_build == warmup.keys.source_build:
            raise ChangeToLiveBenchmarkError("benchmark patch did not change the source/build cache digest")
        if candidate.overlay.web_overlay_sha256 == warmup.overlay.web_overlay_sha256:
            raise ChangeToLiveBenchmarkError("benchmark patch did not change the compiled web overlay")
        if candidate.overlay.web_overlay_sha256 == initial.active.web_overlay_sha256:
            raise ChangeToLiveBenchmarkError("benchmark patch did not produce a new web overlay")

        store_publish_started = time.monotonic()
        stored_candidate = store.publish_web_overlay(
            candidate.overlay.path,
            web_overlay_sha256=candidate.overlay.web_overlay_sha256,
            trust_contract=benchmark_service / "opendesign_web_trust.json",
        )
        store_publish_duration = round(time.monotonic() - store_publish_started, 6)
        current, verified_artifacts, overlays = protected_activation_inventory(
            store=store,
            generation_root=generation_root,
        )
        stored_candidate = fully_audited_web_overlay(
            store,
            stored_candidate.artifact_sha256,
            runtime_artifact_sha256=current.active.runtime_artifact_sha256,
            trust_contract=benchmark_service / "opendesign_web_trust.json",
        )
        overlays[stored_candidate.artifact_sha256] = verified_overlay_from_store(stored_candidate)
        outcome = None
        restored = None
        activation_started = time.monotonic()
        try:
            outcome = activate_web_overlay(
                generation_root,
                target_web_overlay_sha256=candidate.overlay.web_overlay_sha256,
                web_activation_id=f"web_benchmark_{benchmark_id}",
                verified_artifacts=verified_artifacts,
                verified_overlays=overlays,
                restart_sidecars=lambda: _restart_sidecars(arguments, repo_root=repo_root),
            )
            activation_duration = round(time.monotonic() - activation_started, 6)
            duration = round(time.monotonic() - changed_started, 6)
            if not outcome.activated or outcome.rolled_back:
                raise ChangeToLiveBenchmarkError("benchmark candidate did not become the ready active overlay")
            if outcome.readiness.get("browser_remount_event_emitted") is not True:
                raise ChangeToLiveBenchmarkError("benchmark restart did not publish the browser remount event")
        finally:
            current, verified_artifacts, retained_overlays = protected_activation_inventory(
                store=store,
                generation_root=generation_root,
            )
            overlays.update(retained_overlays)
            restoration_started = time.monotonic()
            if current.active != initial.active:
                restored = activate_web_overlay(
                    generation_root,
                    target_web_overlay_sha256=initial.active.web_overlay_sha256,
                    web_activation_id=f"web_benchmark_restore_{benchmark_id}",
                    verified_artifacts=verified_artifacts,
                    verified_overlays=overlays,
                    restart_sidecars=lambda: _restart_sidecars(arguments, repo_root=repo_root),
                )
            elif current != initial:
                recover_web_activation(
                    generation_root,
                    verified_artifacts=verified_artifacts,
                    verified_overlays=overlays,
                    restart_sidecars=lambda: _restart_sidecars(arguments, repo_root=repo_root),
                )
            restoration_duration = round(time.monotonic() - restoration_started, 6)
        if outcome is None or restored is None:
            raise ChangeToLiveBenchmarkError("benchmark candidate was not activated and restored")
        if not restored.activated or restored.control.active != initial.active:
            raise ChangeToLiveBenchmarkError("benchmark did not restore the complete initial selection")
        if restored.readiness.get("browser_remount_event_emitted") is not True:
            raise ChangeToLiveBenchmarkError("benchmark restoration did not publish the browser remount event")

    evidence = {
        "schema_version": "1",
        "gate": "design-studio-opendesign-change-to-live",
        "status": "passed",
        "executed_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "benchmark_id": benchmark_id,
        "change": change,
        "cache_keys": {
            "baseline_source_build": warmup.keys.source_build,
            "candidate_source_build": candidate.keys.source_build,
        },
        "compiled_baseline": {
            "web_overlay_sha256": warmup.overlay.web_overlay_sha256,
            "matches_active_selection": warmup_matches_active,
        },
        "cache": asdict(candidate_metric),
        "selection": {
            "before": initial.active.to_dict(),
            "candidate": outcome.control.active.to_dict(),
            "restored": restored.control.active.to_dict(),
        },
        "phases": {
            "warmup_excluded_seconds": warmup_duration,
            "mutation_seconds": mutation_duration,
            "build_seconds": build_duration,
            "protected_store_publish_seconds": store_publish_duration,
            "activation_restart_readiness_seconds": activation_duration,
            "change_to_live_seconds": duration,
            "restoration_seconds": restoration_duration,
        },
        "activation": {
            "ready": outcome.readiness.get("ready") is True,
            "service_count": outcome.readiness.get("service_count"),
            "browser_remount_event_emitted": True,
        },
        "restoration": {
            "ready": restored.readiness.get("ready") is True,
            "browser_remount_event_emitted": True,
        },
        "target_ceiling_seconds": BENCHMARK_CEILING_SECONDS,
    }
    validate_change_to_live_benchmark(
        evidence,
        expected_runtime_digest=initial.active.runtime_artifact_sha256,
        expected_baseline_web_digest=initial.active.web_overlay_sha256,
        expected_patch_sha256=change["before_sha256"],
    )
    return evidence


def validate_change_to_live_benchmark(
    evidence: object,
    *,
    expected_runtime_digest: str,
    expected_baseline_web_digest: str,
    expected_patch_sha256: str,
) -> dict[str, object]:
    if not isinstance(evidence, dict):
        raise ValueError("change-to-live benchmark evidence must be an object")
    if (
        evidence.get("schema_version") != "1"
        or evidence.get("gate") != "design-studio-opendesign-change-to-live"
        or evidence.get("status") != "passed"
    ):
        raise ValueError("change-to-live benchmark gate did not pass")
    change = _mapping(evidence.get("change"), "benchmark change")
    if change.get("file") != BENCHMARK_FILE:
        raise ValueError("benchmark did not mutate the reviewed React patch")
    before_sha = change.get("before_sha256")
    after_sha = change.get("after_sha256")
    if before_sha != expected_patch_sha256 or not _digest(after_sha) or before_sha == after_sha:
        raise ValueError("benchmark patch digests do not prove changed bytes")
    keys = _mapping(evidence.get("cache_keys"), "benchmark cache keys")
    if not _digest(keys.get("baseline_source_build")) or not _digest(keys.get("candidate_source_build")):
        raise ValueError("benchmark source/build keys are invalid")
    if keys["baseline_source_build"] == keys["candidate_source_build"]:
        raise ValueError("benchmark source/build digest did not change")
    cache = _mapping(evidence.get("cache"), "benchmark cache")
    if cache.get("source_build_cache_hit") is not False:
        raise ValueError("benchmark did not compile the changed React source")
    if cache.get("dependency_cache_hit") is not True or cache.get("install_skipped") is not True:
        raise ValueError("benchmark is not a warm dependency-cache measurement")
    if cache.get("workspace_build_cache_hit") is not True:
        raise ValueError("benchmark did not reuse verified invariant workspace outputs")
    compiled_baseline = _mapping(evidence.get("compiled_baseline"), "compiled baseline")
    compiled_baseline_digest = compiled_baseline.get("web_overlay_sha256")
    if not _digest(compiled_baseline_digest):
        raise ValueError("benchmark compiled baseline digest is invalid")
    if not isinstance(compiled_baseline.get("matches_active_selection"), bool):
        raise ValueError("benchmark compiled baseline selection relationship is missing")
    selection = _mapping(evidence.get("selection"), "benchmark selection")
    before = _selection(selection.get("before"), "before")
    candidate = _selection(selection.get("candidate"), "candidate")
    restored = _selection(selection.get("restored"), "restored")
    if before["runtime_artifact_sha256"] != expected_runtime_digest:
        raise ValueError("benchmark runtime digest differs from release evidence")
    if before["web_overlay_sha256"] != expected_baseline_web_digest:
        raise ValueError("benchmark baseline overlay differs from release evidence")
    if candidate["runtime_artifact_sha256"] != expected_runtime_digest:
        raise ValueError("benchmark changed the runtime artifact")
    if candidate["web_overlay_sha256"] == expected_baseline_web_digest:
        raise ValueError("benchmark did not activate a new overlay")
    if candidate["web_overlay_sha256"] == compiled_baseline_digest:
        raise ValueError("benchmark React mutation did not change the compiled baseline overlay")
    if restored != before:
        raise ValueError("benchmark did not restore the complete launch selection")
    activation = _mapping(evidence.get("activation"), "benchmark activation")
    restoration = _mapping(evidence.get("restoration"), "benchmark restoration")
    if activation.get("ready") is not True or activation.get("browser_remount_event_emitted") is not True:
        raise ValueError("benchmark candidate readiness/remount proof is incomplete")
    if restoration.get("ready") is not True or restoration.get("browser_remount_event_emitted") is not True:
        raise ValueError("benchmark restoration readiness/remount proof is incomplete")
    phases = _mapping(evidence.get("phases"), "benchmark phases")
    duration = _positive_number(phases.get("change_to_live_seconds"), "change_to_live_seconds")
    build = _positive_number(phases.get("build_seconds"), "build_seconds")
    activation_seconds = _positive_number(
        phases.get("activation_restart_readiness_seconds"),
        "activation_restart_readiness_seconds",
    )
    store_publish = _positive_number(
        phases.get("protected_store_publish_seconds"),
        "protected_store_publish_seconds",
    )
    mutation = _positive_number(phases.get("mutation_seconds"), "mutation_seconds")
    if duration + 0.001 < build + store_publish + activation_seconds + mutation:
        raise ValueError("benchmark phase timings are internally inconsistent")
    if evidence.get("target_ceiling_seconds") != BENCHMARK_CEILING_SECONDS:
        raise ValueError("benchmark target ceiling is not canonical")
    return {
        "status": "passed",
        "change_to_live_seconds": duration,
        "target_met": duration <= BENCHMARK_CEILING_SECONDS,
        "source_build_cache_hit": False,
        "baseline_web_overlay_sha256": before["web_overlay_sha256"],
        "candidate_web_overlay_sha256": candidate["web_overlay_sha256"],
        "browser_remount_event_emitted": True,
        "protected_store_publish_seconds": store_publish,
    }


def _prepare_benchmark_service(
    repository: Path,
    *,
    service_root: Path,
    manifest: dict[str, Any],
    root: Path,
) -> Path:
    benchmark_service = root / "service"
    benchmark_service.mkdir()
    shutil.copytree(service_root / "patches", benchmark_service / "patches")
    shutil.copytree(service_root / "trust", benchmark_service / "trust")
    shutil.copy2(service_root / "opendesign_web_trust.json", benchmark_service)
    prepared_source = root / "prepared-source"
    export_source(repository, prepared_source, manifest)
    apply_patch_series(
        prepared_source,
        service_root,
        manifest,
        components={"web-build", "web-react"},
    )
    return benchmark_service


def _mutate_benchmark_patch(service_root: Path, *, prepared_source: Path, nonce: str) -> dict[str, str]:
    color = f"#{hashlib.sha256(nonce.encode('ascii')).hexdigest()[:6]}"
    if color == "#070708":
        color = "#070709"
    patch_path = service_root / "patches/0003-maverick-web-react.patch"
    before_sha = sha256_file(patch_path)
    patch_text = patch_path.read_text(encoding="utf-8")
    if patch_text.count(_BASELINE_PATCH_LINE) != 1:
        raise ChangeToLiveBenchmarkError("reviewed React patch benchmark anchor is missing or ambiguous")
    patch_path.write_text(
        patch_text.replace(_BASELINE_PATCH_LINE, f"+  --mav-bg: {color};"),
        encoding="utf-8",
    )
    source_path = prepared_source / "apps/web/src/index.css"
    source_text = source_path.read_text(encoding="utf-8")
    if source_text.count(_BASELINE_SOURCE_LINE) != 1:
        raise ChangeToLiveBenchmarkError("prepared React/CSS benchmark anchor is missing or ambiguous")
    source_path.write_text(
        source_text.replace(_BASELINE_SOURCE_LINE, f"  --mav-bg: {color};"),
        encoding="utf-8",
    )
    series_path = service_root / "patches/series.json"
    series = json.loads(series_path.read_text(encoding="utf-8"))
    web_react = next(
        (entry for entry in series.get("patches", []) if entry.get("component") == "web-react"),
        None,
    )
    if not isinstance(web_react, dict):
        raise ChangeToLiveBenchmarkError("web-react patch inventory is missing")
    file_entry = next(
        (entry for entry in web_react.get("files", []) if entry.get("path") == "apps/web/src/index.css"),
        None,
    )
    if not isinstance(file_entry, dict):
        raise ChangeToLiveBenchmarkError("web-react CSS post-image inventory is missing")
    web_react["sha256"] = sha256_file(patch_path)
    file_entry["post_sha256"] = sha256_file(source_path)
    write_canonical_json(series_path, series)
    return {
        "file": BENCHMARK_FILE,
        "before_sha256": before_sha,
        "after_sha256": sha256_file(patch_path),
    }


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _digest(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _selection(value: object, label: str) -> dict[str, Any]:
    selection = _mapping(value, f"benchmark {label} selection")
    required = {
        "runtime_artifact_sha256",
        "web_overlay_sha256",
        "od_version",
        "data_generation",
    }
    if set(selection) != required or not _digest(selection.get("runtime_artifact_sha256")) or not _digest(
        selection.get("web_overlay_sha256")
    ):
        raise ValueError(f"benchmark {label} selection is invalid")
    return selection


def _positive_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
        raise ValueError(f"benchmark {label} must be positive")
    return float(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--source-repository", type=Path, required=True)
    parser.add_argument("--web-signing-key", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--work-parent", type=Path)
    parser.add_argument("--workspace-id", default="default")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    raw_arguments = {
        "repo_root": str(arguments.repo_root),
        "source_repository": str(arguments.source_repository),
        "web_signing_key": str(arguments.web_signing_key),
        "cache_root": str(arguments.cache_root),
        "workspace_id": arguments.workspace_id,
    }
    if arguments.work_parent is not None:
        raw_arguments["work_parent"] = str(arguments.work_parent)
    result = run_change_to_live_benchmark(
        {"data_root": str(arguments.data_root)},
        raw_arguments,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    write_canonical_json(arguments.output, result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
