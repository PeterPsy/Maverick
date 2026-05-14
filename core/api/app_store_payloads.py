"""Authenticated Maverick App Store API surface."""

from __future__ import annotations

from dataclasses import asdict

from core.api.app_registry import user_can_mount_app
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession
from core.apps.errors import AppHostingError
from core.apps.models import WorkspaceAppBindingRecord, WorkspaceLocalAppProjectRecord
from core.apps.presentation import app_frontend_is_launchable
from core.workspaces.models import WorkspaceMembershipRecord
from core.workspaces.errors import WorkspaceNotFoundError


from core.api.app_store_visibility import (
    _app_visible_for_context,
    _binding_contract,
    _can_manage_workspace_apps,
    _source_surface_labels,
    _source_visible_for_context,
    _workspace_membership,
)

def _server_apps_payload(state: PlatformState, context: RequestSession) -> dict[str, object]:
    grouped: dict[str, list] = {}
    for source in state.app_store.list_app_sources():
        if not _source_visible_for_context(state, context, source.contract):
            continue
        grouped.setdefault(source.app_id, []).append(source)

    items = []
    for app_id, sources in sorted(grouped.items()):
        ordered_sources = sorted(sources, key=lambda source: (source.updated_at, source.version, source.source_id))
        latest = ordered_sources[-1]
        items.append(
            {
                "app_id": app_id,
                "name": latest.name,
                "description": latest.description,
                "publisher": latest.publisher,
                "latest_version": latest.version,
                "source_id": latest.source_id,
                "source_kind": latest.source_kind,
                "distribution": asdict(latest.contract.distribution),
                "presentation": asdict(latest.contract.presentation),
                "frontend_role": latest.contract.presentation.frontend_role,
                "frontend_launchable": app_frontend_is_launchable(latest.contract),
                "surfaces": _source_surface_labels(latest.contract),
                "versions": [
                    {
                        "app_id": source.app_id,
                        "name": source.name,
                        "version": source.version,
                        "description": source.description,
                        "publisher": source.publisher,
                        "source_id": source.source_id,
                        "source_kind": source.source_kind,
                        "distribution": asdict(source.contract.distribution),
                        "presentation": asdict(source.contract.presentation),
                        "frontend_role": source.contract.presentation.frontend_role,
                        "frontend_launchable": app_frontend_is_launchable(source.contract),
                        "surfaces": _source_surface_labels(source.contract),
                    }
                    for source in ordered_sources
                ],
            }
        )
    return {"items": items, "count": len(items)}



def _server_source_for_install(
    state: PlatformState,
    context: RequestSession,
    *,
    app_id: str,
    source_id: str | None,
):
    if source_id:
        source = state.app_store.get_app_source(source_id)
        if source.app_id != app_id:
            raise AppHostingError(f"Source `{source_id}` does not provide app `{app_id}`.")
        if not _source_visible_for_context(state, context, source.contract):
            raise AppHostingError(f"Source `{source_id}` is not available.")
        return source
    candidates = [
        source
        for source in state.app_store.list_app_sources()
        if source.app_id == app_id and _source_visible_for_context(state, context, source.contract)
    ]
    if not candidates:
        raise AppHostingError(f"No registered server source is available for app `{app_id}`.")
    return sorted(candidates, key=lambda source: (source.updated_at, source.version, source.source_id))[-1]



def _installed_binding_visible_for_context(
    state: PlatformState,
    context: RequestSession,
    membership: WorkspaceMembershipRecord,
    binding: WorkspaceAppBindingRecord,
) -> bool:
    try:
        contract = _binding_contract(state, binding)
    except AppHostingError:
        return _can_manage_workspace_apps(context, membership)
    return _app_visible_for_context(state, context, membership, contract)



def _local_project_visible_for_context(
    state: PlatformState,
    context: RequestSession,
    membership: WorkspaceMembershipRecord,
    project: WorkspaceLocalAppProjectRecord,
    binding: WorkspaceAppBindingRecord | None,
) -> bool:
    if _can_manage_workspace_apps(context, membership):
        return True
    try:
        governance = state.workspace_store.get_governance(membership.workspace_id)
    except WorkspaceNotFoundError:
        governance = None
    if governance is not None and governance.allow_custom_apps:
        return user_can_mount_app(state, user=context.user, workspace_id=membership.workspace_id, visibility=project.contract.visibility)
    if binding is None:
        return False
    return _app_visible_for_context(state, context, membership, project.contract)



def _invalid_local_project_visible_for_context(
    state: PlatformState,
    context: RequestSession,
    membership: WorkspaceMembershipRecord,
) -> bool:
    if _can_manage_workspace_apps(context, membership):
        return True
    try:
        governance = state.workspace_store.get_governance(membership.workspace_id)
    except WorkspaceNotFoundError:
        return False
    return governance.allow_custom_apps



def _installation_payload(state: PlatformState, context: RequestSession, workspace_ids: list[str]) -> dict[str, object]:
    items = []
    for workspace_id in workspace_ids:
        membership = _workspace_membership(state, context, workspace_id)
        if membership is None:
            continue
        for binding in state.app_store.list_workspace_app_bindings(workspace_id):
            if not _installed_binding_visible_for_context(state, context, membership, binding):
                continue
            try:
                contract = _binding_contract(state, binding)
                presentation = asdict(contract.presentation)
                frontend_role = contract.presentation.frontend_role
                frontend_launchable = app_frontend_is_launchable(contract)
                surfaces = _source_surface_labels(contract)
            except AppHostingError:
                presentation = {"frontend_role": "none"}
                frontend_role = "none"
                frontend_launchable = False
                surfaces = []
            items.append(
                {
                    "workspace_id": workspace_id,
                    "app_id": binding.app_id,
                    "status": binding.status,
                    "active_version": binding.active_version,
                    "source_kind": binding.source_kind,
                    "source_record_id": binding.source_record_id,
                    "presentation": presentation,
                    "frontend_role": frontend_role,
                    "frontend_launchable": frontend_launchable,
                    "surfaces": surfaces,
                }
            )
    return {"items": items}
