"""Backend-owned deferred purge for deleted runtime-session roots."""

from __future__ import annotations

import logging
import os
from threading import Event, Thread
from typing import Any

from core.runtime.session_root_cleanup import purge_staged_runtime_roots


logger = logging.getLogger(__name__)

DEFAULT_RUNTIME_SESSION_ROOT_PURGE_INTERVAL_SECONDS = 1.0
DEFAULT_RUNTIME_SESSION_ROOT_PURGE_BATCH_SIZE = 8


def start_runtime_session_root_purge_scheduler(
    state,
    *,
    interval_seconds: float | None = None,
    initial_delay_seconds: float | None = None,
    shutdown_controller=None,
) -> Thread:
    """Start one process-owned worker that drains the persistent purge queue."""
    stop = Event()
    if shutdown_controller is not None:
        shutdown_controller.register_cleanup(stop.set)
    interval = _purge_interval_seconds(interval_seconds)
    initial_delay = interval if initial_delay_seconds is None else max(0.1, float(initial_delay_seconds))
    thread = Thread(
        target=_run_runtime_session_root_purge_scheduler,
        args=(state, interval, initial_delay, stop),
        name="maverick-runtime-session-root-purge",
        daemon=True,
    )
    thread.start()
    return thread


def run_runtime_session_root_purge_tick(
    state,
    *,
    max_roots: int = DEFAULT_RUNTIME_SESSION_ROOT_PURGE_BATCH_SIZE,
) -> dict[str, Any]:
    """Purge a bounded number of staged roots across registered workspaces."""
    if max_roots < 1:
        raise ValueError("Runtime-session root purge batch size must be positive.")
    attempted = 0
    purged = 0
    remaining = 0
    failures: list[dict[str, str]] = []
    workspace_results: list[dict[str, object]] = []
    workspaces = sorted(
        state.workspace_store.list_workspaces(),
        key=lambda workspace: workspace.workspace_id,
    )
    for workspace in workspaces:
        capacity = max_roots - attempted
        if capacity < 1:
            break
        try:
            result = purge_staged_runtime_roots(
                workspace_id=workspace.workspace_id,
                start_path=state.repository_root,
                max_roots=capacity,
            )
        except Exception as error:  # maintenance must not prevent later ticks
            failures.append(
                {
                    "workspace_id": workspace.workspace_id,
                    "error_type": type(error).__name__,
                }
            )
            logger.exception(
                "Runtime-session root purge failed for workspace %s.",
                workspace.workspace_id,
            )
            continue
        workspace_results.append(result)
        attempted += int(result["attempted"])
        purged += int(result["purged"])
        remaining += int(result["remaining"])
        failures.extend(
            {
                "workspace_id": workspace.workspace_id,
                "entry": str(failure.get("entry") or ""),
                "error_type": str(failure.get("error_type") or "unknown"),
            }
            for failure in result["failures"]
        )
    return {
        "attempted": attempted,
        "purged": purged,
        "remaining": remaining,
        "reached_limit": attempted >= max_roots,
        "failures": failures,
        "workspaces": workspace_results,
    }


def _run_runtime_session_root_purge_scheduler(
    state,
    interval_seconds: float,
    initial_delay_seconds: float,
    stop: Event,
) -> None:
    delay = initial_delay_seconds
    while not stop.wait(delay):
        try:
            result = run_runtime_session_root_purge_tick(state)
        except Exception:
            logger.exception("Runtime-session root purge tick failed.")
            result = None
        if result and (result["attempted"] or result["failures"]):
            logger.info("Runtime-session root purge tick completed: %s", result)
        should_continue_draining = bool(
            result
            and result["purged"]
            and (result["remaining"] or result["reached_limit"])
        )
        delay = 0.0 if should_continue_draining else interval_seconds


def _purge_interval_seconds(interval_seconds: float | None) -> float:
    if interval_seconds is not None:
        return max(0.1, float(interval_seconds))
    raw = os.environ.get("MAVERICK_RUNTIME_SESSION_ROOT_PURGE_INTERVAL_SECONDS", "").strip()
    if not raw:
        return DEFAULT_RUNTIME_SESSION_ROOT_PURGE_INTERVAL_SECONDS
    try:
        return max(0.1, float(raw))
    except ValueError:
        return DEFAULT_RUNTIME_SESSION_ROOT_PURGE_INTERVAL_SECONDS
