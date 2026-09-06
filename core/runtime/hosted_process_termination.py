"""Quiesce the complete group of a Core-owned, detached hosted launcher."""

import os
import signal
import subprocess

from core.runtime.tool_errors import RuntimeToolError


def terminate_hosted_process(process: subprocess.Popen, *, timeout_seconds: float = 1.5) -> bool:
    """Do not confuse launcher exit with termination of its sandbox descendants.

    Callers must own a process launched with start_new_session=True and keep
    Bubblewrap in that group. Namespace init can ignore SIGTERM during startup;
    therefore an active group's SIGKILL escalation must not depend on whether
    SIGTERM exited the leader. Already-reaped handles are not group authority:
    their numeric pid may have been reused; session-owned orphan cleanup is
    the separate fallback for those handles.
    """
    was_running = process.poll() is None
    if not was_running:
        return False
    _signal_group(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        pass
    _signal_group(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        raise RuntimeToolError("hosted_process_termination_incomplete") from error
    return was_running


def _signal_group(group_id: int, sig: signal.Signals) -> None:
    try:
        os.killpg(group_id, sig)
    except ProcessLookupError:
        pass
    except OSError as error:
        raise RuntimeToolError("hosted_process_termination_failed") from error
