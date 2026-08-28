"""One-time verified cutover from the legacy OpenDesign generation to native data."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from typing import Any, Callable

from native_cutover_files import (
    atomic_write_json,
    copy_legacy_files,
    copy_verified_tree,
    fsync_directory,
    make_files_read_only,
    make_tree_read_only,
    real_directory,
    tree_evidence,
)
from native_cutover_state import (
    BACKUP_DIRECTORY,
    GENERATION_PATTERN,
    MARKER_FILE,
    NativeDataCutoverError,
    backup_files,
    begin_native_writer_activation,
    cutover_lock,
    existing_marker,
    finish_native_writer_activation,
    legacy_source,
    new_cutover_id,
    read_only_files,
    utc_now,
)
from official_opendesign_release import OfficialInstallation
from official_public_inventory import inventory_digest, inventory_official_copy


InventoryRunner = Callable[..., dict[str, Any]]


def perform_native_data_cutover(
    app_data_root: Path,
    installation: OfficialInstallation,
    *,
    inventory_runner: InventoryRunner = inventory_official_copy,
    cutover_id: str | None = None,
) -> dict[str, Any]:
    """Back up, restore/probe twice, compare, and atomically select native data."""
    app_root = real_directory(app_data_root, label="Design Studio data root")
    marker_path = app_root / MARKER_FILE
    existing = existing_marker(marker_path)
    if existing is not None:
        return {**existing, "already_cut_over": True}
    identifier = cutover_id or new_cutover_id()
    if not GENERATION_PATTERN.fullmatch(identifier):
        raise NativeDataCutoverError("cutover id is invalid")
    with cutover_lock(app_root / ".native-cutover.lock"):
        existing = existing_marker(marker_path)
        if existing is not None:
            return {**existing, "already_cut_over": True}
        return _perform_locked(
            app_root,
            installation,
            inventory_runner=inventory_runner,
            cutover_id=identifier,
        )


def _perform_locked(
    app_root: Path,
    installation: OfficialInstallation,
    *,
    inventory_runner: InventoryRunner,
    cutover_id: str,
) -> dict[str, Any]:
    source, generation = legacy_source(app_root)
    native = real_directory(app_root / "opendesign-native", label="native OpenDesign data")
    if native.parent != app_root or source == native:
        raise NativeDataCutoverError("legacy and native OpenDesign data roots overlap")
    backups = real_directory(app_root / BACKUP_DIRECTORY, label="cutover backup root", create=True)
    backup = backups / f"official-native-{cutover_id}"
    staging_backup = backups / f".{backup.name}.tmp"
    if backup.exists() or backup.is_symlink() or staging_backup.exists() or staging_backup.is_symlink():
        raise NativeDataCutoverError("cutover backup identity already exists")
    staging_backup.mkdir(mode=0o700)
    try:
        source_evidence = copy_verified_tree(source, staging_backup / "canonical-source")
        previous_native = copy_verified_tree(native, staging_backup / "previous-native")
        legacy_paths = backup_files(generation)
        legacy_hashes = copy_legacy_files(app_root, staging_backup / "legacy-files", legacy_paths)
        manifest = {
            "schema_version": "1",
            "kind": "design-studio-official-native-cutover-backup",
            "cutover_id": cutover_id,
            "created_at": utc_now(),
            "source_generation": generation,
            "official_release": {
                "version": installation.release.version,
                "manifest_digest": installation.release.manifest_digest,
                "rootfs_snapshot_sha256": installation.rootfs_snapshot_sha256,
                "customizations": [],
            },
            "canonical_source": source_evidence,
            "previous_native": previous_native,
            "legacy_file_sha256": legacy_hashes,
        }
        atomic_write_json(staging_backup / "backup-manifest.json", manifest)
        os.replace(staging_backup, backup)
        fsync_directory(backups)
    except Exception:
        shutil.rmtree(staging_backup, ignore_errors=True)
        raise

    try:
        marker = _certify_and_select(
            app_root,
            installation,
            source=source,
            native=native,
            backup=backup,
            manifest=manifest,
            generation=generation,
            inventory_runner=inventory_runner,
            cutover_id=cutover_id,
        )
    except Exception:
        make_tree_read_only(backup)
        raise
    make_tree_read_only(backup)
    return marker


def _certify_and_select(
    app_root: Path,
    installation: OfficialInstallation,
    *,
    source: Path,
    native: Path,
    backup: Path,
    manifest: dict[str, Any],
    generation: str,
    inventory_runner: InventoryRunner,
    cutover_id: str,
) -> dict[str, Any]:
    with TemporaryDirectory(prefix=f"opendesign-native-cutover-{cutover_id}-") as temporary:
        disposable = Path(temporary)
        baseline = disposable / "baseline"
        restored = disposable / "restored"
        copy_verified_tree(backup / "canonical-source", baseline)
        copy_verified_tree(backup / "canonical-source", restored)
        _remove_legacy_runtime_metadata(restored)
        restored.chmod(0o700)
        before = inventory_runner(
            installation, data_dir=baseline, log_path=disposable / "baseline.log"
        )
        after = inventory_runner(
            installation, data_dir=restored, log_path=disposable / "restored.log"
        )
        certification = _certification(cutover_id, before=before, after=after)
        atomic_write_json(backup / "public-api-certification.json", certification)
        mismatches = certification["mismatched_categories"]
        if mismatches:
            raise NativeDataCutoverError(
                "restored official inventory differs in categories: " + ", ".join(mismatches)
            )
        migrated_evidence = tree_evidence(restored)
        rollback_native = _select_native(app_root, native, restored, cutover_id=cutover_id)
        try:
            readonly = make_files_read_only(app_root, read_only_files(generation))
            make_tree_read_only(source)
            now = utc_now()
            marker = {
                "schema_version": "1",
                "kind": "design-studio-official-native-cutover",
                "cutover_id": cutover_id,
                "phase": "prepared",
                "created_at": now,
                "updated_at": now,
                "backup_directory": f"{BACKUP_DIRECTORY}/{backup.name}",
                "source_generation": generation,
                "source_tree_sha256": manifest["canonical_source"]["sha256"],
                "native_tree_sha256": migrated_evidence["sha256"],
                "public_inventory_sha256": certification["inventory_sha256"],
                "inventory_categories": certification["after"]["categories"],
                "legacy_read_only_files": readonly,
                "legacy_source_read_only": True,
                "legacy_writer_enabled": False,
                "native_writer_started": False,
                "native_ready": False,
                "rollback_to_legacy_allowed": True,
                "writer": "official-native-opendesign",
                "semantic_content_copied_to_maverick_state": False,
            }
            atomic_write_json(app_root / MARKER_FILE, marker)
        except Exception:
            shutil.rmtree(native, ignore_errors=True)
            os.replace(rollback_native, native)
            fsync_directory(app_root)
            raise
        shutil.rmtree(rollback_native)
        fsync_directory(app_root)
        return marker


def _certification(
    cutover_id: str,
    *,
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    mismatches = _inventory_mismatches(before, after)
    return {
        "schema_version": "1",
        "kind": "design-studio-official-native-cutover-certification",
        "cutover_id": cutover_id,
        "verified_at": utc_now(),
        "before": before,
        "after": after,
        "inventory_sha256": inventory_digest(after),
        "mismatched_categories": mismatches,
        "matches": not mismatches,
        "private_database_read": False,
        "official_migrations_only": True,
    }


def _select_native(app_root: Path, native: Path, restored: Path, *, cutover_id: str) -> Path:
    staging = app_root / f".opendesign-native.{cutover_id}.tmp"
    rollback = app_root / f".opendesign-native.{cutover_id}.rollback"
    if staging.exists() or rollback.exists() or staging.is_symlink() or rollback.is_symlink():
        raise NativeDataCutoverError("native cutover staging identity already exists")
    copy_verified_tree(restored, staging)
    try:
        os.replace(native, rollback)
        os.replace(staging, native)
        fsync_directory(app_root)
    except Exception:
        if not native.exists() and rollback.exists():
            os.replace(rollback, native)
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return rollback


def _inventory_mismatches(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    before_categories = before.get("categories") if isinstance(before, dict) else None
    after_categories = after.get("categories") if isinstance(after, dict) else None
    if not isinstance(before_categories, dict) or not isinstance(after_categories, dict):
        raise NativeDataCutoverError("official inventory response is invalid")
    return sorted(
        key
        for key in set(before_categories) | set(after_categories)
        if before_categories.get(key) != after_categories.get(key)
    )


def _remove_legacy_runtime_metadata(data_root: Path) -> None:
    shutil.rmtree(data_root / "maverick-runtime", ignore_errors=True)
    for name in ("launcher-status.json", "maverick-ready.json"):
        (data_root / name).unlink(missing_ok=True)

__all__ = [
    "NativeDataCutoverError",
    "begin_native_writer_activation",
    "finish_native_writer_activation",
    "perform_native_data_cutover",
]
