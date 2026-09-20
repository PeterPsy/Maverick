"""Backend-owned periodic app hook scheduling."""

from __future__ import annotations

import logging
import os
from threading import Event, Thread
from typing import Any

from core.api.prepared_session_cleanup import start_prepared_session_cleanup_scheduler
from core.api.runtime_session_root_purge import start_runtime_session_root_purge_scheduler
from core.apps.runtime_event_hooks import dispatch_workspace_app_background_hooks
from core.apps.background_schedule import BackgroundHookSchedule
from core.runtime.runtime_idle_deadlines import runtime_idle_deadlines

logger = logging.getLogger(__name__)

DEFAULT_BACKGROUND_HOOK_INTERVAL_SECONDS = 15.0


def start_background_hook_scheduler(state, *, interval_seconds: float | None = None, shutdown_controller=None) -> Thread:
    """Start the backend-owned app background hook scheduler."""
    interval = _background_hook_interval_seconds(interval_seconds)
    stop = Event()
    if shutdown_controller is not None:
        shutdown_controller.register_cleanup(stop.set)
        shutdown_controller.register_cleanup(lambda: runtime_idle_deadlines.cancel_owner(state))
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
        args=(state, interval, stop),
        name="maverick-app-background-hooks",
        daemon=True,
    )
    thread.start()
    return thread


def run_background_hook_tick(state, *, due_schedule: BackgroundHookSchedule | None = None) -> dict[str, Any]:
    """Invoke one app-agnostic background tick across active workspaces."""
    workspaces = []
    active = set()
    for workspace in state.workspace_store.list_workspaces():
        if getattr(workspace, "status", "") != "active":
            continue
        workspace_id = workspace.workspace_id
        active.add(workspace_id)
        results = dispatch_workspace_app_background_hooks(
            state,
            workspace_id=workspace_id,
            hook_name="background_tick",
            action="background.tick",
            start_path=state.repository_root,
            due_schedule=due_schedule,
        )
        if results:
            workspaces.append({"workspace_id": workspace_id, "results": results})
    if due_schedule is not None:
        due_schedule.prune_workspaces(active)
    return {"workspaces": workspaces}


def _run_background_hook_scheduler(state, interval_seconds: float, stop: Event) -> None:
    schedule = BackgroundHookSchedule(interval_seconds)
    while not stop.wait(schedule.next_delay()):
        try:
            result = run_background_hook_tick(state, due_schedule=schedule)
        except Exception:
            logger.exception("App background hook tick failed.")
            continue
        if result.get("workspaces"):
            logger.debug("App background hook tick completed: %s", result)


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
