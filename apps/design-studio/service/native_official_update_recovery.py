"""Crash-safe recovery for an interrupted official OpenDesign update."""

from __future__ import annotations

from contextlib import suppress
import json
import os
from pathlib import Path
import shutil
import stat
from typing import Any, Callable

from managed_sidecar_evidence import (
    require_verified_writer_ready,
    require_verified_writer_status,
    require_verified_writer_stop,
)
from native_cutover_files import (
    atomic_write_json,
    copy_verified_tree,
    fsync_directory,
    make_tree_private_writable,
    make_tree_read_only,
    real_directory,
)
from native_cutover_quiescence import (
    QUIESCE_FILE,
    quiesce_native_host,
    read_quiescence,
    release_native_host,
)
from native_host_status import read_live_model_bridge
from official_bridge_contracts import (
    read_delegation_contract,
    validate_delegation_status,
    write_bridge_contracts,
)
from official_oci_validation import reject_duplicate_pairs
from official_release_selection import (
    SELECTION_FILE,
    read_release_selection,
    validate_release_selection_payload,
)
from official_update_journal import (
    clear_update_journal,
    read_update_journal,
    write_update_journal,
)
from official_update_lock import official_update_lock
from official_update_state import (
    OfficialUpdateError,
    read_update_state,
    utc_now,
    write_update_state,
)


Control = Callable[[str, str], dict[str, Any]]
WRITER_STOP_ATTEMPTS = 3
TERMINAL_PHASES = {"committed", "rolled_back"}


def recover_official_update(
    app_data_root: Path,
    *,
    workspace_id: str,
    sidecar_control: Control,
) -> dict[str, Any]:
    """Explicitly recover one interrupted transaction and restart its writer."""
    root = real_directory(app_data_root, label="Design Studio data root")
    with official_update_lock(root) as acquired:
        if not acquired:
            raise OfficialUpdateError("another official update transaction is active")
        return recover_official_update_locked(
            root,
            workspace_id=workspace_id,
            sidecar_control=sidecar_control,
            managed_writer_stopped=False,
            resume_writer=True,
        )


def recover_official_update_locked(
    app_data_root: Path,
    *,
    workspace_id: str,
    sidecar_control: Control | None,
    managed_writer_stopped: bool,
    resume_writer: bool,
) -> dict[str, Any]:
    """Recover while the caller holds the per-workspace official-update lock."""
    root = real_directory(app_data_root, label="Design Studio data root")
    state = read_update_state(root)
    journal = read_update_journal(root)
    if state is None:
        if journal is not None:
            raise OfficialUpdateError(
                "official update cutover journal has no matching transaction marker"
            )
        return {"recovered": False, "update": None}

    identifier = state["update_id"]
    if journal is not None and journal["update_id"] != identifier:
        raise OfficialUpdateError("official update cutover journal identity mismatch")

    if state["phase"] in TERMINAL_PHASES:
        cleaned = _finalize_terminal_transaction(root, state)
        resumed = False
        if resume_writer and not state["native_ready"]:
            if sidecar_control is None:
                raise OfficialUpdateError("official update recovery has no Core control channel")
            state = _resume_recovered_writer(
                root,
                state,
                workspace_id=workspace_id,
                control=sidecar_control,
            )
            resumed = True
        # `host_prepare` runs before sandbox preparation and process spawn. It
        # may clear transaction residue, but it cannot claim runtime readiness.
        backup = _optional_backup(root, state)
        if backup is not None and resumed:
            _finalize_backup(backup, state)
        prepared_backup = False
        if (
            backup is not None
            and not resume_writer
            and not state["native_ready"]
            and not cleaned
            and backup.stat().st_mode & 0o222
        ):
            _finalize_backup(backup, state)
            prepared_backup = True
        return {
            "recovered": cleaned or resumed or prepared_backup,
            "update": state,
        }

    quiesce_native_host(root, cutover_id=identifier)
    if not managed_writer_stopped:
        if sidecar_control is None:
            raise OfficialUpdateError("official update recovery has no Core control channel")
        confirm_writer_stopped(
            root,
            identifier=identifier,
            workspace_id=workspace_id,
            control=sidecar_control,
        )

    quarantine_active = (
        state.get("bridges", {}).get("model_access", {}).get("reason")
        == "core_sidecar_quarantine"
    )

    backup = _optional_backup(root, state)
    if backup is None:
        previous = read_release_selection(root)
        if _release_identity(previous.release) != state["previous_release"]:
            raise OfficialUpdateError(
                "official update recovery has no verified previous selection backup"
            )
        real_directory(root / "opendesign-native", label="native OpenDesign data")
        previous_delegation = read_delegation_contract(root, previous.release)
    else:
        previous = validate_release_selection_payload(
            _read_private_json(backup / "previous-selection.json")
        )
        if _release_identity(previous.release) != state["previous_release"]:
            raise OfficialUpdateError(
                "official update previous selection backup does not match its marker"
            )
        previous_delegation = _read_previous_delegation(
            root,
            backup=backup,
            release=previous.release,
        )
        _restore_native_data(root, backup=backup, identifier=identifier)
        atomic_write_json(root / SELECTION_FILE, previous.payload)
        read_release_selection(root)
        write_bridge_contracts(
            root,
            previous.release,
            delegation=previous_delegation,
        )

    state.update(
        {
            "phase": "rolled_back",
            "updated_at": utc_now(),
            "native_ready": False,
            "rolled_back": True,
            "bridges": {
                "model_access": {"state": "unchecked"},
                "delegation": previous_delegation,
            },
        }
    )
    write_update_state(root, state)
    clear_update_journal(root, update_id=identifier)
    _cleanup_transaction_paths(root, identifier=identifier)
    _release_matching_quiescence(root, identifier=identifier)

    if resume_writer:
        if sidecar_control is None:
            raise OfficialUpdateError("official update recovery has no Core control channel")
        state = _resume_recovered_writer(
            root,
            state,
            workspace_id=workspace_id,
            control=sidecar_control,
            release_quarantine=quarantine_active,
        )
    if backup is not None:
        _finalize_backup(backup, state)
    return {"recovered": True, "update": state}


def confirm_writer_stopped(
    root: Path,
    *,
    identifier: str,
    workspace_id: str,
    control: Control,
) -> None:
    """Require canonical Core evidence for the exact bound writer service."""
    try:
        quiesce_native_host(root, cutover_id=identifier)
    except Exception as error:
        raise OfficialUpdateError(
            "official OpenDesign update recovery could not restore quiescence"
        ) from error
    last_error: Exception | None = None
    for _attempt in range(WRITER_STOP_ATTEMPTS):
        try:
            response = control("stop", workspace_id)
            require_verified_writer_stop(
                response,
                workspace_id=workspace_id,
                app_data_root=root,
            )
        except Exception as error:
            last_error = error
            continue
        return
    try:
        status = control("status", workspace_id)
        require_verified_writer_status(
            status,
            workspace_id=workspace_id,
            app_data_root=root,
        )
    except Exception as error:
        last_error = error
    else:
        return
    raise OfficialUpdateError(
        "official OpenDesign update recovery could not confirm the writer stop"
    ) from last_error


def _restore_native_data(root: Path, *, backup: Path, identifier: str) -> None:
    backup_native = real_directory(
        backup / "native-data",
        label="official update native data backup",
    )
    native = root / "opendesign-native"
    staging = root / f".{identifier}.recovery-data"
    failed = root / f".{identifier}.failed-data"
    _remove_tree(staging)
    copy_verified_tree(backup_native, staging)
    make_tree_private_writable(staging)

    if native.exists() or native.is_symlink():
        if native.is_symlink() or not native.is_dir():
            raise OfficialUpdateError("native OpenDesign recovery target is unsafe")
        _remove_tree(failed)
        write_update_journal(
            root,
            update_id=identifier,
            step="rollback_retire_candidate_intent",
        )
        os.replace(native, failed)
        _sync_rename(root, root)
    write_update_journal(root, update_id=identifier, step="candidate_retired")
    write_update_journal(
        root,
        update_id=identifier,
        step="rollback_restore_previous_intent",
    )
    os.replace(staging, native)
    _sync_rename(root, root)
    write_update_journal(root, update_id=identifier, step="previous_restored")
    make_tree_private_writable(native)


def _resume_recovered_writer(
    root: Path,
    state: dict[str, Any],
    *,
    workspace_id: str,
    control: Control,
    release_quarantine: bool = False,
) -> dict[str, Any]:
    identifier = state["update_id"]
    terminal_phase = state["phase"]
    committed = terminal_phase == "committed"
    try:
        if release_quarantine:
            released = control("release_quarantine", workspace_id)
            if not isinstance(released, dict) or released.get("quarantined") is not False:
                raise OfficialUpdateError("Core did not release sidecar quarantine")
        readiness = control("prewarm", workspace_id)
        try:
            require_verified_writer_ready(
                readiness,
                workspace_id=workspace_id,
                app_data_root=root,
            )
        except ValueError as error:
            raise OfficialUpdateError(
                "the selected native OpenDesign writer did not become ready"
            ) from error
    except Exception as error:
        quiesce_native_host(root, cutover_id=identifier)
        state.update(
            {
                "phase": "committed" if committed else "recovery_required",
                "updated_at": utc_now(),
                "native_ready": False,
                "rolled_back": False,
            }
        )
        write_update_state(root, state)
        raise OfficialUpdateError(
            "official OpenDesign update recovery requires operator intervention"
        ) from error
    state.update(
        {
            "phase": terminal_phase,
            "updated_at": utc_now(),
            "native_ready": True,
            "rolled_back": terminal_phase == "rolled_back",
        }
    )
    if terminal_phase == "committed":
        state["bridges"]["model_access"] = read_live_model_bridge(
            root,
            manifest_digest=state["candidate_release"]["manifest_digest"],
            unavailable_reason="post_update_handshake_unavailable",
            wait_seconds=2.0,
        )
    write_update_state(root, state)
    return state


def _finalize_terminal_transaction(root: Path, state: dict[str, Any]) -> bool:
    identifier = state["update_id"]
    real_directory(root / "opendesign-native", label="native OpenDesign data")
    paths = (
        root / f".{identifier}.work",
        root / f".{identifier}.backup",
        root / f".{identifier}.recovery-data",
        root / f".{identifier}.failed-data",
    )
    quiescence = root / QUIESCE_FILE
    residue = read_update_journal(root) is not None or any(
        path.exists() or path.is_symlink() for path in paths
    )
    if quiescence.exists() or quiescence.is_symlink():
        marker = read_quiescence(quiescence)
        if marker["cutover_id"] != identifier:
            raise OfficialUpdateError("another transaction owns native host quiescence")
        residue = True
    if not residue:
        return False
    clear_update_journal(root, update_id=identifier)
    _cleanup_transaction_paths(root, identifier=identifier)
    _release_matching_quiescence(root, identifier=identifier)
    backup = _optional_backup(root, state)
    if backup is not None:
        _finalize_backup(backup, state)
    return True


def _optional_backup(root: Path, state: dict[str, Any]) -> Path | None:
    backup = root / state["backup_directory"]
    if not backup.exists() and not backup.is_symlink():
        return None
    return real_directory(backup, label="official update backup")


def _read_private_json(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise OfficialUpdateError("official update backup metadata is unsafe")
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise OfficialUpdateError("official update backup metadata is unreadable") from error
    if not isinstance(payload, dict):
        raise OfficialUpdateError("official update backup metadata is invalid")
    return payload


def _read_previous_delegation(
    root: Path,
    *,
    backup: Path,
    release: Any,
) -> dict[str, Any]:
    path = backup / "previous-delegation.json"
    if not path.exists() and not path.is_symlink():
        # Backups created before the durable journal schema did not carry this
        # optional evidence. Degrade only the bridge, never data recovery.
        return read_delegation_contract(root, release)
    return validate_delegation_status(_read_private_json(path))


def _cleanup_transaction_paths(root: Path, *, identifier: str) -> None:
    for path in (
        root / f".{identifier}.work",
        root / f".{identifier}.backup",
        root / f".{identifier}.recovery-data",
        root / f".{identifier}.failed-data",
    ):
        _remove_tree(path)
    fsync_directory(root)


def _remove_tree(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    try:
        metadata = path.lstat()
    except OSError as error:
        raise OfficialUpdateError("official update transaction path is unavailable") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise OfficialUpdateError("official update transaction path is unsafe")
    make_tree_private_writable(path)
    shutil.rmtree(path)
    fsync_directory(path.parent)


def _release_matching_quiescence(root: Path, *, identifier: str) -> None:
    path = root / QUIESCE_FILE
    if not path.exists() and not path.is_symlink():
        return
    marker = read_quiescence(path)
    if marker["cutover_id"] != identifier:
        raise OfficialUpdateError("another transaction owns native host quiescence")
    release_native_host(root, cutover_id=identifier)


def _write_backup_evidence(backup: Path, state: dict[str, Any]) -> None:
    atomic_write_json(backup / "update-evidence.json", state)


def _finalize_backup(backup: Path, state: dict[str, Any]) -> None:
    """Refresh evidence under the lock, then restore immutable backup modes."""
    with suppress(Exception):
        make_tree_private_writable(backup)
        _write_backup_evidence(backup, state)
    make_tree_read_only(backup)


def _release_identity(release: Any) -> dict[str, str]:
    return {
        "version": str(release.version),
        "manifest_digest": str(release.manifest_digest),
    }


def _sync_rename(source_parent: Path, destination_parent: Path) -> None:
    fsync_directory(source_parent)
    if destination_parent != source_parent:
        fsync_directory(destination_parent)


__all__ = [
    "confirm_writer_stopped",
    "recover_official_update",
    "recover_official_update_locked",
]
