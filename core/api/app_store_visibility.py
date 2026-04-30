"""Authenticated Maverick App Store API surface."""

from __future__ import annotations


from core.api.app_registry import user_can_mount_app
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession
from core.apps.models import AppContractDescriptor, WorkspaceAppBindingRecord
from core.authorization.service import can_mount_app_visibility
from core.workspaces.models import WorkspaceMembershipRecord
from core.workspaces.errors import WorkspaceMembershipError, WorkspaceNotFoundError



def _authorize_app_management_targets(state: PlatformState, context: RequestSession, workspace_ids: list[str]) -> str | None:
    if not workspace_ids:
        return "workspace_required"
    unique_ids = []
    for workspace_id in workspace_ids:
        if workspace_id and workspace_id not in unique_ids:
            unique_ids.append(workspace_id)
    if len(unique_ids) != len(workspace_ids):
        return "duplicate_workspace"
    for workspace_id in unique_ids:
        try:
            workspace = state.workspace_store.get_workspace(workspace_id)
            membership = state.workspace_store.get_membership(user_id=context.user.user_id, workspace_id=workspace_id)
            governance = state.workspace_store.get_governance(workspace_id)
        except (WorkspaceNotFoundError, WorkspaceMembershipError):
            return "workspace_not_available"
        if workspace.status != "active" or membership.status != "active":
            return "workspace_not_available"
        if context.user.platform_role != "admin" and membership.role != "admin":
            return "workspace_admin_required"
        if not governance.allow_app_installation:
            return "app_installation_disabled"
    return None



def _authorize_workspace_local_app_targets(
    state: PlatformState,
    context: RequestSession,
    workspace_ids: list[str],
) -> str | None:
    if not workspace_ids:
        return "workspace_required"
    unique_ids = []
    for workspace_id in workspace_ids:
        if workspace_id and workspace_id not in unique_ids:
            unique_ids.append(workspace_id)
    if len(unique_ids) != len(workspace_ids):
        return "duplicate_workspace"
    for workspace_id in unique_ids:
        try:
            workspace = state.workspace_store.get_workspace(workspace_id)
            membership = state.workspace_store.get_membership(user_id=context.user.user_id, workspace_id=workspace_id)
            governance = state.workspace_store.get_governance(workspace_id)
        except (WorkspaceNotFoundError, WorkspaceMembershipError):
            return "workspace_not_available"
        if workspace.status != "active" or membership.status != "active":
            return "workspace_not_available"
        if context.user.platform_role == "admin" or membership.role == "admin":
            if not governance.allow_app_installation:
                return "app_installation_disabled"
            continue
        if not governance.allow_custom_apps:
            return "custom_apps_disabled"
        if not governance.allow_app_installation:
            return "app_installation_disabled"
    return None



def _authorize_platform_admin(context: RequestSession) -> str | None:
    if context.user.platform_role != "admin":
        return "platform_admin_required"
    return None



def _unique_workspace_ids(workspace_ids: list[str]) -> list[str]:
    unique_ids = []
    for workspace_id in workspace_ids:
        if workspace_id and workspace_id not in unique_ids:
            unique_ids.append(workspace_id)
    return unique_ids



def _user_workspace_ids(state: PlatformState, context: RequestSession) -> list[str]:
    memberships = state.workspace_store.list_memberships_for_user(context.user.user_id)
    return [
        membership.workspace_id
        for membership in memberships
        if membership.status == "active"
    ]



def _can_manage_workspace_apps(context: RequestSession, membership: WorkspaceMembershipRecord) -> bool:
    return context.user.platform_role == "admin" or membership.role == "admin"



def _workspace_membership(state: PlatformState, context: RequestSession, workspace_id: str) -> WorkspaceMembershipRecord | None:
    try:
        membership = state.workspace_store.get_membership(user_id=context.user.user_id, workspace_id=workspace_id)
    except WorkspaceMembershipError:
        return None
    if membership.status != "active":
        return None
    return membership



def _binding_contract(state: PlatformState, binding: WorkspaceAppBindingRecord) -> AppContractDescriptor:
    if binding.source_kind == "workspace_local_project":
        project = state.app_store.get_workspace_local_app_project(workspace_id=binding.workspace_id, app_id=binding.app_id)
        return project.contract
    source = state.app_store.get_app_source(binding.source_record_id)
    return source.contract



def _app_visible_for_context(
    state: PlatformState,
    context: RequestSession,
    membership: WorkspaceMembershipRecord,
    contract: AppContractDescriptor,
) -> bool:
    if _can_manage_workspace_apps(context, membership):
        return True
    return user_can_mount_app(state, user=context.user, workspace_id=membership.workspace_id, visibility=contract.visibility)



def _catalog_item_visible_for_context(state: PlatformState, context: RequestSession, item: dict[str, object]) -> bool:
    visibility = item.get("visibility")
    if not isinstance(visibility, dict):
        return True
    platform_roles = _visibility_string_list(visibility.get("platform_roles"))
    workspace_roles = _visibility_string_list(visibility.get("workspace_roles"))
    capabilities = _visibility_string_list(visibility.get("capabilities"))
    if platform_roles is False or workspace_roles is False or capabilities is False:
        return False
    return can_mount_app_visibility(
        state.workspace_store,
        user=context.user,
        workspace_id=context.workspace_id,
        platform_roles=platform_roles,
        workspace_roles=workspace_roles,
        capabilities=capabilities,
    )



def _visibility_string_list(value: object) -> list[str] | None | bool:
    if value is None:
        return None
    if not isinstance(value, list):
        return False
    return [item for item in value if isinstance(item, str)] or None



def _filter_catalog_for_context(state: PlatformState, catalog: dict[str, object], context: RequestSession) -> dict[str, object]:
    raw_items = catalog.get("items")
    if not isinstance(raw_items, list):
        return catalog
    items = [
        item
        for item in raw_items
        if isinstance(item, dict) and _catalog_item_visible_for_context(state, context, item)
    ]
    return {**catalog, "items": items, "count": len(items)}



def _source_visible_for_context(state: PlatformState, context: RequestSession, contract: AppContractDescriptor) -> bool:
    if context.user.platform_role == "admin":
        return True
    return user_can_mount_app(state, user=context.user, workspace_id=context.workspace_id, visibility=contract.visibility)



def _source_surface_labels(contract: AppContractDescriptor) -> list[str]:
    surfaces = []
    if contract.entrypoints.frontend or contract.capabilities.views or contract.capabilities.view_surfaces:
        surfaces.append("frontend")
    if contract.entrypoints.backend:
        surfaces.append("backend")
    if contract.entrypoints.mcp or contract.capabilities.mcp_tools:
        surfaces.append("mcp")
    if contract.entrypoints.cli or contract.capabilities.cli_commands:
        surfaces.append("cli")
    if contract.capabilities.skills:
        surfaces.append("skills")
    if contract.widgets:
        surfaces.append("widgets")
    return surfaces
