"""Asynchronous declarative prewarm for governed app sidecars."""

from __future__ import annotations

import json
import logging
from threading import Lock, Thread
import time
from typing import Literal

from core.api.sidecar_proxy import ensure_sidecar_with_declared_auto_repair
from core.apps.models import WorkspaceAppBindingRecord
from core.apps.surfaces import resolve_workspace_app_surface


logger = logging.getLogger(__name__)
PrewarmTrigger = Literal["core_start", "install", "activation"]
_prewarm_family_guard = Lock()
_prewarm_family_locks: dict[tuple[str, str], Lock] = {}


def start_declared_sidecar_prewarms(
    state,
    *,
    trigger: PrewarmTrigger,
    shutdown_controller=None,
) -> tuple[Thread, ...]:
    """Schedule matching sidecars in deterministic per-family queues."""
    queues: dict[tuple[str, str], list[dict[str, object]]] = {}
    workspaces = sorted(
        state.workspace_store.list_workspaces(),
        key=lambda item: (item.workspace_id != "default", item.workspace_id),
    )
    for workspace in workspaces:
        if getattr(workspace, "status", "") != "active":
            continue
        for binding in state.app_store.list_workspace_app_bindings(workspace.workspace_id):
            for arguments in _matching_prewarm_arguments(
                state,
                binding=binding,
                trigger=trigger,
                shutdown_controller=shutdown_controller,
            ):
                sidecar = arguments["sidecar"]
                key = (binding.app_id, sidecar.service_id)
                queues.setdefault(key, []).append(arguments)
    threads: list[Thread] = []
    for (app_id, sidecar_id), queue in queues.items():
        thread = Thread(
            target=_prewarm_sequence,
            kwargs={"queue": tuple(queue), "shutdown_controller": shutdown_controller},
            name=f"maverick-sidecar-prewarm-family-{app_id}-{sidecar_id}",
            daemon=True,
        )
        thread.start()
        threads.append(thread)
    return tuple(threads)


def start_workspace_app_sidecar_prewarms(
    state,
    *,
    binding: WorkspaceAppBindingRecord,
    trigger: PrewarmTrigger,
    shutdown_controller=None,
) -> tuple[Thread, ...]:
    """Schedule matching sidecars for one enabled binding."""
    threads: list[Thread] = []
    for arguments in _matching_prewarm_arguments(
        state,
        binding=binding,
        trigger=trigger,
        shutdown_controller=shutdown_controller,
    ):
        sidecar = arguments["sidecar"]
        thread = Thread(
            target=_prewarm_one,
            kwargs=arguments,
            name=f"maverick-sidecar-prewarm-{binding.workspace_id}-{binding.app_id}-{sidecar.service_id}",
            daemon=True,
        )
        thread.start()
        threads.append(thread)
    return tuple(threads)


def prewarm_workspace_app_sidecars(
    state,
    *,
    binding: WorkspaceAppBindingRecord,
    trigger: PrewarmTrigger,
    shutdown_controller=None,
) -> dict[str, object]:
    """Synchronously prewarm through the live manager for governed operator control."""
    arguments = _matching_prewarm_arguments(
        state,
        binding=binding,
        trigger=trigger,
        shutdown_controller=shutdown_controller,
    )
    if not arguments:
        raise RuntimeError("No matching declarative sidecar prewarm policy is enabled.")
    instances: list[str] = []
    for item in arguments:
        sidecar = item["sidecar"]
        with _prewarm_family_lock(binding.app_id, sidecar.service_id):
            if _is_shutting_down(shutdown_controller):
                raise RuntimeError("Maverick Core is shutting down.")
            running = ensure_sidecar_with_declared_auto_repair(
                binding=binding,
                source_root=item["source_root"],
                parsed=item["parsed"],
                sidecar=sidecar,
                start_path=item["start_path"],
                shutdown_controller=shutdown_controller,
            )
            instances.append(running.instance_id)
    return {
        "ready": True,
        "service_count": len(instances),
        "instance_count": len(set(instances)),
    }


def _matching_prewarm_arguments(
    state,
    *,
    binding: WorkspaceAppBindingRecord,
    trigger: PrewarmTrigger,
    shutdown_controller,
) -> tuple[dict[str, object], ...]:
    if binding.status != "enabled" or _is_shutting_down(shutdown_controller):
        return ()
    try:
        source_root, parsed = resolve_workspace_app_surface(
            state.app_store,
            binding=binding,
            start_path=state.repository_root,
        )
    except Exception:
        logger.exception("Unable to resolve app sidecars for declarative prewarm.")
        return ()
    return tuple(
        {
            "binding": binding,
            "source_root": source_root,
            "parsed": parsed,
            "sidecar": sidecar,
            "start_path": state.repository_root,
            "shutdown_controller": shutdown_controller,
            "trigger": trigger,
        }
        for sidecar in parsed.contract.services.http_sidecars
        if sidecar.prewarm is not None and _trigger_enabled(sidecar.prewarm, trigger=trigger)
    )


def _prewarm_sequence(*, queue: tuple[dict[str, object], ...], shutdown_controller) -> None:
    for arguments in queue:
        if _is_shutting_down(shutdown_controller):
            return
        _prewarm_one(**arguments)


def _prewarm_one(
    *,
    binding: WorkspaceAppBindingRecord,
    source_root,
    parsed,
    sidecar,
    start_path,
    shutdown_controller,
    trigger: PrewarmTrigger,
) -> None:
    if _is_shutting_down(shutdown_controller):
        return
    started = time.monotonic()
    family_lock = _prewarm_family_lock(binding.app_id, sidecar.service_id)
    try:
        with family_lock:
            if _is_shutting_down(shutdown_controller):
                return
            running = ensure_sidecar_with_declared_auto_repair(
                binding=binding,
                source_root=source_root,
                parsed=parsed,
                sidecar=sidecar,
                start_path=start_path,
                shutdown_controller=shutdown_controller,
            )
    except Exception as error:
        logger.warning(
            "sidecar.prewarm %s",
            json.dumps(
                {
                    "status": "failed",
                    "trigger": trigger,
                    "workspace_id": binding.workspace_id,
                    "app_id": binding.app_id,
                    "sidecar_id": sidecar.service_id,
                    "error_code": getattr(error, "code", type(error).__name__),
                    "phase": getattr(error, "phase", "prewarm"),
                    "prewarm_ms": round((time.monotonic() - started) * 1000, 3),
                },
                sort_keys=True,
            ),
        )
        return
    logger.info(
        "sidecar.prewarm %s",
        json.dumps(
            {
                "status": "ready",
                "trigger": trigger,
                "workspace_id": binding.workspace_id,
                "app_id": binding.app_id,
                "sidecar_id": sidecar.service_id,
                "instance_id": running.instance_id,
                "prewarm_ms": round((time.monotonic() - started) * 1000, 3),
            },
            sort_keys=True,
        ),
    )


def _trigger_enabled(policy, *, trigger: PrewarmTrigger) -> bool:
    return bool(
        (trigger == "core_start" and policy.on_core_start)
        or (trigger == "install" and policy.on_install)
        or (trigger == "activation" and policy.on_activation)
    )


def _prewarm_family_lock(app_id: str, sidecar_id: str) -> Lock:
    """Bound heavy identical prewarms while leaving different sidecars parallel."""
    key = (app_id, sidecar_id)
    with _prewarm_family_guard:
        lock = _prewarm_family_locks.get(key)
        if lock is None:
            lock = Lock()
            _prewarm_family_locks[key] = lock
        return lock


def _is_shutting_down(shutdown_controller) -> bool:
    return bool(shutdown_controller is not None and shutdown_controller.is_shutting_down())
