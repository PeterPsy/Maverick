"""App-hosting services for app installation and enablement."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
import shutil
from uuid import uuid4

from core.apps.data_state import read_app_data_state, write_app_data_state
from core.apps.contracts import (
    build_app_compatibility,
    build_app_capabilities,
    build_app_contract,
    build_app_distribution,
    build_app_entrypoints,
    build_app_failure_semantics,
    build_app_health_contract,
    build_app_hook_timeouts,
    build_app_lifecycle,
    build_app_rollback_support,
    build_app_storage,
    _normalize_slug,
    parse_app_contract_file,
    parsed_contract_to_app_source_record,
    parsed_contract_to_workspace_local_project_record,
    utcnow,
    write_app_contract_file,
)
from core.apps.errors import (
    AppDataRootError,
    AppLifecycleError,
    WorkspaceLocalAppProjectNotFoundError,
)
from core.apps.models import (
    AppDataStateRecord,
    AppHookContext,
    AppSourceKind,
    AppSourceRecord,
    ParsedAppContract,
    WorkspaceAppBindingRecord,
    WorkspaceAppReinstallResult,
    WorkspaceAppStatus,
    WorkspaceAppUpgradeResult,
    WorkspaceLocalAppProjectRecord,
)
from core.apps.paths import workspace_app_data_root
from core.apps.store import AppStore
from core.apps.lifecycle import (
    ensure_app_compatible,
    finalize_install_status,
    load_contract_from_source_record,
    load_contract_from_workspace_project,
    run_health_check,
    run_lifecycle_hook,
    run_reactivation_hooks,
)
from core.observability.service import record_platform_audit, record_platform_event
from core.workspaces.paths import workspace_paths

from core.apps.hook_payloads import build_app_health_hook_payload

def probe_workspace_app_health(
    store: AppStore,
    *,
    workspace_id: str,
    app_id: str,
    start_path: Path | None = None,
) -> tuple[bool, str]:
    """Run the declared health contract for one installed workspace app."""
    binding = store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    if binding.source_kind == "workspace_local_project":
        project = store.get_workspace_local_app_project(workspace_id=workspace_id, app_id=app_id)
        source_root, parsed = load_contract_from_workspace_project(project, start_path=start_path)
    else:
        source = store.get_app_source(binding.source_record_id)
        source_root, parsed = load_contract_from_source_record(source, start_path=start_path)
    healthy = run_health_check(
        source_root,
        parsed.contract,
        payload=build_app_health_hook_payload(store, workspace_id=workspace_id, app_id=app_id, start_path=start_path),
    )
    if healthy:
        return True, "App health contract passed."
    return False, "App health contract failed."
