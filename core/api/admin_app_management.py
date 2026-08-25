"""Admin-only workspace app installation and enablement management."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from core.api.http import StartResponse, json_response
from core.api.session_api import RequestSession
from core.api.sidecar_proxy import stop_app_sidecars
from core.api.sidecar_prewarm import start_workspace_app_sidecar_prewarms
from core.apps.errors import AppHostingError, WorkspaceAppBindingNotFoundError, WorkspaceLocalAppProjectNotFoundError
from core.apps.models import AppContractDescriptor, AppSourceRecord, WorkspaceAppBindingRecord, WorkspaceLocalAppProjectRecord
from core.apps.service import install_store_app, transition_workspace_app_status, uninstall_workspace_app
from core.api.platform_state import PlatformState
from core.workspaces.errors import WorkspaceNotFoundError


def _contract_payload(contract: AppContractDescriptor) -> dict[str, object]:
    return {
        "distribution": asdict(contract.distribution),
        "visibility": asdict(contract.visibility),
        "capabilities": asdict(contract.capabilities),
        "entrypoints": asdict(contract.entrypoints),
    }


def _binding_payload(binding: WorkspaceAppBindingRecord | None) -> dict[str, object] | None:
    if binding is None:
        return None
    return {
        "binding_id": binding.binding_id,
        "workspace_id": binding.workspace_id,
        "app_id": binding.app_id,
        "source_record_id": binding.source_record_id,
        "source_kind": binding.source_kind,
        "status": binding.status,
        "active_version": binding.active_version,
        "installed_at": binding.installed_at,
        "updated_at": binding.updated_at,
    }


def _latest_sources_by_app(state: PlatformState) -> dict[str, AppSourceRecord]:
    sources: dict[str, AppSourceRecord] = {}
    for source in sorted(state.app_store.list_app_sources(), key=lambda item: (item.app_id, item.version, item.updated_at)):
        sources[source.app_id] = source
    return sources


def _workspace_local_projects_by_app(state: PlatformState, *, workspace_id: str) -> dict[str, WorkspaceLocalAppProjectRecord]:
    return {project.app_id: project for project in state.app_store.list_workspace_local_app_projects(workspace_id)}


def _get_binding_or_none(state: PlatformState, *, workspace_id: str, app_id: str) -> WorkspaceAppBindingRecord | None:
    try:
        return state.app_store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    except WorkspaceAppBindingNotFoundError:
        return None


def _workspace_app_items(state: PlatformState) -> list[dict[str, object]]:
    sources_by_app = _latest_sources_by_app(state)
    items: list[dict[str, object]] = []
    for workspace in sorted(state.workspace_store.list_workspaces(), key=lambda item: item.workspace_id):
        bindings_by_app = {binding.app_id: binding for binding in state.app_store.list_workspace_app_bindings(workspace.workspace_id)}
        projects_by_app = _workspace_local_projects_by_app(state, workspace_id=workspace.workspace_id)
        app_ids = sorted(set(sources_by_app) | set(bindings_by_app))
        for app_id in app_ids:
            source = sources_by_app.get(app_id)
            project = projects_by_app.get(app_id)
            binding = _get_binding_or_none(state, workspace_id=workspace.workspace_id, app_id=app_id)
            if binding and binding.source_kind == "workspace_local_project":
                try:
                    project = project or state.app_store.get_workspace_local_app_project(workspace_id=workspace.workspace_id, app_id=app_id)
                except WorkspaceLocalAppProjectNotFoundError:
                    project = None
            if project and binding and binding.source_kind == "workspace_local_project":
                name = project.name
                description = project.description
                publisher = project.publisher
                version = project.version
                source_id = project.project_id
                source_kind = "workspace_local_project"
                contract = project.contract
            elif source is not None:
                name = source.name
                description = source.description
                publisher = source.publisher
                version = source.version
                source_id = source.source_id
                source_kind = source.source_kind
                contract = source.contract
            else:
                continue
            items.append(
                {
                    "workspace_id": workspace.workspace_id,
                    "workspace_name": workspace.name,
                    "app_id": app_id,
                    "name": name,
                    "description": description,
                    "publisher": publisher,
                    "version": version,
                    "source_id": source_id,
                    "source_kind": source_kind,
                    "installed": binding is not None,
                    "status": binding.status if binding else "uninstalled",
                    "binding": _binding_payload(binding),
                    "contract": _contract_payload(contract),
                }
            )
    return items


def _source_for_install(state: PlatformState, *, app_id: str, source_id: str | None) -> AppSourceRecord:
    if source_id:
        source = state.app_store.get_app_source(source_id)
        if source.app_id != app_id:
            raise AppHostingError(f"Source `{source_id}` does not provide app `{app_id}`.")
        return source
    source = _latest_sources_by_app(state).get(app_id)
    if source is None:
        raise AppHostingError(f"No registered source is available for app `{app_id}`.")
    return source


def _install_workspace_app(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    body: dict,
    start_path: Path,
) -> WorkspaceAppBindingRecord:
    state.workspace_store.get_workspace(workspace_id)
    enabled = bool(body.get("enabled", True))
    source_id = body.get("source_id") if isinstance(body.get("source_id"), str) else None
    source = _source_for_install(state, app_id=app_id, source_id=source_id)
    return install_store_app(
        state.app_store,
        source_id=source.source_id,
        workspace_id=workspace_id,
        enabled=enabled,
        start_path=start_path,
        observability_store=state.observability_store,
    )


def handle_admin_app_management_api(
    state: PlatformState,
    context: RequestSession,
    environ: dict,
    start_response: StartResponse,
    *,
    body: dict,
    start_path: Path,
    shutdown_controller=None,
) -> list[bytes] | None:
    """Handle admin workspace app management routes."""
    del context
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    if path == "/api/admin/workspace-apps" and method == "GET":
        return json_response(start_response, {"items": _workspace_app_items(state)})
    prefix = "/api/admin/workspace-apps/"
    if not path.startswith(prefix):
        return None

    suffix = path.removeprefix(prefix).strip("/")
    workspace_id, separator, app_id = suffix.partition("/")
    if not separator or not workspace_id or not app_id:
        return json_response(start_response, {"error": "invalid_workspace_app_path"}, status="400 Bad Request")
    try:
        if method == "POST":
            binding = _install_workspace_app(
                state,
                workspace_id=workspace_id,
                app_id=app_id,
                body=body,
                start_path=start_path,
            )
            if getattr(state, "repository_root", None) is not None:
                start_workspace_app_sidecar_prewarms(
                    state,
                    binding=binding,
                    trigger="install",
                    shutdown_controller=shutdown_controller,
                )
            return json_response(start_response, _binding_payload(binding) or {}, status="201 Created")
        if method == "PATCH":
            status = str(body.get("status") or "").strip()
            if status not in {"enabled", "disabled"}:
                return json_response(start_response, {"error": "invalid_app_status"}, status="400 Bad Request")
            binding = transition_workspace_app_status(
                state.app_store,
                workspace_id=workspace_id,
                app_id=app_id,
                target_status=status,
                observability_store=state.observability_store,
            )
            if status == "disabled":
                state.sidecar_browser_sessions.revoke_app(workspace_id=workspace_id, app_id=app_id)
                stop_app_sidecars(workspace_id=workspace_id, app_id=app_id)
            else:
                if getattr(state, "repository_root", None) is not None:
                    start_workspace_app_sidecar_prewarms(
                        state,
                        binding=binding,
                        trigger="activation",
                        shutdown_controller=shutdown_controller,
                    )
            return json_response(start_response, _binding_payload(binding) or {})
        if method == "DELETE":
            uninstall_workspace_app(
                state.app_store,
                workspace_id=workspace_id,
                app_id=app_id,
                observability_store=state.observability_store,
            )
            state.sidecar_browser_sessions.revoke_app(workspace_id=workspace_id, app_id=app_id)
            stop_app_sidecars(workspace_id=workspace_id, app_id=app_id)
            return json_response(start_response, {"workspace_id": workspace_id, "app_id": app_id, "status": "uninstalled"})
    except WorkspaceNotFoundError:
        return json_response(start_response, {"error": "workspace_not_found"}, status="404 Not Found")
    except WorkspaceAppBindingNotFoundError:
        return json_response(start_response, {"error": "app_not_installed"}, status="404 Not Found")
    except AppHostingError as error:
        return json_response(start_response, {"error": "app_management_failed", "detail": str(error)}, status="400 Bad Request")

    return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
