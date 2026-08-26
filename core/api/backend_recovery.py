"""Backend-host recovery helpers."""

from __future__ import annotations

import logging
from threading import Thread
import time
from typing import Iterable

from core.recovery.backend_restart import recover_interrupted_runtime_turns_after_backend_restart
from core.api.orchestration_workers import resume_recovering_orchestrations

logger = logging.getLogger(__name__)


def start_backend_restart_recovery(
    state,
    *,
    after_threads: Iterable[Thread] = (),
    maximum_defer_seconds: float = 8.0,
) -> Thread:
    """Run backend restart recovery without blocking host socket startup."""
    thread = Thread(
        target=_recover_backend_restart_after,
        args=(state, tuple(after_threads), max(0.0, float(maximum_defer_seconds))),
        name="maverick-backend-recovery",
        daemon=True,
    )
    thread.start()
    return thread


def _recover_backend_restart_after(
    state,
    prerequisites: tuple[Thread, ...],
    maximum_defer_seconds: float,
) -> None:
    """Prioritize bounded sidecar prewarm before competing runtime recovery."""
    deadline = time.monotonic() + maximum_defer_seconds
    for prerequisite in prerequisites:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        prerequisite.join(timeout=remaining)
    _recover_backend_restart(state)


def _recover_backend_restart(state) -> None:
    result = None
    try:
        result = recover_interrupted_runtime_turns_after_backend_restart(state)
    except Exception:
        logger.exception("Backend restart runtime recovery failed.")
    recovered_jobs = []
    try:
        recovered_jobs = state.job_service.recover_expired_jobs()
    except Exception:
        logger.exception("Backend restart durable job recovery failed.")
    resumed_orchestrations = []
    try:
        resumed_orchestrations = resume_recovering_orchestrations(state)
    except Exception:
        logger.exception("Backend restart orchestration resume failed.")
    logger.info(
        "Backend restart recovery completed: %s; recovered jobs=%s; resumed orchestrations=%s",
        result,
        len(recovered_jobs),
        len(resumed_orchestrations),
    )
