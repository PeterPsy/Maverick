"""Authorization helpers for core-owned inter-agent surfaces."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.authorization.errors import AuthorizationError
from core.authorization.service import authorize_runtime_session_create
from core.identity.errors import UserNotFoundError
from core.identity.models import UserRecord
from core.runtime.runtime_session import RuntimeSessionGrantRecord, runtime_session_allows_user_thread
from core.workspaces.errors import WorkspaceMembershipError

if TYPE_CHECKING:
    from core.identity.store import IdentityStore
    from core.inter_agent.models import InterAgentRunRecord
    from core.runtime.runtime_session import RuntimeSessionRecord
    from core.runtime.store import RuntimeStore
    from core.workspaces.store import WorkspaceStore


def authorize_inter_agent_run_view(*, context_workspace_id: str | None, run_workspace_id: str) -> None:
    """Require the caller workspace to match the run workspace."""
    if context_workspace_id != run_workspace_id:
        raise AuthorizationError("inter_agent_run_not_found")


def authorize_inter_agent_run_operation(
    *,
    workspace_store: "WorkspaceStore | None",
    context_workspace_id: str | None,
    caller_kind: str,
    run: "InterAgentRunRecord",
    user_id: str | None,
    platform_role: str | None = None,
    workspace_role: str | None = None,
) -> None:
    """Require owner/creator/admin authority for one inter-agent run mutation."""
    authorize_inter_agent_run_view(context_workspace_id=context_workspace_id, run_workspace_id=run.workspace_id)
    if caller_kind == "operator":
        return
    if _is_admin_context(
        workspace_store=workspace_store,
        workspace_id=run.workspace_id,
        user_id=user_id,
        platform_role=platform_role,
        workspace_role=workspace_role,
    ):
        return
    if user_id and run.created_by_user_id == user_id:
        return
    raise AuthorizationError("inter_agent_run_operation_forbidden")


def authorize_inter_agent_participant_spawn(
    *,
    workspace_store: "WorkspaceStore | None",
    runtime_store: "RuntimeStore",
    identity_store: "IdentityStore | None" = None,
    user: UserRecord | None = None,
    context_workspace_id: str | None,
    caller_kind: str,
    run: "InterAgentRunRecord",
    owner_user_id: str | None = None,
    user_id: str | None = None,
    platform_role: str | None = None,
    workspace_role: str | None = None,
) -> None:
    """Require run mutation authority plus runtime-session creation authority."""
    authorize_inter_agent_run_operation(
        workspace_store=workspace_store,
        context_workspace_id=context_workspace_id,
        caller_kind=caller_kind,
        run=run,
        user_id=user_id or (user.user_id if user is not None else None),
        platform_role=platform_role or (user.platform_role if user is not None else None),
        workspace_role=workspace_role,
    )
    if caller_kind == "operator":
        return
    if workspace_store is None:
        raise AuthorizationError("runtime_session_create_forbidden")
    resolved_user = _resolve_user(user=user, identity_store=identity_store, user_id=user_id)
    authorize_runtime_session_create(
        workspace_store=workspace_store,
        runtime_store=runtime_store,
        user=resolved_user,
        workspace_id=run.workspace_id,
    )
    if owner_user_id and owner_user_id != resolved_user.user_id and not _is_admin_context(
        workspace_store=workspace_store,
        workspace_id=run.workspace_id,
        user_id=resolved_user.user_id,
        platform_role=platform_role or resolved_user.platform_role,
        workspace_role=workspace_role,
    ):
        raise AuthorizationError("inter_agent_owner_forbidden")


def authorize_inter_agent_root_session_use(
    *,
    workspace_store: "WorkspaceStore | None",
    identity_store: "IdentityStore | None" = None,
    user: UserRecord | None = None,
    context_workspace_id: str | None,
    caller_kind: str,
    root_session: "RuntimeSessionRecord",
    user_id: str | None = None,
    platform_role: str | None = None,
    workspace_role: str | None = None,
    caller_runtime_session_id: str | None = None,
) -> None:
    """Require authority to attach an inter-agent run to one root runtime session."""
    if context_workspace_id != root_session.workspace_id:
        raise AuthorizationError("root_runtime_session_not_found")
    if not runtime_session_allows_user_thread(root_session):
        raise AuthorizationError("root_runtime_session_hidden")
    if caller_kind == "operator":
        return
    effective_user_id = user_id or (user.user_id if user is not None else None)
    effective_platform_role = platform_role or (user.platform_role if user is not None else None)
    if _is_admin_context(
        workspace_store=workspace_store,
        workspace_id=root_session.workspace_id,
        user_id=effective_user_id,
        platform_role=effective_platform_role,
        workspace_role=workspace_role,
    ):
        return
    resolved_user = _resolve_user(user=user, identity_store=identity_store, user_id=effective_user_id)
    if root_session.owner_user_id and root_session.owner_user_id == resolved_user.user_id:
        return
    if _session_grants_operation(
        root_session,
        operation="inter_agent_root",
        grantee_kind="user",
        grantee_id=resolved_user.user_id,
    ):
        return
    if caller_runtime_session_id and _session_grants_operation(
        root_session,
        operation="inter_agent_root",
        grantee_kind="runtime_session",
        grantee_id=caller_runtime_session_id,
    ):
        return
    raise AuthorizationError("inter_agent_root_session_forbidden")


def _resolve_user(
    *,
    user: UserRecord | None,
    identity_store: "IdentityStore | None",
    user_id: str | None,
) -> UserRecord:
    if user is not None:
        if not user.is_active:
            raise AuthorizationError("runtime_session_create_forbidden")
        return user
    if identity_store is None or not user_id:
        raise AuthorizationError("runtime_session_create_forbidden")
    try:
        resolved = identity_store.get_user(user_id)
    except UserNotFoundError as error:
        raise AuthorizationError("runtime_session_create_forbidden") from error
    if not resolved.is_active:
        raise AuthorizationError("runtime_session_create_forbidden")
    return resolved


def _session_grants_operation(
    session: "RuntimeSessionRecord",
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


def _is_admin_context(
    *,
    workspace_store: "WorkspaceStore | None",
    workspace_id: str,
    user_id: str | None,
    platform_role: str | None,
    workspace_role: str | None,
) -> bool:
    if platform_role == "admin" or workspace_role == "admin":
        return True
    if workspace_store is None or not user_id:
        return False
    try:
        membership = workspace_store.get_membership(user_id=user_id, workspace_id=workspace_id)
    except WorkspaceMembershipError:
        return False
    return membership.status == "active" and membership.role == "admin"
