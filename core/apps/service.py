"""Public app-hosting service facade."""

from core.apps.forks import fork_store_app_to_workspace
from core.apps.health import probe_workspace_app_health
from core.apps.hook_payloads import build_app_export_hook_payload, build_app_health_hook_payload
from core.apps.installation import install_store_app, install_workspace_local_app
from core.apps.registration import (
    build_workspace_app_binding_record,
    register_app_source,
    register_app_source_from_contract,
    register_workspace_local_app_project,
    register_workspace_local_app_project_from_contract,
)
from core.apps.reinstall import reinstall_workspace_app
from core.apps.status import purge_workspace_app_data, transition_workspace_app_status, uninstall_workspace_app
from core.apps.upgrades import upgrade_workspace_app

__all__ = [
    "build_app_export_hook_payload",
    "build_app_health_hook_payload",
    "build_workspace_app_binding_record",
    "fork_store_app_to_workspace",
    "install_store_app",
    "install_workspace_local_app",
    "probe_workspace_app_health",
    "purge_workspace_app_data",
    "register_app_source",
    "register_app_source_from_contract",
    "register_workspace_local_app_project",
    "register_workspace_local_app_project_from_contract",
    "reinstall_workspace_app",
    "transition_workspace_app_status",
    "uninstall_workspace_app",
    "upgrade_workspace_app",
]
