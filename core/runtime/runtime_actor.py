"""Authoritative actor resolution shared by runtime execution surfaces."""

from __future__ import annotations

from core.authorization.errors import AuthorizationError
from core.identity.errors import UserNotFoundError
from core.workspaces.errors import WorkspaceMembershipError


def resolve_runtime_actor_roles(
    state,
    *,
    user_id: str | None,
    workspace_id: str,
) -> tuple[str, str, str]:
    """Return live platform/workspace roles for an active runtime owner."""
    if not user_id:
        raise AuthorizationError("runtime_session_owner_not_authorized")
    try:
        user = state.identity_store.get_user(user_id)
    except UserNotFoundError:
        raise AuthorizationError("runtime_session_owner_not_authorized") from None
    try:
        membership = state.workspace_store.get_membership(
            user_id=user_id,
            workspace_id=workspace_id,
        )
    except WorkspaceMembershipError:
        if user.platform_role == "admin":
            return user.platform_role, user_id, "admin"
        raise AuthorizationError("runtime_session_owner_not_authorized") from None
    if membership.status != "active" and user.platform_role != "admin":
        raise AuthorizationError("runtime_session_owner_not_authorized")
    workspace_role = membership.role if membership.status == "active" else "admin"
    return user.platform_role, user_id, workspace_role
