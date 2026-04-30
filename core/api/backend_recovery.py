"""Backend-host recovery helpers."""

from __future__ import annotations

import logging
from threading import Thread

from core.recovery.backend_restart import recover_interrupted_runtime_turns_after_backend_restart

logger = logging.getLogger(__name__)


def start_backend_restart_recovery(state) -> Thread:
    """Run backend restart recovery without blocking host socket startup."""
    thread = Thread(
        target=_recover_backend_restart,
        args=(state,),
        name="maverick-backend-recovery",
        daemon=True,
    )
    thread.start()
    return thread


def _recover_backend_restart(state) -> None:
    try:
        result = recover_interrupted_runtime_turns_after_backend_restart(state)
    except Exception:
        logger.exception("Backend restart recovery failed.")
        return
    logger.info("Backend restart recovery completed: %s", result)
