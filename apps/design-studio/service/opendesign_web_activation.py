"""Atomic web-only OpenDesign activation with scoped restart rollback."""

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
    load_generation_control,
    load_web_activation_journal,
    write_generation_control,
    write_web_activation_journal,
)
from opendesign_generation_model import (
    GenerationControl,
    LaunchSelection,
    WebActivationJournal,
    reconcile_web_activation,
)


class WebActivationError(RuntimeError):
    """Raised when web activation and/or its recovery restart fails."""


@dataclass(frozen=True)
class WebActivationOutcome:
    control: GenerationControl
    web_activation_id: str
    activated: bool
    rolled_back: bool
    readiness: dict[str, object]


Restart = Callable[[], Mapping[str, object]]


def activate_web_overlay(
    root: Path,
    *,
    target_web_overlay_sha256: str,
    web_activation_id: str,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
    restart_sidecars: Restart,
    now: Callable[[], str] | None = None,
) -> WebActivationOutcome:
    timestamp = now or _utc_now
    recover_web_activation(
        root,
        verified_artifacts=verified_artifacts,
        verified_overlays=verified_overlays,
        restart_sidecars=restart_sidecars,
        now=timestamp,
    )
    with _web_activation_lock(root):
        control = load_generation_control(
            root,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        if control.web_activation_id is not None:
            current_journal = load_web_activation_journal(
                root,
                control.web_activation_id,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
            current_state = reconcile_web_activation(control, current_journal)
            if current_state not in {"ready_committed", "rolled_back"}:
                raise WebActivationError("previous web activation recovery is incomplete")
        source = control.active
        target = LaunchSelection(
            runtime_artifact_sha256=source.runtime_artifact_sha256,
            web_overlay_sha256=target_web_overlay_sha256,
            od_version=source.od_version,
            data_generation=source.data_generation,
        )
        if source == target:
            raise WebActivationError("web overlay is already active")
        prepared = WebActivationJournal(
            web_activation_id=web_activation_id,
            state="prepared",
            source=source,
            target=target,
            readiness={},
            error=None,
            created_at=timestamp(),
            updated_at=timestamp(),
        )
        write_web_activation_journal(
            root,
            prepared,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        cutover = GenerationControl(
            active=target,
            previous_release=control.previous_release,
            previous_web=source,
            migration_id=control.migration_id,
            web_activation_id=web_activation_id,
            updated_at=timestamp(),
        )
        write_generation_control(
            root,
            cutover,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        try:
            readiness = _restart(restart_sidecars)
        except Exception as candidate_error:
            return _rollback_after_failed_restart(
                root,
                original=control,
                candidate=target,
                journal=prepared,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
                restart_sidecars=restart_sidecars,
                timestamp=timestamp,
                candidate_error=candidate_error,
            )
        committed = _journal_state(
            prepared,
            "ready_committed",
            readiness=readiness,
            error=None,
            updated_at=timestamp(),
        )
        write_web_activation_journal(
            root,
            committed,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        return WebActivationOutcome(cutover, web_activation_id, True, False, readiness)


def recover_web_activation(
    root: Path,
    *,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
    restart_sidecars: Restart,
    now: Callable[[], str] | None = None,
) -> WebActivationOutcome | None:
    timestamp = now or _utc_now
    with _web_activation_lock(root):
        control = load_generation_control(
            root,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        if control.web_activation_id is None:
            return None
        journal = load_web_activation_journal(
            root,
            control.web_activation_id,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        state = reconcile_web_activation(control, journal)
        if state in {"ready_committed", "rolled_back"}:
            return WebActivationOutcome(
                control,
                journal.web_activation_id,
                state == "ready_committed",
                state == "rolled_back",
                journal.readiness,
            )
        if state == "activation_committed_readiness_pending":
            try:
                readiness = _restart(restart_sidecars)
            except Exception as candidate_error:
                original = GenerationControl(
                    active=journal.source,
                    previous_release=control.previous_release,
                    previous_web=None,
                    migration_id=control.migration_id,
                    web_activation_id=None,
                    updated_at=timestamp(),
                )
                return _rollback_after_failed_restart(
                    root,
                    original=original,
                    candidate=journal.target,
                    journal=journal,
                    verified_artifacts=verified_artifacts,
                    verified_overlays=verified_overlays,
                    restart_sidecars=restart_sidecars,
                    timestamp=timestamp,
                    candidate_error=candidate_error,
                )
            committed = _journal_state(
                journal,
                "ready_committed",
                readiness=readiness,
                error=None,
                updated_at=timestamp(),
            )
            write_web_activation_journal(
                root,
                committed,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
            return WebActivationOutcome(control, journal.web_activation_id, True, False, readiness)
        if state in {"rollback_committed_journal_pending", "rollback_restart_pending"}:
            try:
                readiness = _restart(restart_sidecars)
            except Exception as rollback_error:
                safe_error = f"rollback_restart_failed:{type(rollback_error).__name__}:recovery"
                pending = _journal_state(
                    journal,
                    "rollback_restart_pending",
                    readiness={"rollback": {"ready": False}},
                    error=safe_error,
                    updated_at=timestamp(),
                )
                write_web_activation_journal(
                    root,
                    pending,
                    verified_artifacts=verified_artifacts,
                    verified_overlays=verified_overlays,
                )
                raise WebActivationError(safe_error) from rollback_error
            rolled_back = _journal_state(
                journal,
                "rolled_back",
                readiness={"rollback": readiness},
                error="candidate_restart_failed:recovered",
                updated_at=timestamp(),
            )
            write_web_activation_journal(
                root,
                rolled_back,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
            return WebActivationOutcome(control, journal.web_activation_id, False, True, readiness)
        return None


def finalize_web_activation_after_host_restart(
    root: Path,
    *,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
    now: Callable[[], str] | None = None,
) -> WebActivationOutcome | None:
    """Finalize a rollback whose process restart was supplied by backend restart recovery."""
    timestamp = now or _utc_now
    with _web_activation_lock(root):
        control = load_generation_control(
            root,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        if control.web_activation_id is None:
            return None
        journal = load_web_activation_journal(
            root,
            control.web_activation_id,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        state = reconcile_web_activation(control, journal)
        if state in {"ready_committed", "rolled_back"}:
            return WebActivationOutcome(
                control,
                journal.web_activation_id,
                state == "ready_committed",
                state == "rolled_back",
                journal.readiness,
            )
        if state not in {"rollback_committed_journal_pending", "rollback_restart_pending"}:
            raise WebActivationError("host restart cannot certify candidate activation readiness")
        readiness = {
            "rollback": {
                "ready": True,
                "service_count": 0,
                "restart_reason": "backend_restart",
            }
        }
        rolled_back = _journal_state(
            journal,
            "rolled_back",
            readiness=readiness,
            error=journal.error or "candidate_restart_failed:host_restart_recovery",
            updated_at=timestamp(),
        )
        write_web_activation_journal(
            root,
            rolled_back,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        return WebActivationOutcome(control, journal.web_activation_id, False, True, readiness)


def _rollback_after_failed_restart(
    root: Path,
    *,
    original: GenerationControl,
    candidate: LaunchSelection,
    journal: WebActivationJournal,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
    restart_sidecars: Restart,
    timestamp: Callable[[], str],
    candidate_error: Exception,
) -> WebActivationOutcome:
    rollback = GenerationControl(
        active=journal.source,
        previous_release=original.previous_release,
        previous_web=candidate,
        migration_id=original.migration_id,
        web_activation_id=journal.web_activation_id,
        updated_at=timestamp(),
    )
    write_generation_control(
        root,
        rollback,
        verified_artifacts=verified_artifacts,
        verified_overlays=verified_overlays,
    )
    try:
        rollback_readiness = _restart(restart_sidecars)
    except Exception as rollback_error:
        safe_error = (
            f"candidate_restart_failed:{type(candidate_error).__name__};"
            f"rollback_restart_failed:{type(rollback_error).__name__}"
        )
        pending = _journal_state(
            journal,
            "rollback_restart_pending",
            readiness={"candidate": {"ready": False}, "rollback": {"ready": False}},
            error=safe_error,
            updated_at=timestamp(),
        )
        write_web_activation_journal(
            root,
            pending,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        raise WebActivationError(safe_error) from rollback_error
    safe_error = f"candidate_restart_failed:{type(candidate_error).__name__}"
    readiness = {"candidate": {"ready": False}, "rollback": rollback_readiness}
    rolled_back = _journal_state(
        journal,
        "rolled_back",
        readiness=readiness,
        error=safe_error,
        updated_at=timestamp(),
    )
    write_web_activation_journal(
        root,
        rolled_back,
        verified_artifacts=verified_artifacts,
        verified_overlays=verified_overlays,
    )
    return WebActivationOutcome(rollback, journal.web_activation_id, False, True, readiness)


def _restart(restart_sidecars: Restart) -> dict[str, object]:
    started = time.monotonic()
    result = restart_sidecars()
    ready = result.get("ready") is True
    if not ready:
        raise WebActivationError("sidecar readiness failed")
    service_count = result.get("service_count")
    readiness = {
        "ready": True,
        "duration_seconds": round(time.monotonic() - started, 6),
        "service_count": service_count if isinstance(service_count, int) and service_count >= 0 else 0,
    }
    if result.get("browser_remount_event_emitted") is True:
        readiness["browser_remount_event_emitted"] = True
    return readiness


def _journal_state(
    journal: WebActivationJournal,
    state: str,
    *,
    readiness: dict[str, object],
    error: str | None,
    updated_at: str,
) -> WebActivationJournal:
    return WebActivationJournal(
        web_activation_id=journal.web_activation_id,
        state=state,
        source=journal.source,
        target=journal.target,
        readiness=readiness,
        error=error,
        created_at=journal.created_at,
        updated_at=updated_at,
    )


@contextmanager
def _web_activation_lock(root: Path):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise WebActivationError("OpenDesign generation root must be a real directory")
    lock_path = root / ".web-activation.lock"
    if lock_path.is_symlink():
        raise WebActivationError("OpenDesign web activation lock must not be a symlink")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        mode = os.fstat(descriptor).st_mode
        if not stat.S_ISREG(mode):
            raise WebActivationError("OpenDesign web activation lock must be a regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
