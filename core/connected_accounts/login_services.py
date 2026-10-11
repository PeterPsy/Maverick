"""Public Google consent requirements derived from enabled installation apps."""

import logging

from core.apps.errors import AppHostingError
from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.connected_accounts.google import SERVICES


logger = logging.getLogger(__name__)


def required_login_services(state):
    """Expose service identifiers without disclosing workspace or app inventory."""
    if not getattr(state, "app_store", None) or not getattr(state, "workspace_store", None):
        return []
    services = set()
    for workspace in state.workspace_store.list_workspaces():
        if workspace.status != "active":
            continue
        for binding in enabled_workspace_app_bindings(state.app_store, workspace_id=workspace.workspace_id):
            try:
                _, parsed = resolve_workspace_app_surface(
                    state.app_store, binding=binding, start_path=state.repository_root,
                )
            except AppHostingError:
                logger.warning("Skipping unavailable app contract when deriving Google login services.")
                continue
            declaration = parsed.contract.permissions.external_accounts.get("google")
            if declaration:
                services.update(set(declaration.capabilities) & SERVICES.keys())
    return [service for service in SERVICES if service in services]
