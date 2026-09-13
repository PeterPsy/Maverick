"""Off-reader dispatch for Codex Device Use server requests."""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable

from core.device_use.runtime_registry import stop_registered_device_use_session
from core.providers.codex_app_server_device_use import (
    process_device_use_request,
    reject_device_use_request,
)


ServerRequestFallback = Callable[[object, dict[str, Any]], None]


def start_device_use_request_worker(runtime) -> None:
    """Start a worker only for sessions that may steer an active tool call."""
    if runtime.device_use_binding is None:
        return
    runtime.server_request_thread = threading.Thread(
        target=_server_request_loop,
        args=(runtime,),
        daemon=True,
        name=f"codex-app-server-requests-{runtime.session_id}",
    )
    runtime.server_request_thread.start()


def dispatch_server_request(
    runtime,
    payload: dict[str, Any],
    fallback: ServerRequestFallback,
) -> None:
    """Keep native calls off stdout; preserve legacy handling otherwise."""
    if runtime.device_use_binding is None:
        fallback(runtime, payload)
        return
    try:
        runtime.server_request_queue.put_nowait(payload)
    except queue.Full:
        reject_device_use_request(
            runtime,
            payload.get("id"),
            "Device Use request queue is full.",
        )


def stop_device_use_request_worker(runtime) -> None:
    """Drain doomed work and wake the bounded worker after stdout closes."""
    if runtime.device_use_binding is None:
        return
    while True:
        try:
            runtime.server_request_queue.get_nowait()
        except queue.Empty:
            break
    runtime.server_request_queue.put_nowait(None)


def stop_device_use_runtime(runtime, *, reason: str) -> None:
    binding = runtime.device_use_binding
    if binding is not None:
        stop_registered_device_use_session(
            runtime.session_id,
            binding.activation_id,
            reason=reason,
        )


def _server_request_loop(runtime) -> None:
    while True:
        payload = runtime.server_request_queue.get()
        if payload is None:
            return
        process_device_use_request(runtime, payload)
