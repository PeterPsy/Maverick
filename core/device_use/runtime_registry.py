"""Process-local bridge from persisted runtime sessions to DeviceUseService."""

from __future__ import annotations

import threading

from core.device_use.service import DeviceUseService


_SERVICES: dict[str, DeviceUseService] = {}
_LOCK = threading.Lock()


def register_device_use_session(session_id: str, service: DeviceUseService) -> None:
    """Make the ephemeral executor available to the live provider adapter."""
    with _LOCK:
        _SERVICES[str(session_id)] = service


def unregister_device_use_session(session_id: str) -> None:
    """Forget a runtime-to-executor association after terminal cleanup."""
    with _LOCK:
        _SERVICES.pop(str(session_id), None)


def stop_registered_device_use_session(
    session_id: str,
    activation_id: str,
    *,
    reason: str,
) -> None:
    """Revoke and forget an ephemeral lease from a lifecycle boundary."""
    with _LOCK:
        service = _SERVICES.pop(str(session_id), None)
    if service is not None:
        service.stop_activation(activation_id, reason=reason)


def device_use_service_for_session(session_id: str) -> DeviceUseService | None:
    """Resolve the in-process service; missing state is fail-closed after restart."""
    with _LOCK:
        return _SERVICES.get(str(session_id))
