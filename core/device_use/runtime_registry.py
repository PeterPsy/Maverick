"""Process-local bridge from persisted runtime sessions to DeviceUseService."""

from __future__ import annotations

import threading

from core.device_use.service import DeviceUseService


_SERVICES: dict[str, tuple[DeviceUseService, str]] = {}
_LOCK = threading.Lock()


def register_device_use_session(
    session_id: str, service: DeviceUseService, *, activation_id: str, state=None
) -> None:
    """Make the ephemeral executor available to the live provider adapter."""
    with _LOCK:
        _SERVICES[str(session_id)] = (service, activation_id)
    if state is not None:
        from core.device_use.computer_actor_registry import register_computer_actor
        register_computer_actor(state, str(session_id), activation_id)


def unregister_device_use_session(session_id: str) -> None:
    """Forget a runtime-to-executor association after terminal cleanup."""
    with _LOCK:
        _SERVICES.pop(str(session_id), None)
    from core.device_use.computer_actor_registry import cancel_computer_actor
    cancel_computer_actor(str(session_id), forget=True)


def stop_registered_device_use_session(
    session_id: str,
    activation_id: str,
    *,
    reason: str,
) -> None:
    """Revoke and forget an ephemeral lease from a lifecycle boundary."""
    with _LOCK:
        entry = _SERVICES.get(str(session_id))
        if entry is not None and entry[1] == activation_id:
            _SERVICES.pop(str(session_id), None)
    if entry is not None:
        # A delayed exit from the old provider must not unregister a reconnected
        # lease, even when both generations use the same service instance.
        entry[0].stop_activation(activation_id, reason=reason)


def device_use_service_for_session(session_id: str) -> DeviceUseService | None:
    """Resolve the in-process service; missing state is fail-closed after restart."""
    with _LOCK:
        entry = _SERVICES.get(str(session_id))
        return entry[0] if entry is not None else None
