"""Backend-owned periodic app hook scheduling."""

from __future__ import annotations

import logging
import os
from threading import Thread
import time
from typing import Any

from core.api.prepared_session_cleanup import start_prepared_session_cleanup_scheduler
from core.api.runtime_session_root_purge import start_runtime_session_root_purge_scheduler
from core.apps.runtime_event_hooks import dispatch_workspace_app_background_hooks

logger = logging.getLogger(__name__)

DEFAULT_BACKGROUND_HOOK_INTERVAL_SECONDS = 15.0


def start_background_hook_scheduler(state, *, interval_seconds: float | None = None, shutdown_controller=None) -> Thread:
    """Start the backend-owned app background hook scheduler."""
    interval = _background_hook_interval_seconds(interval_seconds)
    start_prepared_session_cleanup_scheduler(
        state,
        initial_delay_seconds=max(1.0, interval / 2),
        shutdown_controller=shutdown_controller,
    )
    start_runtime_session_root_purge_scheduler(
        state,
        initial_delay_seconds=1.0,
        shutdown_controller=shutdown_controller,
    )
    thread = Thread(
        target=_run_background_hook_scheduler,
        args=(state, interval, shutdown_controller),
        name="maverick-app-background-hooks",
        daemon=True,
    )
    thread.start()
    return thread


def run_background_hook_tick(state) -> dict[str, Any]:
    """Invoke one app-agnostic background tick across active workspaces."""
    workspaces = []
    for workspace in state.workspace_store.list_workspaces():
        if getattr(workspace, "status", "") != "active":
            continue
        workspace_id = workspace.workspace_id
        results = dispatch_workspace_app_background_hooks(
            state,
            workspace_id=workspace_id,
            hook_name="background_tick",
            action="background.tick",
            start_path=state.repository_root,
        )
        if results:
            workspaces.append({"workspace_id": workspace_id, "results": results})
    return {"workspaces": workspaces}


def _run_background_hook_scheduler(state, interval_seconds: float, shutdown_controller) -> None:
    while not _is_shutting_down(shutdown_controller):
        time.sleep(interval_seconds)
        if _is_shutting_down(shutdown_controller):
            return
        try:
            result = run_background_hook_tick(state)
        except Exception:
            logger.exception("App background hook tick failed.")
            continue
        if result.get("workspaces"):
            logger.info("App background hook tick completed: %s", result)


def _background_hook_interval_seconds(interval_seconds: float | None) -> float:
    if interval_seconds is not None:
        return max(1.0, float(interval_seconds))
    raw = os.environ.get("MAVERICK_BACKGROUND_HOOK_INTERVAL_SECONDS", "").strip()
    if not raw:
        return DEFAULT_BACKGROUND_HOOK_INTERVAL_SECONDS
    try:
        return max(1.0, float(raw))
    except ValueError:
        return DEFAULT_BACKGROUND_HOOK_INTERVAL_SECONDS


def _is_shutting_down(shutdown_controller) -> bool:
    return bool(shutdown_controller is not None and shutdown_controller.is_shutting_down())
