"""Workspace authorization helpers shared by core surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from core.authorization.errors import AuthorizationError
from core.identity.models import UserRecord
from core.runtime.runtime_session import RuntimeSessionGrantRecord, RuntimeSessionRecord
from core.workspaces.errors import WorkspaceMembershipError, WorkspaceNotFoundError
from core.workspaces.models import WorkspaceMembershipRecord, WorkspaceQuotaRecord

if TYPE_CHECKING:
    from core.runtime.store import RuntimeStore
    from core.workspaces.store import WorkspaceStore


WORKSPACE_ADMIN_CAPABILITIES = {
    "manage_app_dependencies",
    "manage_apps",
    "manage_agents",
    "manage_providers",
    "manage_runtime_sessions",
    "manage_workspace_governance",
    "manage_workspace_memberships",
    "restart_backend",
}
WORKSPACE_MEMBER_CAPABILITIES = {
    "create_runtime_sessions",
    "use_apps",
    "use_workspace",
}


@dataclass(frozen=True)
class WorkspaceAuthorization:
    """Resolved authority for one user in one workspace."""

    user: UserRecord
    workspace_id: str
    membership: WorkspaceMembershipRecord | None

    @property
    def is_platform_admin(self) -> bool:
        return self.user.platform_role == "admin"

    @property
    def is_workspace_admin(self) -> bool:
        return self.membership is not None and self.membership.status == "active" and self.membership.role == "admin"

    @property
    def is_active_member(self) -> bool:
        return self.membership is not None and self.membership.status == "active"


def resolve_workspace_authorization(
    store: "WorkspaceStore",
    *,
    user: UserRecord,
    workspace_id: str,
) -> WorkspaceAuthorization:
    """Resolve one user's workspace authority without raising on missing membership."""
    try:
        membership = store.get_membership(user_id=user.user_id, workspace_id=workspace_id)
    except WorkspaceMembershipError:
        membership = None
    return WorkspaceAuthorization(user=user, workspace_id=workspace_id, membership=membership)


def require_workspace_membership(
    store: "WorkspaceStore",
    *,
    user: UserRecord,
    workspace_id: str,
) -> WorkspaceAuthorization:
    """Require an active membership or platform-admin authority for one workspace."""
    try:
        workspace = store.get_workspace(workspace_id)
    except WorkspaceNotFoundError as error:
        raise AuthorizationError("workspace_not_available") from error
    if workspace.status != "active":
        raise AuthorizationError("workspace_not_available")
    authorization = resolve_workspace_authorization(store, user=user, workspace_id=workspace_id)
    if not authorization.is_active_member and not authorization.is_platform_admin:
        raise AuthorizationError("workspace_not_available")
    return authorization


def require_workspace_admin(
    store: "WorkspaceStore",
    *,
    user: UserRecord,
    workspace_id: str,
    reason: str = "workspace_admin_required",
) -> WorkspaceAuthorization:
    """Require platform admin or active workspace-admin authority."""
    authorization = require_workspace_membership(store, user=user, workspace_id=workspace_id)
    if authorization.is_platform_admin or authorization.is_workspace_admin:
        return authorization
    raise AuthorizationError(reason)


def user_has_workspace_role(
    store: "WorkspaceStore",
    *,
    user: UserRecord | None,
    workspace_id: str,
    workspace_roles: Iterable[str] | None,
) -> bool:
    """Return whether a user has any requested active workspace role."""
    roles = set(workspace_roles or [])
    if not roles:
        return True
    if user is None:
        return False
    authorization = resolve_workspace_authorization(store, user=user, workspace_id=workspace_id)
    return authorization.is_active_member and authorization.membership is not None and authorization.membership.role in roles


def can_mount_app_visibility(
    store: "WorkspaceStore",
    *,
    user: UserRecord | None,
    workspace_id: str,
    platform_roles: Iterable[str] | None,
    workspace_roles: Iterable[str] | None,
    capabilities: Iterable[str] | None = None,
    platform_role: str | None = None,
    workspace_role: str | None = None,
) -> bool:
    """Return whether one user may see or mount an app under its visibility policy."""
    platform_role_set = set(platform_roles or [])
    workspace_role_set = set(workspace_roles or [])
    capability_set = set(capabilities or [])
    if not platform_role_set and not workspace_role_set and not capability_set:
        return True
    effective_platform_role = platform_role or (user.platform_role if user is not None else None)
    if effective_platform_role is None and workspace_role is None and user is None:
        return False
    if platform_role_set and effective_platform_role in platform_role_set:
        return True
    if workspace_role_set and _effective_workspace_role_allowed(
        store,
        user=user,
        workspace_id=workspace_id,
        workspace_role=workspace_role,
        workspace_roles=workspace_role_set,
    ):
        return True
    if capability_set and any(
        user_has_visibility_capability(
            store,
            user=user,
            workspace_id=workspace_id,
            capability=capability,
            platform_role=effective_platform_role,
            workspace_role=workspace_role,
        )
        for capability in capability_set
    ):
        return True
    return False


def user_has_visibility_capability(
    store: "WorkspaceStore",
    *,
    user: UserRecord | None,
    workspace_id: str,
    capability: str,
    platform_role: str | None = None,
    workspace_role: str | None = None,
) -> bool:
    """Return whether one resolved caller has a named app visibility capability."""
    if platform_role == "admin" or (user is not None and user.platform_role == "admin"):
        return True
    if workspace_role is None and user is not None:
        authorization = resolve_workspace_authorization(store, user=user, workspace_id=workspace_id)
        if authorization.is_workspace_admin:
            workspace_role = "admin"
        elif authorization.is_active_member:
            workspace_role = "member"
    if workspace_role == "admin" and capability in WORKSPACE_ADMIN_CAPABILITIES:
        return True
    if workspace_role == "member" and capability in WORKSPACE_MEMBER_CAPABILITIES:
        return True
    return False


def _effective_workspace_role_allowed(
    store: "WorkspaceStore",
    *,
    user: UserRecord | None,
    workspace_id: str,
    workspace_role: str | None,
    workspace_roles: set[str],
) -> bool:
    if workspace_role is not None:
        return workspace_role in workspace_roles
    if user is None:
        return False
    return user_has_workspace_role(store, user=user, workspace_id=workspace_id, workspace_roles=workspace_roles)


def require_provider_selection_authority(store: "WorkspaceStore", *, user: UserRecord, workspace_id: str) -> None:
    """Require authority to change workspace-wide provider/model selection."""
    require_workspace_admin(store, user=user, workspace_id=workspace_id, reason="provider_selection_forbidden")


def require_app_dependency_management(store: "WorkspaceStore", *, user: UserRecord, workspace_id: str) -> None:
    """Require authority to change workspace-wide app dependency selections."""
    require_workspace_admin(store, user=user, workspace_id=workspace_id, reason="app_dependency_management_forbidden")


def require_governance_management(store: "WorkspaceStore", *, user: UserRecord, workspace_id: str) -> None:
    """Require authority to change workspace-local governance."""
    require_workspace_admin(store, user=user, workspace_id=workspace_id, reason="workspace_governance_forbidden")


def authorize_runtime_session_create(
    *,
    workspace_store: "WorkspaceStore",
    runtime_store: "RuntimeStore",
    user: UserRecord,
    workspace_id: str,
) -> None:
    """Authorize creation of a runtime session in one workspace."""
    authorization = require_workspace_membership(workspace_store, user=user, workspace_id=workspace_id)
    governance = workspace_store.get_governance(workspace_id)
    quota = workspace_store.get_quota(workspace_id)
    if not governance.allow_agent_creation:
        raise AuthorizationError("agent_creation_disabled")
    if not governance.allow_agent_management and not (authorization.is_platform_admin or authorization.is_workspace_admin):
        raise AuthorizationError("agent_management_disabled")
    _enforce_agent_quota(runtime_store, workspace_id=workspace_id, quota=quota)


def require_runtime_session_operation(
    *,
    workspace_store: "WorkspaceStore",
    user: UserRecord,
    session: RuntimeSessionRecord,
    operation: str,
) -> None:
    """Authorize destructive or interrupting operations for one runtime session."""
    authorization = require_workspace_membership(workspace_store, user=user, workspace_id=session.workspace_id)
    if authorization.is_platform_admin or authorization.is_workspace_admin:
        return
    if session.owner_user_id and session.owner_user_id == user.user_id:
        return
    if _session_grants_operation_to_user(session, operation=operation, user_id=user.user_id):
        return
    raise AuthorizationError(f"runtime_session_{operation}_forbidden")


def _session_grants_operation_to_user(session: RuntimeSessionRecord, *, operation: str, user_id: str) -> bool:
    return _session_grants_operation_to_principal(
        session,
        operation=operation,
        grantee_kind="user",
        grantee_id=user_id,
    )


def _session_grants_operation_to_principal(
    session: RuntimeSessionRecord,
    *,
    operation: str,
    grantee_kind: str,
    grantee_id: str,
) -> bool:
    for grant in session.grants:
        if isinstance(grant, RuntimeSessionGrantRecord):
            if grant.operation == operation and grant.grantee_kind == grantee_kind and grant.grantee_id == grantee_id:
                return True
            continue
        if not isinstance(grant, dict):
            continue
        if grant.get("source") != "platform":
            continue
        if (
            grant.get("operation") == operation
            and grant.get("grantee_kind") == grantee_kind
            and grant.get("grantee_id") == grantee_id
        ):
            return True
    return False


def require_session_restart_context(
    *,
    runtime_store: "RuntimeStore",
    workspace_store: "WorkspaceStore" | None,
    session_id: str,
    workspace_id: str | None,
    user_id: str | None,
    caller_runtime_session_id: str | None = None,
    platform_role: str | None = None,
) -> RuntimeSessionRecord:
    """Authorize CLI/MCP restart of a runtime session from trusted invocation context."""
    session = runtime_store.get_session(session_id)
    if workspace_id != session.workspace_id:
        raise AuthorizationError("runtime_session_not_found")
    if platform_role == "admin":
        return session
    if workspace_store is None or not user_id:
        raise AuthorizationError("runtime_restart_forbidden")
    try:
        membership = workspace_store.get_membership(user_id=user_id, workspace_id=session.workspace_id)
    except WorkspaceMembershipError as error:
        raise AuthorizationError("runtime_restart_forbidden") from error
    if membership.status != "active":
        raise AuthorizationError("runtime_restart_forbidden")
    if membership.role == "admin":
        return session
    if session.owner_user_id and session.owner_user_id == user_id:
        return session
    if _session_grants_operation_to_user(session, operation="restart", user_id=user_id):
        return session
    if caller_runtime_session_id and _session_grants_operation_to_principal(
        session,
        operation="restart",
        grantee_kind="runtime_session",
        grantee_id=caller_runtime_session_id,
    ):
        return session
    raise AuthorizationError("runtime_restart_forbidden")


def require_backend_restart_context(
    *,
    workspace_id: str | None,
    effective_mode: str | None,
    platform_role: str | None = None,
    workspace_role: str | None = None,
) -> None:
    """Authorize manual backend restart separately from full-access execution."""
    if workspace_id != "default":
        raise AuthorizationError("backend_restart_default_workspace_required")
    if effective_mode != "full-access":
        raise AuthorizationError("backend_restart_full_access_required")
    if platform_role == "admin" or workspace_role == "admin":
        return
    raise AuthorizationError("backend_restart_admin_required")


def _enforce_agent_quota(runtime_store: "RuntimeStore", *, workspace_id: str, quota: WorkspaceQuotaRecord) -> None:
    max_instances = quota.max_agent_instances
    if max_instances is None:
        return
    active_count = sum(
        1
        for session in runtime_store.list_sessions(workspace_id)
        if session.status in {"created", "running", "stopping"}
    )
    if active_count >= max_instances:
        raise AuthorizationError("max_agent_instances_reached")
