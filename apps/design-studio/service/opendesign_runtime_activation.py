"""Atomic same-generation runtime/overlay activation with restart rollback."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import fcntl
import os
from pathlib import Path
import stat
import time
from typing import Callable, Mapping

from opendesign_generation_control import (
    load_runtime_activation_journal,
    load_runtime_generation_control,
    write_generation_control,
    write_runtime_activation_journal,
)
from opendesign_generation_model import (
    GenerationControl,
    LaunchSelection,
    RuntimeActivationJournal,
    reconcile_runtime_activation,
)


class RuntimeActivationError(RuntimeError):
    """Raised when runtime activation cannot become ready or roll back safely."""


@dataclass(frozen=True)
class RuntimeActivationOutcome:
    control: GenerationControl
    runtime_activation_id: str
    activated: bool
    rolled_back: bool
    readiness: dict[str, object]


Restart = Callable[[], Mapping[str, object]]


def activate_runtime_binding(
    root: Path,
    *,
    target_runtime_artifact_sha256: str,
    target_web_overlay_sha256: str,
    runtime_activation_id: str,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
    restart_sidecars: Restart,
    now: Callable[[], str] | None = None,
) -> RuntimeActivationOutcome:
    timestamp = now or _utc_now
    _ensure_layout(root)
    recover_runtime_activation(
        root,
        verified_artifacts=verified_artifacts,
        verified_overlays=verified_overlays,
        restart_sidecars=restart_sidecars,
        now=timestamp,
    )
    with _activation_lock(root):
        control = load_runtime_generation_control(
            root,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        source = control.active
        target = LaunchSelection(
            target_runtime_artifact_sha256,
            target_web_overlay_sha256,
            source.od_version,
            source.data_generation,
        )
        if source == target:
            raise RuntimeActivationError("runtime binding is already active")
        prepared = RuntimeActivationJournal(
            runtime_activation_id,
            "prepared",
            source,
            target,
            {},
            None,
            timestamp(),
            timestamp(),
        )
        write_runtime_activation_journal(
            root,
            prepared,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        cutover = _control(target, source, runtime_activation_id, timestamp())
        write_generation_control(
            root,
            cutover,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
    try:
        readiness = _restart(restart_sidecars)
    except Exception as candidate_error:
        return _rollback(
            root,
            journal=prepared,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
            restart_sidecars=restart_sidecars,
            timestamp=timestamp,
            candidate_error=candidate_error,
        )
    final_control, final_journal = _complete_after_restart(
        root,
        activation_id=runtime_activation_id,
        state="ready_committed",
        readiness=readiness,
        error=None,
        verified_artifacts=verified_artifacts,
        verified_overlays=verified_overlays,
        timestamp=timestamp,
    )
    return RuntimeActivationOutcome(final_control, runtime_activation_id, True, False, final_journal.readiness)


def retry_runtime_activation_candidate(
    root: Path,
    *,
    runtime_activation_id: str,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
    restart_sidecars: Restart,
    now: Callable[[], str] | None = None,
) -> RuntimeActivationOutcome:
    """Resume the exact candidate after a crash-safe rollback could not become ready."""
    timestamp = now or _utc_now
    with _activation_lock(root):
        control = load_runtime_generation_control(
            root,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        journal = load_runtime_activation_journal(
            root,
            runtime_activation_id,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        state = reconcile_runtime_activation(control, journal)
        if state != "rollback_restart_pending":
            raise RuntimeActivationError("only a rollback-pending activation candidate can be resumed")
        prepared = _journal(journal, "prepared", {}, None, timestamp())
        write_runtime_activation_journal(
            root,
            prepared,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        cutover = _control(journal.target, journal.source, runtime_activation_id, timestamp())
        write_generation_control(
            root,
            cutover,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
    try:
        readiness = _restart(restart_sidecars)
    except Exception as candidate_error:
        return _rollback(
            root,
            journal=prepared,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
            restart_sidecars=restart_sidecars,
            timestamp=timestamp,
            candidate_error=candidate_error,
        )
    final_control, final_journal = _complete_after_restart(
        root,
        activation_id=runtime_activation_id,
        state="ready_committed",
        readiness=readiness,
        error=None,
        verified_artifacts=verified_artifacts,
        verified_overlays=verified_overlays,
        timestamp=timestamp,
    )
    return RuntimeActivationOutcome(
        final_control,
        runtime_activation_id,
        True,
        False,
        final_journal.readiness,
    )


def recover_runtime_activation(
    root: Path,
    *,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
    restart_sidecars: Restart,
    now: Callable[[], str] | None = None,
) -> RuntimeActivationOutcome | None:
    _ensure_layout(root)
    timestamp = now or _utc_now
    with _activation_lock(root):
        control = load_runtime_generation_control(
            root,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        if control.runtime_activation_id is None:
            return None
        journal = load_runtime_activation_journal(
            root,
            control.runtime_activation_id,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        state = reconcile_runtime_activation(control, journal)
        if state in {"ready_committed", "rolled_back"}:
            return RuntimeActivationOutcome(
                control,
                journal.runtime_activation_id,
                state == "ready_committed",
                state == "rolled_back",
                journal.readiness,
            )
    if state == "activation_committed_readiness_pending":
        try:
            readiness = _restart(restart_sidecars)
        except Exception as candidate_error:
            return _rollback(
                root,
                journal=journal,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
                restart_sidecars=restart_sidecars,
                timestamp=timestamp,
                candidate_error=candidate_error,
            )
        final_control, final_journal = _complete_after_restart(
            root,
            activation_id=journal.runtime_activation_id,
            state="ready_committed",
            readiness=readiness,
            error=None,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
            timestamp=timestamp,
        )
        return RuntimeActivationOutcome(
            final_control, journal.runtime_activation_id, True, False, final_journal.readiness
        )
    if state in {"rollback_committed_journal_pending", "rollback_restart_pending"}:
        readiness = _restart(restart_sidecars)
        final_control, final_journal = _complete_after_restart(
            root,
            activation_id=journal.runtime_activation_id,
            state="rolled_back",
            readiness={"rollback": readiness},
            error=journal.error or "candidate_restart_failed:recovered",
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
            timestamp=timestamp,
        )
        return RuntimeActivationOutcome(
            final_control, journal.runtime_activation_id, False, True, final_journal.readiness
        )
    return None


def finalize_runtime_activation_after_verified_sidecar_start(
    root: Path,
    *,
    readiness: Mapping[str, object],
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
    now: Callable[[], str] | None = None,
) -> RuntimeActivationOutcome | None:
    verified_readiness = _verified_readiness(readiness)
    timestamp = now or _utc_now
    with _activation_lock(root):
        control = load_runtime_generation_control(
            root,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        if control.runtime_activation_id is None:
            return None
        journal = load_runtime_activation_journal(
            root,
            control.runtime_activation_id,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        state = reconcile_runtime_activation(control, journal)
        if state in {"ready_committed", "rolled_back"}:
            return RuntimeActivationOutcome(
                control,
                journal.runtime_activation_id,
                state == "ready_committed",
                state == "rolled_back",
                journal.readiness,
            )
        rolled_back = state in {"rollback_committed_journal_pending", "rollback_restart_pending"}
        if state != "activation_committed_readiness_pending" and not rolled_back:
            raise RuntimeActivationError("verified sidecar cannot reconcile runtime activation")
        completed = _journal(
            journal,
            "rolled_back" if rolled_back else "ready_committed",
            {"rollback": verified_readiness} if rolled_back else verified_readiness,
            (journal.error or "candidate_restart_failed:verified_recovery") if rolled_back else None,
            timestamp(),
        )
        write_runtime_activation_journal(
            root,
            completed,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        return RuntimeActivationOutcome(
            control,
            journal.runtime_activation_id,
            not rolled_back,
            rolled_back,
            completed.readiness,
        )


def runtime_activation_recovery_state(
    root: Path,
    *,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
) -> str | None:
    _ensure_layout(root)
    with _activation_lock(root):
        control = load_runtime_generation_control(
            root,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        if control.runtime_activation_id is None:
            return None
        journal = load_runtime_activation_journal(
            root,
            control.runtime_activation_id,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        return reconcile_runtime_activation(control, journal)


def _rollback(
    root: Path,
    *,
    journal: RuntimeActivationJournal,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
    restart_sidecars: Restart,
    timestamp: Callable[[], str],
    candidate_error: Exception,
) -> RuntimeActivationOutcome:
    rollback = _control(journal.source, journal.target, journal.runtime_activation_id, timestamp())
    with _activation_lock(root):
        current_control = load_runtime_generation_control(
            root,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        current_journal = load_runtime_activation_journal(
            root,
            journal.runtime_activation_id,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        current_state = reconcile_runtime_activation(current_control, current_journal)
        if current_state in {"ready_committed", "rolled_back"}:
            return RuntimeActivationOutcome(
                current_control,
                current_journal.runtime_activation_id,
                current_state == "ready_committed",
                current_state == "rolled_back",
                current_journal.readiness,
            )
        write_generation_control(
            root,
            rollback,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
    safe_error = f"candidate_restart_failed:{type(candidate_error).__name__}"
    try:
        readiness = _restart(restart_sidecars)
    except Exception as rollback_error:
        pending = _journal(
            journal,
            "rollback_restart_pending",
            {"candidate": {"ready": False}, "rollback": {"ready": False}},
            f"{safe_error};rollback_restart_failed:{type(rollback_error).__name__}",
            timestamp(),
        )
        with _activation_lock(root):
            current_control = load_runtime_generation_control(
                root,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
            current_journal = load_runtime_activation_journal(
                root,
                journal.runtime_activation_id,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
            current_state = reconcile_runtime_activation(current_control, current_journal)
            if current_state in {"ready_committed", "rolled_back"}:
                return RuntimeActivationOutcome(
                    current_control,
                    current_journal.runtime_activation_id,
                    current_state == "ready_committed",
                    current_state == "rolled_back",
                    current_journal.readiness,
                )
            write_runtime_activation_journal(
                root,
                pending,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
        raise RuntimeActivationError(pending.error or "runtime rollback failed") from rollback_error
    final_control, final_journal = _complete_after_restart(
        root,
        activation_id=journal.runtime_activation_id,
        state="rolled_back",
        readiness={"candidate": {"ready": False}, "rollback": readiness},
        error=safe_error,
        verified_artifacts=verified_artifacts,
        verified_overlays=verified_overlays,
        timestamp=timestamp,
    )
    return RuntimeActivationOutcome(
        final_control, journal.runtime_activation_id, False, True, final_journal.readiness
    )


def _complete_after_restart(
    root: Path,
    *,
    activation_id: str,
    state: str,
    readiness: dict[str, object],
    error: str | None,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
    timestamp: Callable[[], str],
) -> tuple[GenerationControl, RuntimeActivationJournal]:
    with _activation_lock(root):
        control = load_runtime_generation_control(
            root,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        journal = load_runtime_activation_journal(
            root,
            activation_id,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        observed = reconcile_runtime_activation(control, journal)
        if observed in {"ready_committed", "rolled_back"}:
            return control, journal
        completed = _journal(journal, state, readiness, error, timestamp())
        write_runtime_activation_journal(
            root,
            completed,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        return control, completed


def _control(
    active: LaunchSelection,
    previous: LaunchSelection,
    activation_id: str,
    updated_at: str,
) -> GenerationControl:
    return GenerationControl(
        active=active,
        previous_release=None,
        previous_web=None,
        migration_id=None,
        web_activation_id=None,
        updated_at=updated_at,
        previous_runtime=previous,
        runtime_activation_id=activation_id,
    )


def _restart(callback: Restart) -> dict[str, object]:
    started = time.monotonic()
    result = callback()
    if result.get("ready") is not True:
        raise RuntimeActivationError("sidecar readiness failed")
    count = result.get("service_count")
    return {
        "ready": True,
        "duration_seconds": round(time.monotonic() - started, 6),
        "service_count": count if isinstance(count, int) and count >= 0 else 0,
        **({"browser_remount_event_emitted": True} if result.get("browser_remount_event_emitted") is True else {}),
    }


def _verified_readiness(readiness: Mapping[str, object]) -> dict[str, object]:
    count = readiness.get("service_count")
    if readiness.get("ready") is not True or not isinstance(count, int) or count < 1:
        raise RuntimeActivationError("verified sidecar readiness is required")
    return {"ready": True, "service_count": count, "readiness_source": "sidecar_health"}


def _journal(
    source: RuntimeActivationJournal,
    state: str,
    readiness: dict[str, object],
    error: str | None,
    updated_at: str,
) -> RuntimeActivationJournal:
    return RuntimeActivationJournal(
        source.runtime_activation_id,
        state,
        source.source,
        source.target,
        readiness,
        error,
        source.created_at,
        updated_at,
    )


def _ensure_layout(root: Path) -> None:
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise RuntimeActivationError("OpenDesign generation root must be a real directory")
    path = root / "runtime-activations"
    if not path.exists():
        path.mkdir(mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise RuntimeActivationError("runtime-activations must be a real directory")


@contextmanager
def _activation_lock(root: Path):
    lock_path = Path(root) / ".runtime-activation.lock"
    if lock_path.is_symlink():
        raise RuntimeActivationError("runtime activation lock must not be a symlink")
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeActivationError("runtime activation lock must be a regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
