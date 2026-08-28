"""Install and transactionally select a user-chosen official OpenDesign update."""

from __future__ import annotations

from contextlib import suppress
import json
import os
from pathlib import Path
import shutil
from typing import Any, Callable

from native_cutover_files import (
    atomic_write_json,
    copy_verified_tree,
    make_tree_private_writable,
    make_tree_read_only,
    real_directory,
)
from native_cutover_quiescence import quiesce_native_host, release_native_host
from official_bridge_contracts import (
    probe_delegation_contract,
    read_delegation_contract,
    write_bridge_contracts,
)
from official_opendesign_release import (
    OfficialInstallation,
    OfficialReleaseError,
    install_official_release,
    load_official_release,
    verify_official_installation,
)
from official_public_inventory import inventory_official_copy
from official_release_selection import (
    OfficialReleaseSelection,
    ensure_release_selection,
    write_release_selection,
)
from official_update_state import (
    OfficialUpdateError,
    UPDATE_BACKUPS,
    empty_inventory_categories,
    incomplete_migration_guard,
    inventory_categories,
    migration_preservation_guard,
    new_update_id,
    release_identity,
    utc_now,
    write_update_state,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
NATIVE_DATA_DIRECTORY = "opendesign-native"


def perform_official_update(
    app_data_root: Path,
    artifact_root: Path,
    release_descriptor: Path,
    *,
    workspace_id: str,
    confirmed: bool,
    update_id: str | None = None,
    install_runner: Callable[..., OfficialInstallation] = install_official_release,
    verify_runner: Callable[..., OfficialInstallation] = verify_official_installation,
    inventory_runner: Callable[..., dict[str, Any]] = inventory_official_copy,
    delegation_probe: Callable[..., dict[str, Any]] = probe_delegation_contract,
    sidecar_control: Callable[[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Migrate a stable copy, atomically select it, and recover on startup failure."""
    if confirmed is not True:
        raise OfficialUpdateError("explicit official update confirmation is required")
    root = real_directory(app_data_root, label="Design Studio data root")
    store = real_directory(artifact_root, label="official OpenDesign artifact store")
    native = real_directory(root / NATIVE_DATA_DIRECTORY, label="native OpenDesign data")
    bundled = load_official_release()
    previous = ensure_release_selection(root, bundled)
    previous_installation = verify_runner(
        store / "official" / previous.release.digest_key,
        expected_release=previous.release,
    )
    candidate = load_official_release(release_descriptor, require_bundled_pin=False)
    if candidate.manifest_digest == previous.release.manifest_digest:
        raise OfficialUpdateError("the selected official OpenDesign release is already active")
    candidate_installation = install_runner(
        store / "official" / candidate.digest_key,
        release=candidate,
    )
    identifier = update_id or new_update_id()
    control = sidecar_control or _sidecar_control
    previous_delegation = read_delegation_contract(root, previous.release)
    quiesce_native_host(root, cutover_id=identifier)
    activated = False
    backup: Path | None = None
    marker: dict[str, Any] | None = None
    baseline_categories = empty_inventory_categories()
    migrated_categories = empty_inventory_categories()
    migration_guard = incomplete_migration_guard()
    work = root / f".{identifier}.work"
    try:
        response = control("stop", workspace_id)
        if response.get("ready") is not False:
            raise OfficialUpdateError("Core did not confirm the native OpenDesign writer stop")
        backup = _prepare_backup(root, native, previous, identifier)
        work.mkdir(mode=0o700)
        baseline_data = work / "baseline-data"
        migrated_data = work / "migrated-data"
        probe_data = work / "probe-data"
        copy_verified_tree(native, baseline_data)
        copy_verified_tree(native, migrated_data)
        baseline = inventory_runner(
            previous_installation,
            data_dir=baseline_data,
            log_path=backup / "baseline-inventory.log",
        )
        baseline_categories = inventory_categories(baseline)
        migrated = inventory_runner(
            candidate_installation,
            data_dir=migrated_data,
            log_path=backup / "candidate-migration.log",
        )
        migrated_categories = inventory_categories(migrated)
        migration_guard = migration_preservation_guard(baseline, migrated)
        if migration_guard["state"] != "passed":
            removed = [
                category
                for category, count in migration_guard["lost_identity_counts"].items()
                if count
            ]
            raise OfficialUpdateError(
                "candidate migration removed protected native identities: "
                + ", ".join(removed)
            )
        delegation = _probe_delegation(
            candidate_installation,
            migrated_data=migrated_data,
            probe_data=probe_data,
            log_path=backup / "delegation-contract.log",
            delegation_probe=delegation_probe,
        )
        marker = _marker(
            identifier,
            previous=previous,
            candidate=candidate_installation,
            baseline=baseline,
            migrated=migrated,
            migration_guard=migration_guard,
            delegation=delegation,
        )
        write_update_state(root, marker)
        retired = work / "retired-data"
        os.replace(native, retired)
        activated = True
        os.replace(migrated_data, native)
        write_release_selection(root, candidate)
        write_bridge_contracts(root, candidate, delegation=delegation)
        marker.update({"phase": "activating", "updated_at": utc_now()})
        write_update_state(root, marker)
        release_native_host(root, cutover_id=identifier)
        readiness = control("prewarm", workspace_id)
        if readiness.get("ready") is not True:
            raise OfficialUpdateError("the selected official OpenDesign release did not become ready")
        bridges = _live_bridge_results(root, delegation)
        marker.update(
            {
                "phase": "committed",
                "updated_at": utc_now(),
                "native_ready": True,
                "bridges": bridges,
            }
        )
        write_update_state(root, marker)
        _write_backup_evidence(backup, marker)
        make_tree_read_only(backup)
        shutil.rmtree(work, ignore_errors=True)
        return {"update_applied": True, "update": marker}
    except Exception as error:
        if activated and backup is not None:
            recovered = _rollback_activated_update(
                root,
                native=native,
                work=work,
                backup=backup,
                previous=previous,
                previous_delegation=previous_delegation,
                identifier=identifier,
                workspace_id=workspace_id,
                control=control,
            )
            return {
                "update_applied": False,
                "update": recovered,
                "error": "candidate_startup_failed",
            }
        try:
            _resume_previous_writer(
                root,
                identifier=identifier,
                workspace_id=workspace_id,
                control=control,
            )
        except Exception as recovery_error:
            with suppress(Exception):
                quiesce_native_host(root, cutover_id=identifier)
            recovery = marker or _recovery_required_marker(
                identifier,
                previous=previous,
                candidate=candidate_installation,
                baseline_inventory=baseline_categories,
                migrated_inventory=migrated_categories,
                migration_guard=migration_guard,
            )
            recovery.update(
                {
                    "phase": "recovery_required",
                    "updated_at": utc_now(),
                    "native_ready": False,
                    "rolled_back": False,
                }
            )
            try:
                write_update_state(root, recovery)
            except Exception as marker_error:
                raise OfficialUpdateError(
                    "official OpenDesign update recovery is quiesced but its "
                    "recovery_required marker could not be recorded"
                ) from marker_error
            shutil.rmtree(work, ignore_errors=True)
            if backup is not None:
                with suppress(Exception):
                    _write_backup_evidence(backup, recovery)
                    make_tree_read_only(backup)
            raise OfficialUpdateError(
                "official OpenDesign update recovery requires operator intervention"
            ) from recovery_error
        if marker is not None:
            marker.update(
                {
                    "phase": "rolled_back",
                    "updated_at": utc_now(),
                    "native_ready": True,
                    "rolled_back": True,
                }
            )
            write_update_state(root, marker)
        shutil.rmtree(work, ignore_errors=True)
        if backup is not None:
            with suppress(Exception):
                failure = {"schema_version": "1", "kind": "official-update-pre-activation-failure"}
                atomic_write_json(backup / "failure.json", failure)
                make_tree_read_only(backup)
        if isinstance(error, (OfficialUpdateError, OfficialReleaseError)):
            raise
        raise OfficialUpdateError("official OpenDesign update failed safely") from error


def _prepare_backup(
    root: Path,
    native: Path,
    previous: OfficialReleaseSelection,
    identifier: str,
) -> Path:
    backups = root / UPDATE_BACKUPS
    backups.mkdir(mode=0o700, exist_ok=True)
    backup = backups / f"official-update-{identifier}"
    if backup.exists() or backup.is_symlink():
        raise OfficialUpdateError("official update backup already exists")
    backup.mkdir(mode=0o700)
    copy_verified_tree(native, backup / "native-data")
    atomic_write_json(backup / "previous-selection.json", previous.payload)
    return backup


def _probe_delegation(
    installation: OfficialInstallation,
    *,
    migrated_data: Path,
    probe_data: Path,
    log_path: Path,
    delegation_probe: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    try:
        copy_verified_tree(migrated_data, probe_data)
        return delegation_probe(
            installation,
            data_dir=probe_data,
            log_path=log_path,
        )
    except Exception:
        return {"state": "degraded", "reason": "public_api_contract_incompatible"}


def _rollback_activated_update(
    root: Path,
    *,
    native: Path,
    work: Path,
    backup: Path,
    previous: OfficialReleaseSelection,
    previous_delegation: dict[str, Any],
    identifier: str,
    workspace_id: str,
    control: Callable[[str, str], dict[str, Any]],
) -> dict[str, Any]:
    try:
        quiesce_native_host(root, cutover_id=identifier)
        control("stop", workspace_id)
        failed = work / "failed-candidate-data"
        if failed.exists():
            shutil.rmtree(failed)
        if native.exists() and not native.is_symlink():
            os.replace(native, failed)
        copy_verified_tree(backup / "native-data", native)
        make_tree_private_writable(native)
        write_release_selection(root, previous.release, selected_at=previous.selected_at)
        write_bridge_contracts(root, previous.release, delegation=previous_delegation)
        release_native_host(root, cutover_id=identifier)
        readiness = control("prewarm", workspace_id)
        ready = readiness.get("ready") is True
        state = _read_marker_for_recovery(root)
        state.update(
            {
                "phase": "rolled_back" if ready else "recovery_required",
                "updated_at": utc_now(),
                "native_ready": ready,
                "rolled_back": ready,
                "bridges": {
                    "model_access": {"state": "unchecked"},
                    "delegation": previous_delegation,
                },
            }
        )
        write_update_state(root, state)
        _write_backup_evidence(backup, state)
        make_tree_read_only(backup)
        shutil.rmtree(work, ignore_errors=True)
        if not ready:
            quiesce_native_host(root, cutover_id=identifier)
            raise OfficialUpdateError(
                "official OpenDesign update recovery requires operator intervention"
            )
        return state
    except Exception as recovery_error:
        with suppress(Exception):
            state = _read_marker_for_recovery(root)
            state.update({"phase": "recovery_required", "updated_at": utc_now(), "native_ready": False})
            write_update_state(root, state)
        raise OfficialUpdateError("official OpenDesign update recovery requires operator intervention") from recovery_error


def _marker(
    identifier: str,
    *,
    previous: OfficialReleaseSelection,
    candidate: OfficialInstallation,
    baseline: dict[str, Any],
    migrated: dict[str, Any],
    migration_guard: dict[str, Any],
    delegation: dict[str, Any],
) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": "1",
        "kind": "design-studio-official-native-update",
        "update_id": identifier,
        "phase": "prepared",
        "created_at": now,
        "updated_at": now,
        "backup_directory": f"{UPDATE_BACKUPS}/official-update-{identifier}",
        "previous_release": release_identity(previous.release),
        "candidate_release": release_identity(candidate.release),
        "baseline_inventory": inventory_categories(baseline),
        "migrated_inventory": inventory_categories(migrated),
        "migration_guard": migration_guard,
        "native_ready": False,
        "rolled_back": False,
        "bridges": {
            "model_access": {"state": "unchecked"},
            "delegation": delegation,
        },
        "semantic_content_retained": False,
        "private_database_read": False,
    }


def _recovery_required_marker(
    identifier: str,
    *,
    previous: OfficialReleaseSelection,
    candidate: OfficialInstallation,
    baseline_inventory: dict[str, dict[str, Any]],
    migrated_inventory: dict[str, dict[str, Any]],
    migration_guard: dict[str, Any],
) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": "1",
        "kind": "design-studio-official-native-update",
        "update_id": identifier,
        "phase": "recovery_required",
        "created_at": now,
        "updated_at": now,
        "backup_directory": f"{UPDATE_BACKUPS}/official-update-{identifier}",
        "previous_release": release_identity(previous.release),
        "candidate_release": release_identity(candidate.release),
        "baseline_inventory": baseline_inventory,
        "migrated_inventory": migrated_inventory,
        "migration_guard": migration_guard,
        "native_ready": False,
        "rolled_back": False,
        "bridges": {
            "model_access": {"state": "unchecked"},
            "delegation": {"state": "unchecked"},
        },
        "semantic_content_retained": False,
        "private_database_read": False,
    }


def _live_bridge_results(root: Path, delegation: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads((root / "bridge-capabilities.json").read_text(encoding="utf-8"))
        model = payload.get("model_access") if isinstance(payload, dict) else None
        if not isinstance(model, dict) or model.get("state") not in {"ready", "degraded", "disabled"}:
            raise ValueError("model bridge status unavailable")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        model = {"state": "degraded", "reason": "post_update_handshake_unavailable"}
    return {"model_access": model, "delegation": delegation}


def _resume_previous_writer(
    root: Path,
    *,
    identifier: str,
    workspace_id: str,
    control: Callable[[str, str], dict[str, Any]],
) -> None:
    release_native_host(root, cutover_id=identifier)
    readiness = control("prewarm", workspace_id)
    if readiness.get("ready") is not True:
        quiesce_native_host(root, cutover_id=identifier)
        raise OfficialUpdateError(
            "the previous native OpenDesign writer did not become ready"
        )


def _read_marker_for_recovery(root: Path) -> dict[str, Any]:
    from official_update_state import read_update_state

    state = read_update_state(root)
    if state is None:
        raise OfficialUpdateError("official update marker disappeared during recovery")
    return state


def _write_backup_evidence(backup: Path, state: dict[str, Any]) -> None:
    atomic_write_json(backup / "update-evidence.json", state)


def _sidecar_control(operation: str, workspace_id: str) -> dict[str, Any]:
    repository = str(REPOSITORY_ROOT)
    import sys

    if repository not in sys.path:
        sys.path.insert(0, repository)
    from core.api.sidecar_control import request_sidecar_control

    return request_sidecar_control(
        REPOSITORY_ROOT,
        operation=operation,
        workspace_id=workspace_id,
        app_id="design-studio",
        timeout_seconds=60.0,
    )


__all__ = ["OfficialUpdateError", "perform_official_update"]
