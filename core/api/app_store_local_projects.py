"""Authenticated Maverick App Store API surface."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession
from core.apps.models import WorkspaceLocalAppProjectRecord
from core.apps.workspace_local_discovery import discover_workspace_local_app_projects


from core.api.app_store_payloads import _invalid_local_project_visible_for_context, _local_project_visible_for_context
from core.api.app_store_visibility import _can_manage_workspace_apps, _workspace_membership

def _local_apps_payload(state: PlatformState, context: RequestSession, workspace_ids: list[str], *, start_path: Path) -> list[dict[str, object]]:
    items = []
    for workspace_id in workspace_ids:
        membership = _workspace_membership(state, context, workspace_id)
        if membership is None:
            continue
        discovery = discover_workspace_local_app_projects(
            state.app_store,
            workspace_id=workspace_id,
            start_path=start_path,
        )
        bindings = {
            binding.app_id: binding
            for binding in state.app_store.list_workspace_app_bindings(workspace_id)
        }
        if _invalid_local_project_visible_for_context(state, context, membership):
            for invalid in discovery.invalid_projects:
                items.append(
                    {
                        "workspace_id": workspace_id,
                        "project_id": f"{workspace_id}:{invalid.app_id}",
                        "app_id": invalid.app_id,
                        "name": invalid.app_id,
                        "version": "",
                        "description": "Workspace-local app project has an invalid app_contract.json.",
                        "publisher": "workspace",
                        "project_root": invalid.project_root,
                        "distribution": {"mode": "workspace_local", "source_access": "editable"},
                        "installed": False,
                        "status": "invalid",
                        "active_version": None,
                        "binding_source_kind": None,
                        "validation_error": invalid.error,
                        "can_delete": _can_manage_workspace_apps(context, membership),
                        "can_promote": False,
                    }
                )
        for project in state.app_store.list_workspace_local_app_projects(workspace_id):
            binding = bindings.get(project.app_id)
            if not _local_project_visible_for_context(state, context, membership, project, binding):
                continue
            promotion_state = _local_project_promotion_state(state, context, project)
            items.append(
                {
                    "workspace_id": workspace_id,
                    "project_id": project.project_id,
                    "app_id": project.app_id,
                    "name": project.name,
                    "version": project.version,
                    "description": project.description,
                    "publisher": project.publisher,
                    "project_root": project.project_root,
                    "distribution": asdict(project.contract.distribution),
                    "installed": binding is not None,
                    "status": binding.status if binding else "uninstalled",
                    "active_version": binding.active_version if binding else None,
                    "binding_source_kind": binding.source_kind if binding else None,
                    "can_delete": _can_manage_workspace_apps(context, membership),
                    "can_promote": promotion_state["can_promote"],
                    "promotion_kind": promotion_state["promotion_kind"],
                    "promotion_detail": promotion_state["promotion_detail"],
                }
            )
    return items



def _local_project_promotion_state(
    state: PlatformState,
    context: RequestSession,
    project: WorkspaceLocalAppProjectRecord,
) -> dict[str, object]:
    if context.user.platform_role != "admin":
        return {
            "can_promote": False,
            "promotion_kind": "blocked",
            "promotion_detail": "Only platform admins can promote workspace-local apps.",
        }
    platform_sources = [
        source for source in state.app_store.list_app_sources() if source.app_id == project.app_id and source.source_kind == "platform"
    ]
    if not platform_sources:
        return {
            "can_promote": True,
            "promotion_kind": "promote",
            "promotion_detail": "Publish this workspace-local app as a new installation-level app.",
        }
    owner_user_id = next((source.owner_user_id for source in platform_sources if source.owner_user_id), None)
    owner_username = next((source.owner_username for source in platform_sources if source.owner_username), None)
    if owner_user_id is None and project.owner_user_id is not None:
        owner_user_id = project.owner_user_id
        owner_username = project.owner_username
    if owner_user_id is None:
        return {
            "can_promote": False,
            "promotion_kind": "blocked",
            "promotion_detail": (
                f"App id `{project.app_id}` is already claimed by an installation-level app without publish ownership metadata."
            ),
        }
    if context.user.user_id != owner_user_id:
        return {
            "can_promote": False,
            "promotion_kind": "blocked",
            "promotion_detail": (
                f"Only the original app owner `{owner_username or owner_user_id}` can publish updates for `{project.app_id}`."
            ),
        }
    if project.owner_user_id is not None and project.owner_user_id != owner_user_id:
        return {
            "can_promote": False,
            "promotion_kind": "blocked",
            "promotion_detail": (
                f"This workspace-local project belongs to `{project.owner_username or project.owner_user_id}`. "
                "Fork under a different app_id to publish it as a separate app."
            ),
        }
    return {
        "can_promote": True,
        "promotion_kind": "update",
        "promotion_detail": "Publish a new server-wide version of this already-promoted app.",
    }
