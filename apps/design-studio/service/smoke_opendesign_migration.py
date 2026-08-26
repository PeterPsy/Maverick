#!/usr/bin/env python3
"""Migrate a marked 0.10.1 fixture through the real pinned 0.16.1 daemon."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import time
from uuid import UUID, uuid4

SERVICE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = SERVICE_ROOT.parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from core.apps.artifact_mounts import platform_artifact_store_root
from opendesign_artifact import (
    read_bundle_manifest,
    selected_asset,
    validate_bundle_manifest,
    write_canonical_json,
)
from opendesign_artifact_store import OpenDesignArtifactStore
from opendesign_acceptance_evidence import build_source_attestation
from opendesign_generation_control import load_generation_control, write_generation_control
from opendesign_generation_model import GenerationControl, LaunchSelection
from opendesign_migration import migrate_controlled_copy, rollback_controlled_copy
from opendesign_migration_files import mark_controlled_copy, tree_sha256
from opendesign_migration_oci_runtime import OciMigrationRuntime
from opendesign_runtime import materialized_bundle_from_store, verified_overlay_from_store


STORE_ROOT = platform_artifact_store_root(REPOSITORY_ROOT) / "design-studio" / "opendesign"
WEB_TRUST_CONTRACT = SERVICE_ROOT / "opendesign_web_trust.json"
OLD_FIXTURE_DIGEST = "0101" * 16
OLD_FIXTURE_WEB_DIGEST = "0102" * 16
LEGACY_ID = "design_0123456789ab"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-output", type=Path)
    parser.add_argument("--parent-product-run-id")
    arguments = parser.parse_args()
    started_at = datetime.now(tz=UTC)
    started = time.monotonic()
    parent_product_run_id = str(arguments.parent_product_run_id or "")
    if arguments.evidence_output is not None:
        try:
            parsed_parent_run_id = UUID(parent_product_run_id)
        except ValueError as error:
            parser.error("--parent-product-run-id must be supplied with --evidence-output")
        if parsed_parent_run_id.version != 4:
            parser.error("--parent-product-run-id must be a UUIDv4")
    manifest = read_bundle_manifest(SERVICE_ROOT / "opendesign_bundle.json")
    validate_bundle_manifest(manifest, require_artifact_digest=True)
    asset = selected_asset(manifest, require_artifact_digest=True)
    store = OpenDesignArtifactStore(STORE_ROOT)
    stored_runtime = store.fast_runtime(
        str(asset["sha256"]),
        file_manifest_sha256=str(asset["file_manifest_sha256"]),
        opendesign_version=str(manifest["upstream"]["release_version"]),
        upstream_commit=str(manifest["upstream"]["commit"]),
    )
    release = json.loads((SERVICE_ROOT / "opendesign_release_selection.json").read_text(encoding="utf-8"))
    stored_overlay = store.fast_web_overlay(
        str(release["active_web_overlay_sha256"]),
        runtime_artifact_sha256=stored_runtime.artifact_sha256,
    )
    target_bundle = materialized_bundle_from_store(stored_runtime)
    target_overlay = verified_overlay_from_store(stored_overlay)

    with TemporaryDirectory(prefix="maverick-od-migration-smoke-") as temporary:
        app_data = Path(temporary) / "design-studio"
        root = app_data / "opendesign"
        for path in (
            root,
            root / "instances",
            root / "backups",
            root / "migrations",
            root / "web-activations",
            root / "runtime-activations",
        ):
            path.mkdir(parents=True, exist_ok=True)
        mark_controlled_copy(root)

        source = LaunchSelection(
            OLD_FIXTURE_DIGEST,
            OLD_FIXTURE_WEB_DIGEST,
            "0.10.1",
            "gen_fixture_0101",
        )
        target = LaunchSelection(
            asset["sha256"],
            target_overlay.web_overlay_sha256,
            "0.16.1",
            "gen_oci_0161",
        )
        source_data = root / "instances" / source.data_generation / "data"
        source_data.mkdir(parents=True)
        fixture_database = source_data / "legacy-0.10.1.sqlite"
        with sqlite3.connect(fixture_database) as connection:
            connection.execute("CREATE TABLE fixture_version (version TEXT NOT NULL, marker TEXT NOT NULL)")
            connection.execute("INSERT INTO fixture_version VALUES (?, ?)", ("0.10.1", "controlled-copy"))
            connection.commit()
        (source_data / "fixture-project.txt").write_text("0.10.1 fixture bytes\n", encoding="utf-8")
        source_before = tree_sha256(source_data)

        verified = {
            OLD_FIXTURE_DIGEST: "0.10.1",
            target_bundle.artifact_sha256: target_bundle.opendesign_version,
        }
        verified_overlays = {
            OLD_FIXTURE_WEB_DIGEST: {
                "od_version": "0.10.1",
                "compatible_runtime_artifact_sha256": [OLD_FIXTURE_DIGEST],
            },
            target_overlay.web_overlay_sha256: target_overlay,
        }
        write_generation_control(
            root,
            GenerationControl(
                active=source,
                previous_release=None,
                previous_web=None,
                migration_id=None,
                web_activation_id=None,
                updated_at="2026-08-05T00:00:00Z",
            ),
            verified_artifacts=verified,
            verified_overlays=verified_overlays,
        )
        imported = app_data / "imports" / LEGACY_ID / "import_001" / "brief.txt"
        imported.parent.mkdir(parents=True)
        imported.write_bytes(b"verified legacy import bytes\n")
        state_path = app_data / "state.json"
        state_path.write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "projects": [
                        {
                            "id": LEGACY_ID,
                            "name": "Controlled 0.10.1 migration",
                            "prompt": "Preserve the fixture structure",
                            "imports": [
                                {
                                    "status": "imported",
                                    "name": "brief.txt",
                                    "media_type": "text/plain",
                                    "app_data_path": imported.relative_to(app_data).as_posix(),
                                }
                            ],
                        }
                    ],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        timestamps = iter(f"2026-08-05T00:00:{second:02d}Z" for second in range(60))
        runtime = OciMigrationRuntime(
            root,
            STORE_ROOT,
            STORE_ROOT / "web",
            WEB_TRUST_CONTRACT,
            manifest,
        )
        runtime.verified_artifacts[OLD_FIXTURE_DIGEST] = "0.10.1"
        runtime.verified_overlays[OLD_FIXTURE_WEB_DIGEST] = verified_overlays[
            OLD_FIXTURE_WEB_DIGEST
        ]
        try:
            outcome = migrate_controlled_copy(
                root,
                legacy_state_path=state_path,
                target=target,
                migration_id="migration_real_oci_0161",
                verified_artifacts=verified,
                verified_overlays=verified_overlays,
                runtime=runtime,
                now=lambda: next(timestamps),
                minimum_free_bytes=0,
            )
            active = load_generation_control(
                root,
                verified_artifacts=verified,
                verified_overlays=verified_overlays,
            )
            target_data = root / "instances" / target.data_generation / "data"
            source_after = tree_sha256(source_data)
            target_integrity = _sqlite_integrity(target_data)
            mapping = json.loads((root / "legacy-project-map.json").read_text(encoding="utf-8"))
            mapping_sha256 = hashlib.sha256(
                (root / "legacy-project-map.json").read_bytes()
            ).hexdigest()
            evidence = runtime.evidence()
        finally:
            runtime.stop_sidecar()

        rollback_evidence = _real_rollback_smoke(
            Path(temporary),
            manifest=manifest,
            artifact_sha256=target_bundle.artifact_sha256,
            web_overlay_sha256=target_overlay.web_overlay_sha256,
        )

        if active.active != target or active.previous_release != source or outcome.control != active:
            raise SystemExit("OpenDesign migration did not atomically activate the target triple")
        if source_before != source_after:
            raise SystemExit("OpenDesign migration changed the retained 0.10.1 fixture generation")
        if outcome.migrated_projects != 1 or outcome.migrated_imports != 1:
            raise SystemExit("OpenDesign migration did not migrate the complete legacy fixture")
        mappings = mapping.get("mappings")
        if not isinstance(mappings, list) or len(mappings) != 1:
            raise SystemExit("OpenDesign migration mapping evidence is incomplete")
        imported_entries = mappings[0].get("imports") if isinstance(mappings[0], dict) else None
        if not isinstance(imported_entries, list) or len(imported_entries) != 1:
            raise SystemExit("OpenDesign migration import evidence is incomplete")
        result = {
            "ok": True,
            "workspace_data_migrated": False,
            "source": source.to_dict(),
            "target": target.to_dict(),
            "source_tree_sha256_before": source_before,
            "source_tree_sha256_after": source_after,
            "mapping_sha256": mapping_sha256,
            "migrated_projects": outcome.migrated_projects,
            "migrated_imports": outcome.migrated_imports,
            "target_database_integrity": target_integrity,
            "runtime": evidence,
            "real_rollback": rollback_evidence,
        }
        if arguments.evidence_output is not None:
            completed_at = datetime.now(tz=UTC)
            write_canonical_json(
                arguments.evidence_output,
                _acceptance_evidence(
                    result,
                    execution={
                        "schema_version": "1",
                        "run_id": str(uuid4()),
                        "parent_product_run_id": parent_product_run_id,
                        "runner": "apps/design-studio/service/smoke_opendesign_migration.py",
                        "required_command": [
                            "python3",
                            "apps/design-studio/service/smoke_opendesign_migration.py",
                            "--evidence-output",
                            "apps/design-studio/service/opendesign_migration_acceptance_0_16_1.json",
                            "--parent-product-run-id",
                            parent_product_run_id,
                        ],
                        "started_at": started_at.isoformat().replace("+00:00", "Z"),
                        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
                        "duration_ms": round((time.monotonic() - started) * 1000, 3),
                        "source": build_source_attestation(REPOSITORY_ROOT),
                    },
                ),
            )
        print(json.dumps(result, indent=2, sort_keys=True))


def _acceptance_evidence(
    result: dict[str, object],
    *,
    execution: dict[str, object],
) -> dict[str, object]:
    source = result["source"]
    target = result["target"]
    rollback = result["real_rollback"]
    if not isinstance(source, dict) or not isinstance(target, dict) or not isinstance(rollback, dict):
        raise SystemExit("OpenDesign migration smoke produced malformed evidence")
    rollback_active = rollback.get("active")
    if not isinstance(rollback_active, dict):
        raise SystemExit("OpenDesign rollback smoke produced malformed active selection")
    return {
        "schema_version": "2",
        "executed_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "execution": execution,
        "forward_fixture_migration": {
            "api_import_read_back": "byte_identical",
            "legacy_mapping_sha256": result["mapping_sha256"],
            "migrated_imports": result["migrated_imports"],
            "migrated_projects": result["migrated_projects"],
            "source": {
                "data_generation": source["data_generation"],
                "fixture_artifact_sha256": source["runtime_artifact_sha256"],
                "od_version": source["od_version"],
                "tree_sha256_before": result["source_tree_sha256_before"],
                "tree_sha256_after": result["source_tree_sha256_after"],
            },
            "target": {
                "artifact_sha256": target["runtime_artifact_sha256"],
                "data_generation": target["data_generation"],
                "database_integrity": result["target_database_integrity"],
                "od_version": target["od_version"],
                "real_materialized_daemon": True,
                "web_overlay_sha256": target["web_overlay_sha256"],
            },
        },
        "rollback": {
            "distinct_0_10_1_to_0_16_1_triple_atomicity": "passed",
            "forward_generation_preserved": rollback["forward_generation_preserved"],
            "previous_database_integrity": rollback["previous_database_integrity"],
            "previous_generation_reactivated": rollback_active["data_generation"],
            "real_daemon_health_database_and_project_smoke": "passed",
            "real_round_trip_artifact_sha256": rollback_active[
                "runtime_artifact_sha256"
            ],
            "real_round_trip_web_overlay_sha256": rollback_active[
                "web_overlay_sha256"
            ],
        },
        "runtime_evidence": {
            "forward": result["runtime"],
            "rollback": rollback["runtime"],
        },
        "workspace_data_migrated": False,
    }


def _real_rollback_smoke(
    temporary_root: Path,
    *,
    manifest: dict[str, object],
    artifact_sha256: str,
    web_overlay_sha256: str,
) -> dict[str, object]:
    app_data = temporary_root / "rollback-design-studio"
    root = app_data / "opendesign"
    for path in (
        root,
        root / "instances",
        root / "backups",
        root / "migrations",
        root / "web-activations",
        root / "runtime-activations",
    ):
        path.mkdir(parents=True, exist_ok=True)
    mark_controlled_copy(root)
    previous = LaunchSelection(
        artifact_sha256,
        web_overlay_sha256,
        "0.16.1",
        "gen_real_previous",
    )
    forward = LaunchSelection(
        artifact_sha256,
        web_overlay_sha256,
        "0.16.1",
        "gen_real_forward",
    )
    previous_data = root / "instances" / previous.data_generation / "data"
    previous_data.mkdir(parents=True)
    verified = {artifact_sha256: "0.16.1"}
    stored_overlay = OpenDesignArtifactStore(STORE_ROOT).fast_web_overlay(
        web_overlay_sha256,
        runtime_artifact_sha256=artifact_sha256,
    )
    overlays = {web_overlay_sha256: verified_overlay_from_store(stored_overlay)}
    write_generation_control(
        root,
        GenerationControl(
            active=previous,
            previous_release=None,
            previous_web=None,
            migration_id=None,
            web_activation_id=None,
            updated_at="2026-08-05T01:00:00Z",
        ),
        verified_artifacts=verified,
        verified_overlays=overlays,
    )
    runtime = OciMigrationRuntime(
        root,
        STORE_ROOT,
        STORE_ROOT / "web",
        WEB_TRUST_CONTRACT,
        manifest,
    )
    runtime.freeze_mutations()
    try:
        runtime.start_sidecar(previous, previous_data, staging=False)
        runtime.health_check()
        project_id = runtime.create_legacy_project(
            {"id": LEGACY_ID, "name": "Retained rollback project"},
            idempotency_key="real-rollback-retained-project",
        )
        runtime.upload_legacy_import(
            project_id,
            name="retained.txt",
            media_type="text/plain",
            content=b"retained generation bytes\n",
            sha256=hashlib.sha256(b"retained generation bytes\n").hexdigest(),
        )
        runtime.verify_database()
    finally:
        runtime.stop_sidecar()
        runtime.prove_sidecar_stopped(previous_data)
        runtime.unfreeze_mutations()

    legacy_state = app_data / "state.json"
    legacy_state.write_text('{"projects":[],"schema_version":"1"}', encoding="utf-8")
    timestamps = iter(f"2026-08-05T01:00:{second:02d}Z" for second in range(60))
    migrate_controlled_copy(
        root,
        legacy_state_path=legacy_state,
        target=forward,
        migration_id="migration_real_forward",
        verified_artifacts=verified,
        verified_overlays=overlays,
        runtime=runtime,
        now=lambda: next(timestamps),
        minimum_free_bytes=0,
    )
    runtime.stop_sidecar()
    forward_data = root / "instances" / forward.data_generation / "data"
    forward_marker = forward_data / "forward-only.marker"
    forward_marker.write_bytes(b"forward generation remains untouched\n")
    try:
        rolled_back = rollback_controlled_copy(
            root,
            rollback_id="migration_real_rollback",
            verified_artifacts=verified,
            verified_overlays=overlays,
            runtime=runtime,
            now=lambda: next(timestamps),
        )
        control = load_generation_control(
            root,
            verified_artifacts=verified,
            verified_overlays=overlays,
        )
        previous_integrity = _sqlite_integrity(previous_data)
    finally:
        runtime.stop_sidecar()
    if rolled_back.active != previous or control.active != previous:
        raise SystemExit("OpenDesign real rollback did not reactivate the retained triple")
    if not forward_marker.is_file() or forward_marker.read_bytes() != b"forward generation remains untouched\n":
        raise SystemExit("OpenDesign real rollback changed the forward generation")
    return {
        "active": control.active.to_dict(),
        "forward_generation_preserved": True,
        "previous_database_integrity": previous_integrity,
        "runtime": runtime.evidence(),
    }


def _sqlite_integrity(data_dir: Path) -> dict[str, str]:
    results: dict[str, str] = {}
    for database in sorted(data_dir.rglob("*.sqlite")):
        if database.is_symlink() or not database.is_file():
            raise SystemExit("OpenDesign migrated generation contains an unsafe database path")
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        results[database.relative_to(data_dir).as_posix()] = str(row[0]) if row else "missing"
    if not results or any(value != "ok" for value in results.values()):
        raise SystemExit("OpenDesign migrated generation database integrity failed")
    return results


if __name__ == "__main__":
    main()
