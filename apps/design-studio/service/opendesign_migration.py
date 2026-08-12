"""Controlled-copy migration, rollback, recovery, and retention orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Mapping

from opendesign_generation_control import (
    load_generation_control,
    load_migration_journal,
    recover_generation_control,
    resolve_generation_data_dir,
    write_generation_control,
    write_migration_journal,
)
from opendesign_generation_model import (
    GenerationControl,
    GenerationControlError,
    LaunchSelection,
    MigrationJournal,
)
from opendesign_migration_files import (
    GENERATION_ID,
    MIGRATION_ID,
    atomic_write_json,
    clean_unjournaled_failure,
    clone_generation,
    controlled_root,
    create_snapshot,
    migration_lock,
    remove_owned_directory,
    require_real_directory,
    sha256_file,
    tree_sha256,
    validate_identifier,
    verify_free_space,
)
from opendesign_migration_legacy import (
    LEGACY_PROJECT_MAP,
    MAX_LEGACY_STATE_BYTES,
    migrate_legacy_catalog,
    read_legacy_state,
    seal_legacy_state,
)
from opendesign_migration_runtime import (
    BundleUpgradeOutcome,
    MigrationError,
    MigrationOutcome,
    MigrationRuntime,
    RecoveryOutcome,
)


def migrate_controlled_copy(
    root: Path,
    *,
    legacy_state_path: Path,
    target: LaunchSelection,
    migration_id: str,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
    runtime: MigrationRuntime,
    now: Callable[[], str] | None = None,
    minimum_free_bytes: int = 64 * 1024 * 1024,
) -> MigrationOutcome:
    """Migrate one marked fixture/copy and atomically activate its target triple."""
    root = controlled_root(root)
    validate_identifier(migration_id, MIGRATION_ID, "migration_id")
    timestamp = now or _utc_now
    with migration_lock(root):
        runtime.freeze_mutations()
        prepared: MigrationJournal | None = None
        control_switched = False
        created_snapshot: Path | None = None
        created_generation: Path | None = None
        mapping_path: Path | None = None
        try:
            runtime.drain_or_cancel_runs()
            control = load_generation_control(
                root,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
            source = control.active
            if target == source or target.data_generation == source.data_generation:
                raise MigrationError("migration target must use a new bundle/data triple")
            _verify_target_selection(target, verified_artifacts, verified_overlays)
            source_data = resolve_generation_data_dir(root, source)
            runtime.stop_sidecar()
            runtime.prove_sidecar_stopped(source_data)
            verify_free_space(root, source_data, minimum_free_bytes=minimum_free_bytes)
            legacy_state, legacy_state_sha256 = read_legacy_state(
                legacy_state_path,
                migration_root=root,
            )

            created_snapshot = create_snapshot(
                root,
                migration_id,
                source_data,
                legacy_state_path,
                maximum_legacy_state_bytes=MAX_LEGACY_STATE_BYTES,
            )
            target_data = clone_generation(root, source_data, target.data_generation)
            created_generation = target_data.parent
            runtime.start_sidecar(target, target_data, staging=True)
            checks = _prefixed_checks("pre_migration", _validate_staging(runtime))
            mapping, project_count, import_count = migrate_legacy_catalog(
                legacy_state,
                migration_root=root,
                runtime=runtime,
                migration_id=migration_id,
            )
            checks.update(_prefixed_checks("post_migration", _validate_staging(runtime)))
            mapping_destination = root / LEGACY_PROJECT_MAP
            if mapping_destination.exists() or mapping_destination.is_symlink():
                raise MigrationError("legacy project map already exists")
            atomic_write_json(
                mapping_destination,
                {
                    "schema_version": "1",
                    "migration_id": migration_id,
                    "source_state_sha256": legacy_state_sha256,
                    "mappings": mapping,
                    "errors": [],
                    "updated_at": timestamp(),
                },
            )
            mapping_path = mapping_destination
            mapping_sha256 = sha256_file(mapping_path)
            runtime.stop_sidecar()
            runtime.prove_sidecar_stopped(target_data)

            prepared = MigrationJournal(
                migration_id=migration_id,
                state="prepared",
                source=source,
                target=target,
                source_snapshot=f"backups/{migration_id}",
                checks={
                    **checks,
                    "source_snapshot_sha256": tree_sha256(created_snapshot),
                    "legacy_state_sha256": legacy_state_sha256,
                    "legacy_project_map_sha256": mapping_sha256,
                    "migrated_projects": project_count,
                    "migrated_imports": import_count,
                },
                created_at=timestamp(),
                updated_at=timestamp(),
            )
            write_migration_journal(
                root,
                prepared,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
            cutover = GenerationControl(
                active=target,
                previous_release=source,
                previous_web=None,
                migration_id=migration_id,
                web_activation_id=None,
                updated_at=timestamp(),
            )
            write_generation_control(
                root,
                cutover,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
            control_switched = True
            write_migration_journal(
                root,
                _journal_with_state(prepared, "cutover_committed", updated_at=timestamp()),
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
            seal_legacy_state(legacy_state_path, migration_root=root)
            runtime.start_sidecar(target, target_data, staging=False)
            return MigrationOutcome(migration_id, cutover, mapping_sha256, project_count, import_count)
        except (MigrationError, GenerationControlError, OSError, ValueError) as exc:
            _stop_after_failure(runtime)
            if prepared is not None and not control_switched:
                aborted = _journal_with_state(
                    prepared,
                    "aborted",
                    updated_at=timestamp(),
                    checks={**prepared.checks, "error_code": type(exc).__name__},
                )
                write_migration_journal(
                    root,
                    aborted,
                    verified_artifacts=verified_artifacts,
                    verified_overlays=verified_overlays,
                )
            elif prepared is None:
                clean_unjournaled_failure(root, created_generation, created_snapshot, mapping_path)
            raise MigrationError(f"controlled OpenDesign migration failed: {type(exc).__name__}") from exc
        finally:
            runtime.unfreeze_mutations()


def upgrade_controlled_copy(
    root: Path,
    *,
    target: LaunchSelection,
    migration_id: str,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
    runtime: MigrationRuntime,
    now: Callable[[], str] | None = None,
    minimum_free_bytes: int = 64 * 1024 * 1024,
    replace_retained_previous: bool = False,
) -> BundleUpgradeOutcome:
    """Clone and validate an existing generation before an atomic bundle cutover."""
    root = controlled_root(root)
    validate_identifier(migration_id, MIGRATION_ID, "migration_id")
    timestamp = now or _utc_now
    with migration_lock(root):
        runtime.freeze_mutations()
        prepared: MigrationJournal | None = None
        control_switched = False
        created_snapshot: Path | None = None
        created_generation: Path | None = None
        try:
            runtime.drain_or_cancel_runs()
            control = load_generation_control(
                root,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
            source = control.active
            replaced_retained_previous = False
            if control.previous_release is not None or control.migration_id is not None:
                if not replace_retained_previous:
                    raise MigrationError("bundle upgrade requires resolved retention metadata")
                if control.previous_release is None or control.migration_id is None:
                    raise MigrationError("bundle upgrade retention metadata is incomplete")
                retained_journal = load_migration_journal(
                    root,
                    control.migration_id,
                    verified_artifacts=verified_artifacts,
                    verified_overlays=verified_overlays,
                )
                if retained_journal.state != "cutover_committed":
                    raise MigrationError("bundle upgrade cannot replace uncommitted retention metadata")
                replaced_retained_previous = True
            if target == source or target.data_generation == source.data_generation:
                raise MigrationError("bundle upgrade target must use a new bundle/data triple")
            _verify_target_selection(target, verified_artifacts, verified_overlays)
            source_data = resolve_generation_data_dir(root, source)
            runtime.stop_sidecar()
            runtime.prove_sidecar_stopped(source_data)
            verify_free_space(root, source_data, minimum_free_bytes=minimum_free_bytes)

            created_snapshot = create_snapshot(
                root,
                migration_id,
                source_data,
                None,
                maximum_legacy_state_bytes=MAX_LEGACY_STATE_BYTES,
            )
            target_data = clone_generation(root, source_data, target.data_generation)
            created_generation = target_data.parent
            runtime.start_sidecar(target, target_data, staging=True)
            staging_checks = _validate_staging(runtime)
            checks = _prefixed_checks("pre_cutover", staging_checks)
            project_count = int(staging_checks["staging_project_count"])
            runtime.stop_sidecar()
            runtime.prove_sidecar_stopped(target_data)

            prepared = MigrationJournal(
                migration_id=migration_id,
                state="prepared",
                source=source,
                target=target,
                source_snapshot=f"backups/{migration_id}",
                checks={
                    **checks,
                    "source_snapshot_sha256": tree_sha256(created_snapshot),
                    "upgrade_kind": "bundle_controlled_copy",
                    "replaced_retained_previous": replaced_retained_previous,
                },
                created_at=timestamp(),
                updated_at=timestamp(),
            )
            write_migration_journal(
                root,
                prepared,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
            cutover = GenerationControl(
                active=target,
                previous_release=source,
                previous_web=None,
                migration_id=migration_id,
                web_activation_id=None,
                updated_at=timestamp(),
            )
            write_generation_control(
                root,
                cutover,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
            control_switched = True
            write_migration_journal(
                root,
                _journal_with_state(prepared, "cutover_committed", updated_at=timestamp()),
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
            runtime.start_sidecar(target, target_data, staging=False)
            _validate_staging(runtime)
            return BundleUpgradeOutcome(migration_id, cutover, project_count)
        except (MigrationError, GenerationControlError, OSError, ValueError) as exc:
            _stop_after_failure(runtime)
            if prepared is not None and not control_switched:
                aborted = _journal_with_state(
                    prepared,
                    "aborted",
                    updated_at=timestamp(),
                    checks={**prepared.checks, "error_code": type(exc).__name__},
                )
                write_migration_journal(
                    root,
                    aborted,
                    verified_artifacts=verified_artifacts,
                    verified_overlays=verified_overlays,
                )
            elif prepared is None:
                clean_unjournaled_failure(root, created_generation, created_snapshot, None)
            raise MigrationError(f"controlled OpenDesign bundle upgrade failed: {type(exc).__name__}") from exc
        finally:
            runtime.unfreeze_mutations()


def rollback_controlled_copy(
    root: Path,
    *,
    rollback_id: str,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
    runtime: MigrationRuntime,
    now: Callable[[], str] | None = None,
) -> GenerationControl:
    """Atomically restore the retained previous bundle/data triple."""
    root = controlled_root(root)
    validate_identifier(rollback_id, MIGRATION_ID, "rollback_id")
    timestamp = now or _utc_now
    with migration_lock(root):
        runtime.freeze_mutations()
        backup: Path | None = None
        journal_written = False
        try:
            runtime.drain_or_cancel_runs()
            control = load_generation_control(
                root,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
            if control.previous_release is None or control.migration_id is None:
                raise MigrationError("rollback requires one retained previous triple")
            require_real_directory(
                root / "backups" / control.migration_id,
                root=root,
                label="retained migration snapshot",
            )
            active_data = resolve_generation_data_dir(root, control.active)
            target_data = resolve_generation_data_dir(root, control.previous_release)
            runtime.stop_sidecar()
            runtime.prove_sidecar_stopped(active_data)
            backup = create_snapshot(
                root,
                rollback_id,
                active_data,
                None,
                maximum_legacy_state_bytes=MAX_LEGACY_STATE_BYTES,
            )
            prepared = MigrationJournal(
                migration_id=rollback_id,
                state="prepared",
                source=control.active,
                target=control.previous_release,
                source_snapshot=f"backups/{rollback_id}",
                checks={
                    "retained_snapshot_verified": True,
                    "source_snapshot_sha256": tree_sha256(backup),
                },
                created_at=timestamp(),
                updated_at=timestamp(),
            )
            write_migration_journal(
                root,
                prepared,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
            journal_written = True
            rollback = GenerationControl(
                active=control.previous_release,
                previous_release=control.active,
                previous_web=None,
                migration_id=rollback_id,
                web_activation_id=None,
                updated_at=timestamp(),
            )
            write_generation_control(
                root,
                rollback,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
            write_migration_journal(
                root,
                _journal_with_state(prepared, "cutover_committed", updated_at=timestamp()),
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
            runtime.start_sidecar(rollback.active, target_data, staging=False)
            _validate_staging(runtime)
            return rollback
        except (MigrationError, GenerationControlError, OSError, ValueError) as exc:
            _stop_after_failure(runtime)
            if backup is not None and not journal_written and backup.exists():
                remove_owned_directory(
                    backup,
                    parent=root / "backups",
                    label="failed rollback snapshot",
                )
            raise MigrationError(f"controlled OpenDesign rollback failed: {type(exc).__name__}") from exc
        finally:
            runtime.unfreeze_mutations()


def recover_controlled_copy(
    root: Path,
    *,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
    runtime: MigrationRuntime,
    now: Callable[[], str] | None = None,
) -> RecoveryOutcome:
    """Reconcile crash metadata and start only the active verified triple."""
    root = controlled_root(root)
    timestamp = now or _utc_now
    with migration_lock(root):
        runtime.freeze_mutations()
        try:
            runtime.stop_sidecar()
            recovery = recover_generation_control(
                root,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
            runtime.prove_sidecar_stopped(recovery.active_data_dir)
            completed = _finish_pending_journal(
                root,
                recovery.control,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
                updated_at=timestamp(),
            )
            runtime.start_sidecar(recovery.control.active, recovery.active_data_dir, staging=False)
            _validate_staging(runtime)
            return RecoveryOutcome(recovery.control, recovery.migration_reconciliations, completed)
        except (MigrationError, GenerationControlError, OSError, ValueError) as exc:
            _stop_after_failure(runtime)
            raise MigrationError(f"controlled OpenDesign recovery failed: {type(exc).__name__}") from exc
        finally:
            runtime.unfreeze_mutations()


def cleanup_unreferenced_generation(
    root: Path,
    *,
    generation_id: str,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
    runtime: MigrationRuntime,
    retention_expired: bool,
) -> None:
    """Explicitly delete one unreferenced fixture generation after retention."""
    root = controlled_root(root)
    validate_identifier(generation_id, GENERATION_ID, "generation_id")
    if not retention_expired:
        raise MigrationError("generation retention has not expired")
    with migration_lock(root):
        control = load_generation_control(
            root,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        referenced = {control.active.data_generation}
        if control.previous_release is not None:
            referenced.add(control.previous_release.data_generation)
        for journal_path in sorted((root / "migrations").glob("migration_*.json")):
            journal = load_migration_journal(
                root,
                journal_path.stem,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
            if journal.state == "prepared" or journal.migration_id == control.migration_id:
                referenced.update((journal.source.data_generation, journal.target.data_generation))
        if generation_id in referenced:
            raise MigrationError("generation is still referenced by control or a journal")
        candidate = root / "instances" / generation_id
        require_real_directory(candidate, root=root, label="generation cleanup candidate")
        runtime.prove_sidecar_stopped(candidate / "data")
        remove_owned_directory(candidate, parent=root / "instances", label="generation cleanup candidate")


def _finish_pending_journal(
    root: Path,
    control: GenerationControl,
    *,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
    updated_at: str,
) -> bool:
    if control.migration_id is None:
        return False
    journal = load_migration_journal(
        root,
        control.migration_id,
        verified_artifacts=verified_artifacts,
        verified_overlays=verified_overlays,
    )
    completed = journal.state == "prepared" and control.active == journal.target
    if completed:
        write_migration_journal(
            root,
            _journal_with_state(journal, "cutover_committed", updated_at=updated_at),
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
    if journal.state == "cutover_committed" or completed:
        legacy_state = root.parent / "state.json"
        if legacy_state.exists() and not legacy_state.is_symlink():
            seal_legacy_state(legacy_state, migration_root=root)
    return completed


def _validate_staging(runtime: MigrationRuntime) -> dict[str, object]:
    runtime.health_check()
    runtime.verify_database()
    project_ids = runtime.list_project_ids()
    if project_ids:
        runtime.smoke_project(project_ids[0])
    return {
        "health": "pass",
        "database_verify": "pass",
        "staging_project_count": len(project_ids),
        "project_smoke": "pass" if project_ids else "not_applicable",
    }


def _prefixed_checks(prefix: str, checks: Mapping[str, object]) -> dict[str, object]:
    return {f"{prefix}_{key}": value for key, value in checks.items()}


def _journal_with_state(
    journal: MigrationJournal,
    state: str,
    *,
    updated_at: str,
    checks: dict[str, object] | None = None,
) -> MigrationJournal:
    return MigrationJournal(
        migration_id=journal.migration_id,
        state=state,
        source=journal.source,
        target=journal.target,
        source_snapshot=journal.source_snapshot,
        checks=journal.checks if checks is None else checks,
        created_at=journal.created_at,
        updated_at=updated_at,
    )


def _verify_target_selection(
    target: LaunchSelection,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
) -> None:
    if verified_artifacts.get(target.runtime_artifact_sha256) != target.od_version:
        raise MigrationError("migration target runtime is not verified")
    overlay = verified_overlays.get(target.web_overlay_sha256)
    if overlay is None:
        raise MigrationError("migration target overlay is not verified")
    if isinstance(overlay, Mapping):
        version = overlay.get("od_version")
        compatible = overlay.get("compatible_runtime_artifact_sha256")
    else:
        version = getattr(overlay, "od_version", None)
        compatible = getattr(overlay, "compatible_runtime_artifact_sha256", None)
    if version != target.od_version or target.runtime_artifact_sha256 not in (compatible or ()):
        raise MigrationError("migration target overlay is incompatible with its runtime")


def _stop_after_failure(runtime: MigrationRuntime) -> None:
    try:
        runtime.stop_sidecar()
    except Exception:
        return


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
