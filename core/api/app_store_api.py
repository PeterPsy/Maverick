"""Authenticated Maverick App Store API surface."""

from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path

from core.api.http import StartResponse, json_response, read_json_body, status_line
from core.api.app_registry import user_can_mount_app
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession, require_session
from core.apps.errors import AppHostingError
from core.apps.models import AppContractDescriptor, WorkspaceAppBindingRecord, WorkspaceLocalAppProjectRecord
from core.apps.remote_store import catalog_base_url, fetch_remote_catalog, install_remote_store_app
from core.apps.paths import workspace_apps_root
from core.apps.service import (
    delete_workspace_local_app_project,
    install_workspace_local_app,
    register_workspace_local_app_project_from_contract,
    uninstall_workspace_app,
)
from core.apps.workspace_local_discovery import discover_workspace_local_app_projects
from core.workspaces.models import WorkspaceMembershipRecord
from core.workspaces.errors import WorkspaceMembershipError, WorkspaceNotFoundError


def _catalog_base_url() -> str:
    return catalog_base_url(os.environ.get("MAVERICK_APP_STORE_URL"))


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
    context: RequestSession,
    membership: WorkspaceMembershipRecord,
    contract: AppContractDescriptor,
) -> bool:
    if _can_manage_workspace_apps(context, membership):
        return True
    return user_can_mount_app(context.user, contract.visibility.platform_roles)


def _catalog_item_visible_for_context(context: RequestSession, item: dict[str, object]) -> bool:
    visibility = item.get("visibility")
    if not isinstance(visibility, dict):
        return True
    platform_roles = visibility.get("platform_roles")
    if platform_roles is None:
        return True
    if not isinstance(platform_roles, list):
        return False
    roles = [role for role in platform_roles if isinstance(role, str)]
    if not roles:
        return True
    return context.user.platform_role in roles


def _filter_catalog_for_context(catalog: dict[str, object], context: RequestSession) -> dict[str, object]:
    raw_items = catalog.get("items")
    if not isinstance(raw_items, list):
        return catalog
    items = [
        item
        for item in raw_items
        if isinstance(item, dict) and _catalog_item_visible_for_context(context, item)
    ]
    return {**catalog, "items": items, "count": len(items)}


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
    return _app_visible_for_context(context, membership, contract)


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
        return user_can_mount_app(context.user, project.contract.visibility.platform_roles)
    if binding is None:
        return False
    return _app_visible_for_context(context, membership, project.contract)


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
            items.append(
                {
                    "workspace_id": workspace_id,
                    "app_id": binding.app_id,
                    "status": binding.status,
                    "active_version": binding.active_version,
                    "source_kind": binding.source_kind,
                    "source_record_id": binding.source_record_id,
                }
            )
    return {"items": items}


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
                    }
                )
        for project in state.app_store.list_workspace_local_app_projects(workspace_id):
            binding = bindings.get(project.app_id)
            if not _local_project_visible_for_context(state, context, membership, project, binding):
                continue
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
                }
            )
    return items


def _workspace_ids_from_body(body: dict, context: RequestSession) -> list[str]:
    raw_workspace_ids = body.get("workspace_ids")
    if raw_workspace_ids is None:
        return [context.workspace_id]
    if not isinstance(raw_workspace_ids, list):
        return []
    return [str(workspace_id).strip() for workspace_id in raw_workspace_ids if str(workspace_id).strip()]


def handle_app_store_api(
    state: PlatformState,
    environ: dict,
    start_response: StartResponse,
    *,
    start_path: Path,
) -> list[bytes] | None:
    """Handle authenticated app-store routes, returning None when not owned here."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    if path not in {
        "/api/app-store/apps",
        "/api/app-store/install",
        "/api/app-store/install-local",
        "/api/app-store/installations",
        "/api/app-store/register-local",
        "/api/app-store/delete-local",
        "/api/app-store/uninstall",
    }:
        return None

    context_or_response = require_session(state, environ, start_response)
    if not isinstance(context_or_response, RequestSession):
        return context_or_response
    context = context_or_response

    if path == "/api/app-store/apps" and method == "GET":
        try:
            catalog = fetch_remote_catalog(_catalog_base_url())
        except Exception as error:
            return json_response(
                start_response,
                {"error": "catalog_unavailable", "detail": str(error)},
                status=status_line(500),
            )
        return json_response(start_response, _filter_catalog_for_context(catalog, context))

    if path == "/api/app-store/installations" and method == "GET":
        workspace_ids = _user_workspace_ids(state, context)
        payload = _installation_payload(state, context, workspace_ids)
        payload["local_apps"] = _local_apps_payload(state, context, workspace_ids, start_path=start_path)
        return json_response(start_response, payload)

    if path == "/api/app-store/install" and method == "POST":
        body = read_json_body(environ)
        app_id = str(body.get("app_id") or "").strip()
        version = str(body.get("version") or "").strip() or None
        workspace_ids = _unique_workspace_ids(_workspace_ids_from_body(body, context))
        authorization_error = _authorize_app_management_targets(state, context, workspace_ids)
        if not app_id:
            return json_response(start_response, {"error": "app_id_required"}, status="400 Bad Request")
        if authorization_error is not None:
            return json_response(start_response, {"error": authorization_error}, status="403 Forbidden")
        try:
            result = install_remote_store_app(
                state.app_store,
                state.workspace_store,
                catalog_base_url=_catalog_base_url(),
                app_id=app_id,
                version=version,
                workspace_ids=workspace_ids,
                start_path=start_path,
                observability_store=state.observability_store,
            )
        except (AppHostingError, WorkspaceNotFoundError) as error:
            return json_response(
                start_response,
                {"error": "install_failed", "detail": str(error)},
                status="400 Bad Request",
            )
        return json_response(start_response, result, status="201 Created")

    if path == "/api/app-store/install-local" and method == "POST":
        body = read_json_body(environ)
        app_id = str(body.get("app_id") or "").strip()
        workspace_ids = _unique_workspace_ids(_workspace_ids_from_body(body, context))
        authorization_error = _authorize_workspace_local_app_targets(state, context, workspace_ids)
        if not app_id:
            return json_response(start_response, {"error": "app_id_required"}, status="400 Bad Request")
        if authorization_error is not None:
            return json_response(start_response, {"error": authorization_error}, status="403 Forbidden")
        try:
            bindings = []
            for workspace_id in workspace_ids:
                discover_workspace_local_app_projects(state.app_store, workspace_id=workspace_id, start_path=start_path)
                binding = install_workspace_local_app(
                    state.app_store,
                    workspace_id=workspace_id,
                    app_id=app_id,
                    start_path=start_path,
                    observability_store=state.observability_store,
                )
                bindings.append(
                    {
                        "workspace_id": binding.workspace_id,
                        "app_id": binding.app_id,
                        "status": binding.status,
                        "active_version": binding.active_version,
                        "source_kind": binding.source_kind,
                        "source_record_id": binding.source_record_id,
                    }
                )
        except (AppHostingError, WorkspaceNotFoundError) as error:
            return json_response(
                start_response,
                {"error": "install_failed", "detail": str(error)},
                status="400 Bad Request",
            )
        return json_response(
            start_response,
            {
                "app": {"app_id": app_id},
                "workspace_ids": workspace_ids,
                "status": "installed",
                "source_kind": "workspace_local_project",
                "items": bindings,
            },
            status="201 Created",
        )

    if path == "/api/app-store/register-local" and method == "POST":
        body = read_json_body(environ)
        app_id = str(body.get("app_id") or "").strip()
        workspace_ids = _unique_workspace_ids(_workspace_ids_from_body(body, context))
        authorization_error = _authorize_workspace_local_app_targets(state, context, workspace_ids)
        if not app_id:
            return json_response(start_response, {"error": "app_id_required"}, status="400 Bad Request")
        if len(workspace_ids) != 1:
            return json_response(start_response, {"error": "single_workspace_required"}, status="400 Bad Request")
        if authorization_error is not None:
            return json_response(start_response, {"error": authorization_error}, status="403 Forbidden")
        workspace_id = workspace_ids[0]
        project_root = workspace_apps_root(workspace_id=workspace_id, start_path=start_path) / app_id
        try:
            project = register_workspace_local_app_project_from_contract(
                state.app_store,
                workspace_id=workspace_id,
                project_root=str(project_root),
            )
        except (AppHostingError, WorkspaceNotFoundError) as error:
            return json_response(
                start_response,
                {"error": "register_failed", "detail": str(error)},
                status="400 Bad Request",
            )
        return json_response(
            start_response,
            {
                "workspace_id": project.workspace_id,
                "project_id": project.project_id,
                "app_id": project.app_id,
                "name": project.name,
                "version": project.version,
                "project_root": project.project_root,
                "status": "registered",
                "source_kind": "workspace_local_project",
            },
            status="201 Created",
        )

    if path == "/api/app-store/delete-local" and method == "POST":
        body = read_json_body(environ)
        app_id = str(body.get("app_id") or "").strip()
        workspace_ids = _unique_workspace_ids(_workspace_ids_from_body(body, context))
        authorization_error = _authorize_app_management_targets(state, context, workspace_ids)
        if not app_id:
            return json_response(start_response, {"error": "app_id_required"}, status="400 Bad Request")
        if authorization_error is not None:
            return json_response(start_response, {"error": authorization_error}, status="403 Forbidden")
        try:
            items = []
            for workspace_id in workspace_ids:
                discover_workspace_local_app_projects(state.app_store, workspace_id=workspace_id, start_path=start_path)
                items.append(
                    delete_workspace_local_app_project(
                        state.app_store,
                        workspace_id=workspace_id,
                        app_id=app_id,
                        start_path=start_path,
                        observability_store=state.observability_store,
                    )
                )
        except (AppHostingError, WorkspaceNotFoundError) as error:
            return json_response(
                start_response,
                {"error": "delete_failed", "detail": str(error)},
                status="400 Bad Request",
            )
        return json_response(
            start_response,
            {
                "app": {"app_id": app_id},
                "workspace_ids": workspace_ids,
                "status": "deleted",
                "items": items,
            },
        )

    if path == "/api/app-store/uninstall" and method == "POST":
        body = read_json_body(environ)
        app_id = str(body.get("app_id") or "").strip()
        workspace_ids = _unique_workspace_ids(_workspace_ids_from_body(body, context))
        authorization_error = _authorize_app_management_targets(state, context, workspace_ids)
        if not app_id:
            return json_response(start_response, {"error": "app_id_required"}, status="400 Bad Request")
        if authorization_error is not None:
            return json_response(start_response, {"error": authorization_error}, status="403 Forbidden")
        try:
            for workspace_id in workspace_ids:
                uninstall_workspace_app(
                    state.app_store,
                    workspace_id=workspace_id,
                    app_id=app_id,
                    observability_store=state.observability_store,
                )
        except AppHostingError as error:
            return json_response(
                start_response,
                {"error": "uninstall_failed", "detail": str(error)},
                status="400 Bad Request",
            )
        return json_response(
            start_response,
            {
                "app": {"app_id": app_id},
                "workspace_ids": workspace_ids,
                "status": "uninstalled",
            },
        )

    return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
