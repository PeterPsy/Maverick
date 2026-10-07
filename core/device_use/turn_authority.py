"""Keep native login authority independent of workspace turn admission."""

from core.device_use.errors import DeviceUseError


def reconcile_device_use_login(service, *, session, owner_user_id: str, auth_session_id: str) -> None:
    """Revoke a foreign login's native lease without blocking workspace work."""
    binding = session.device_use_binding
    if binding is None:
        return
    try:
        service.binding_snapshot(
            binding.activation_id,
            owner_user_id=owner_user_id,
            workspace_id=session.workspace_id,
            auth_session_id=auth_session_id,
            bound_session_id=session.session_id,
        )
    except DeviceUseError as error:
        # Offline/stopped/obsolete leases are already denied by invoke. A live
        # lease from another login must also remain unavailable to this turn.
        if error.reason_code == "device_use_activation_forbidden":
            service.stop_activation(
                binding.activation_id,
                owner_user_id=binding.owner_user_id,
                workspace_id=binding.workspace_id,
                reason="device_use_login_changed",
            )
