"""Install and transactionally select a user-chosen official OpenDesign update."""

from __future__ import annotations

from contextlib import suppress
import os
from pathlib import Path
import shutil
from typing import Any, Callable

from native_cutover_files import (
    atomic_write_json,
    copy_verified_tree,
    fsync_directory,
    fsync_tree,
    make_tree_read_only,
    real_directory,
)
from native_cutover_quiescence import quiesce_native_host, release_native_host
from managed_sidecar_evidence import require_verified_writer_ready
from native_host_status import read_live_model_bridge
from native_official_update_recovery import (
    confirm_writer_stopped,
    recover_official_update as _recover_official_update,
    recover_official_update_locked,
)
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
from official_update_journal import clear_update_journal, write_update_journal
from official_update_lock import official_update_lock


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
NATIVE_DATA_DIRECTORY = "opendesign-native"
QUARANTINE_ATTEMPTS = 3


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
    """Hold the workspace transaction lock through commit or safe rollback."""
    if confirmed is not True:
        raise OfficialUpdateError("explicit official update confirmation is required")
    root = real_directory(app_data_root, label="Design Studio data root")
    control = sidecar_control or _sidecar_control
    with official_update_lock(root) as acquired:
        if not acquired:
            raise OfficialUpdateError("another official update transaction is active")
        recover_official_update_locked(
            root,
            workspace_id=workspace_id,
            sidecar_control=control,
            managed_writer_stopped=False,
            resume_writer=True,
        )
        return _perform_official_update_locked(
            root,
            artifact_root,
            release_descriptor,
            workspace_id=workspace_id,
            update_id=update_id,
            install_runner=install_runner,
            verify_runner=verify_runner,
            inventory_runner=inventory_runner,
            delegation_probe=delegation_probe,
            control=control,
        )


def _perform_official_update_locked(
    app_data_root: Path,
    artifact_root: Path,
    release_descriptor: Path,
    *,
    workspace_id: str,
    update_id: str | None,
    install_runner: Callable[..., OfficialInstallation],
    verify_runner: Callable[..., OfficialInstallation],
    inventory_runner: Callable[..., dict[str, Any]],
    delegation_probe: Callable[..., dict[str, Any]],
    control: Callable[[str, str], dict[str, Any]],
) -> dict[str, Any]:
    """Migrate a stable copy and make one durable, irreversible commit decision."""
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
    previous_delegation = read_delegation_contract(root, previous.release)
    writer_stopped = False
    activation_attempted = False
    startup_attempted = False
    commit_decided = False
    backup: Path | None = None
    baseline_categories = empty_inventory_categories()
    migrated_categories = empty_inventory_categories()
    migration_guard = incomplete_migration_guard()
    marker = _preparing_marker(
        identifier,
        previous=previous,
        candidate=candidate_installation,
        baseline_inventory=baseline_categories,
        migrated_inventory=migrated_categories,
        migration_guard=migration_guard,
    )
    write_update_state(root, marker)
    work = root / f".{identifier}.work"
    try:
        quiesce_native_host(root, cutover_id=identifier)
        confirm_writer_stopped(
            root,
            identifier=identifier,
            workspace_id=workspace_id,
            control=control,
        )
        writer_stopped = True
        backup = _prepare_backup(
            root,
            native,
            previous,
            previous_delegation,
            identifier,
        )
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
        marker.update(
            {
                "updated_at": utc_now(),
                "baseline_inventory": baseline_categories,
                "migrated_inventory": migrated_categories,
                "migration_guard": migration_guard,
            }
        )
        write_update_state(root, marker)
        if migration_guard["state"] != "passed":
            removed_identities = [
                category
                for category, count in migration_guard["lost_identity_counts"].items()
                if count
            ]
            changed_content = [
                category
                for category, count in migration_guard["lost_content_counts"].items()
                if count
            ]
            if removed_identities:
                reason = (
                    "candidate migration removed protected native identities: "
                    + ", ".join(removed_identities)
                )
            else:
                reason = (
                    "candidate migration changed protected native content: "
                    + ", ".join(changed_content)
                )
            raise OfficialUpdateError(reason)
        delegation = _probe_delegation(
            candidate_installation,
            migrated_data=migrated_data,
            probe_data=probe_data,
            log_path=backup / "delegation-contract.log",
            delegation_probe=delegation_probe,
        )
        fsync_tree(migrated_data)
        marker = _marker(
            identifier,
            previous=previous,
            candidate=candidate_installation,
            baseline=baseline,
            migrated=migrated,
            migration_guard=migration_guard,
            delegation=delegation,
            created_at=marker["created_at"],
        )
        write_update_state(root, marker)
        retired = work / "retired-data"
        activation_attempted = True
        marker.update({"phase": "activating", "updated_at": utc_now()})
        write_update_state(root, marker)
        write_update_journal(
            root,
            update_id=identifier,
            step="retire_native_intent",
        )
        os.replace(native, retired)
        fsync_directory(root)
        fsync_directory(work)
        write_update_journal(root, update_id=identifier, step="native_retired")
        write_update_journal(
            root,
            update_id=identifier,
            step="activate_candidate_intent",
        )
        os.replace(migrated_data, native)
        fsync_directory(work)
        fsync_directory(root)
        write_update_journal(root, update_id=identifier, step="candidate_activated")
        write_release_selection(root, candidate)
        write_bridge_contracts(root, candidate, delegation=delegation)
        marker.update(
            {
                "phase": "committed",
                "updated_at": utc_now(),
                "native_ready": False,
            }
        )
        write_update_state(root, marker)
        commit_decided = True
        clear_update_journal(root, update_id=identifier)
        shutil.rmtree(work, ignore_errors=True)
        fsync_directory(root)
        release_native_host(root, cutover_id=identifier)
        startup_attempted = True
        readiness = control("prewarm", workspace_id)
        try:
            require_verified_writer_ready(
                readiness,
                workspace_id=workspace_id,
                app_data_root=root,
            )
        except ValueError as error:
            raise OfficialUpdateError(
                "the selected official OpenDesign release did not become ready"
            ) from error
        bridges = _live_bridge_results(
            root,
            delegation,
            manifest_digest=candidate.manifest_digest,
        )
        marker.update(
            {
                "updated_at": utc_now(),
                "native_ready": True,
                "bridges": bridges,
            }
        )
        write_update_state(root, marker)
        _write_backup_evidence(backup, marker)
        make_tree_read_only(backup)
        return {"update_applied": True, "update": marker}
    except Exception as error:
        if commit_decided:
            marker.update(
                {
                    "phase": "committed",
                    "updated_at": utc_now(),
                }
            )
            with suppress(Exception):
                write_update_state(root, marker)
            return {
                "update_applied": True,
                "update": marker,
                "error": (
                    "candidate_startup_failed"
                    if startup_attempted
                    else "committed_recovery_required"
                ),
            }
        if marker is not None:
            try:
                recovered = recover_official_update_locked(
                    root,
                    workspace_id=workspace_id,
                    sidecar_control=control,
                    managed_writer_stopped=writer_stopped,
                    resume_writer=True,
                )["update"]
            except Exception as recovery_error:
                try:
                    recovery = _write_recovery_required(
                        root,
                        marker,
                        identifier=identifier,
                        workspace_id=workspace_id,
                        control=control,
                    )
                except OfficialUpdateError as fence_error:
                    raise OfficialUpdateError(
                        "official OpenDesign update recovery requires operator intervention"
                    ) from fence_error
                if backup is not None:
                    with suppress(Exception):
                        _write_backup_evidence(backup, recovery)
                        make_tree_read_only(backup)
                raise OfficialUpdateError(
                    "official OpenDesign update recovery requires operator intervention"
                ) from recovery_error
            if activation_attempted:
                return {
                    "update_applied": False,
                    "update": recovered,
                    "error": "candidate_startup_failed",
                }
            if isinstance(error, (OfficialUpdateError, OfficialReleaseError)):
                raise
            raise OfficialUpdateError("official OpenDesign update failed safely") from error


def _prepare_backup(
    root: Path,
    native: Path,
    previous: OfficialReleaseSelection,
    previous_delegation: dict[str, Any],
    identifier: str,
) -> Path:
    backups = real_directory(
        root / UPDATE_BACKUPS,
        label="official update backup root",
        create=True,
    )
    backup = backups / f"official-update-{identifier}"
    staging = root / f".{identifier}.backup"
    if (
        backup.exists()
        or backup.is_symlink()
        or staging.exists()
        or staging.is_symlink()
    ):
        raise OfficialUpdateError("official update backup already exists")
    staging.mkdir(mode=0o700)
    copy_verified_tree(native, staging / "native-data")
    atomic_write_json(staging / "previous-selection.json", previous.payload)
    atomic_write_json(staging / "previous-delegation.json", previous_delegation)
    fsync_tree(staging)
    os.replace(staging, backup)
    fsync_directory(root)
    fsync_directory(backups)
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


def _marker(
    identifier: str,
    *,
    previous: OfficialReleaseSelection,
    candidate: OfficialInstallation,
    baseline: dict[str, Any],
    migrated: dict[str, Any],
    migration_guard: dict[str, Any],
    delegation: dict[str, Any],
    created_at: str | None = None,
) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": "1",
        "kind": "design-studio-official-native-update",
        "update_id": identifier,
        "phase": "prepared",
        "created_at": created_at or now,
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


def _preparing_marker(
    identifier: str,
    *,
    previous: OfficialReleaseSelection,
    candidate: OfficialInstallation,
    baseline_inventory: dict[str, dict[str, Any]],
    migrated_inventory: dict[str, dict[str, Any]],
    migration_guard: dict[str, Any],
) -> dict[str, Any]:
    marker = _recovery_required_marker(
        identifier,
        previous=previous,
        candidate=candidate,
        baseline_inventory=baseline_inventory,
        migrated_inventory=migrated_inventory,
        migration_guard=migration_guard,
    )
    marker["phase"] = "preparing"
    return marker


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


def _live_bridge_results(
    root: Path,
    delegation: dict[str, Any],
    *,
    manifest_digest: str,
) -> dict[str, Any]:
    model = read_live_model_bridge(
        root,
        manifest_digest=manifest_digest,
        unavailable_reason="post_update_handshake_unavailable",
        wait_seconds=2.0,
    )
    return {"model_access": model, "delegation": delegation}


def _write_recovery_required(
    root: Path,
    state: dict[str, Any] | None,
    *,
    identifier: str,
    workspace_id: str,
    control: Callable[[str, str], dict[str, Any]],
    delegation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist recovery after either a confirmed stop or durable Core quarantine."""
    quarantine: dict[str, Any] | None = None
    try:
        confirm_writer_stopped(
            root,
            identifier=identifier,
            workspace_id=workspace_id,
            control=control,
        )
    except OfficialUpdateError as stop_error:
        quarantine = _establish_core_quarantine(
            control,
            workspace_id=workspace_id,
            stop_error=stop_error,
        )
    if state is None:
        state = _read_marker_for_recovery(root)
    state.update(
        {
            "phase": "recovery_required",
            "updated_at": utc_now(),
            "native_ready": False,
            "rolled_back": False,
        }
    )
    if delegation is not None:
        state["bridges"] = {
            "model_access": {"state": "unchecked"},
            "delegation": delegation,
        }
    if quarantine is not None:
        state["bridges"]["model_access"] = {
            "state": "disabled",
            "reason": "core_sidecar_quarantine",
        }
    try:
        write_update_state(root, state)
    except Exception as error:
        raise OfficialUpdateError(
            "official OpenDesign update recovery established a safety fence but its "
            "recovery_required marker could not be recorded"
        ) from error
    return state


def _establish_core_quarantine(
    control: Callable[[str, str], dict[str, Any]],
    *,
    workspace_id: str,
    stop_error: OfficialUpdateError,
) -> dict[str, Any]:
    """Retry the idempotent Core fence when a completed response may be lost."""
    required = {
        "quarantined",
        "persistent",
        "proxy_revoked",
        "browser_sessions_revoked",
        "model_access_revoked",
    }
    last_error: Exception = stop_error
    for _attempt in range(QUARANTINE_ATTEMPTS):
        try:
            response = control("quarantine", workspace_id)
        except Exception as error:
            last_error = error
            continue
        if isinstance(response, dict) and all(
            response.get(field) is True for field in required
        ):
            return response
        last_error = OfficialUpdateError(
            "Core returned incomplete sidecar quarantine evidence"
        )
    raise OfficialUpdateError(
        "official OpenDesign update recovery could not establish a durable "
        "Core sidecar quarantine"
    ) from last_error


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


def recover_interrupted_official_update(
    app_data_root: Path,
    *,
    workspace_id: str,
    sidecar_control: Callable[[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the explicit operator recovery action under the workspace lock."""
    return _recover_official_update(
        app_data_root,
        workspace_id=workspace_id,
        sidecar_control=sidecar_control or _sidecar_control,
    )


__all__ = [
    "OfficialUpdateError",
    "perform_official_update",
    "recover_interrupted_official_update",
]
