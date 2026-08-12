#!/usr/bin/env python3
"""Migrate a marked 0.10.1 fixture through the real pinned 0.16.1 daemon."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from opendesign_artifact import read_bundle_manifest, selected_asset, validate_bundle_manifest
from opendesign_generation_control import load_generation_control, write_generation_control
from opendesign_generation_model import GenerationControl, LaunchSelection
from opendesign_materialization import discover_verified_bundles
from opendesign_migration import migrate_controlled_copy, rollback_controlled_copy
from opendesign_migration_files import mark_controlled_copy, tree_sha256
from opendesign_migration_oci_runtime import OciMigrationRuntime
from opendesign_web_overlay import discover_verified_overlays


SERVICE_ROOT = Path(__file__).resolve().parent
REGISTRY_ROOT = SERVICE_ROOT / "vendor/open-design"
WEB_REGISTRY_ROOT = SERVICE_ROOT / "vendor/open-design-web"
WEB_TRUST_CONTRACT = SERVICE_ROOT / "opendesign_web_trust.json"
OLD_FIXTURE_DIGEST = "0101" * 16
OLD_FIXTURE_WEB_DIGEST = "0102" * 16
LEGACY_ID = "design_0123456789ab"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-output", type=Path)
    arguments = parser.parse_args()
    manifest = read_bundle_manifest(SERVICE_ROOT / "opendesign_bundle.json")
    validate_bundle_manifest(manifest, require_artifact_digest=True)
    asset = selected_asset(manifest, require_artifact_digest=True)
    bundles = discover_verified_bundles(REGISTRY_ROOT)
    target_bundle = bundles.get(asset["sha256"])
    if target_bundle is None:
        raise SystemExit("Pinned OpenDesign OCI artifact is not materialized")
    overlays = discover_verified_overlays(WEB_REGISTRY_ROOT, trust_contract=WEB_TRUST_CONTRACT)
    compatible = [
        overlay
        for overlay in overlays.values()
        if asset["sha256"] in overlay.compatible_runtime_artifact_sha256
    ]
    if len(compatible) != 1:
        raise SystemExit("Migration smoke requires one compatible canonical web overlay")
    target_overlay = compatible[0]

    with TemporaryDirectory(prefix="maverick-od-migration-smoke-") as temporary:
        app_data = Path(temporary) / "design-studio"
        root = app_data / "opendesign"
        for path in (
            root,
            root / "instances",
            root / "backups",
            root / "migrations",
            root / "web-activations",
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
            REGISTRY_ROOT,
            WEB_REGISTRY_ROOT,
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
            arguments.evidence_output.parent.mkdir(parents=True, exist_ok=True)
            arguments.evidence_output.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(result, indent=2, sort_keys=True))


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
    overlays = discover_verified_overlays(
        WEB_REGISTRY_ROOT,
        trust_contract=WEB_TRUST_CONTRACT,
        required_digests={web_overlay_sha256},
    )
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
        REGISTRY_ROOT,
        WEB_REGISTRY_ROOT,
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
