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

from core.apps.service_common import _build_workspace_hook_payload, _ensure_workspace_app_data_root

def build_app_export_hook_payload(
    store: AppStore,
    *,
    workspace_id: str,
    app_id: str,
    start_path: Path | None = None,
) -> dict[str, object]:
    """Build the canonical payload passed to one app export hook."""
    binding = store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    data_root = _ensure_workspace_app_data_root(workspace_id=workspace_id, app_id=app_id, start_path=start_path)
    return _build_workspace_hook_payload(
        workspace_id=workspace_id,
        app_id=app_id,
        data_root=data_root,
        source_kind=binding.source_kind,
        source_record_id=binding.source_record_id,
        hook_name="workspace_export",
        start_path=start_path,
    )

def build_app_health_hook_payload(
    store: AppStore,
    *,
    workspace_id: str,
    app_id: str,
    start_path: Path | None = None,
) -> dict[str, object]:
    """Build the canonical payload passed to one app health hook."""
    binding = store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    data_root = _ensure_workspace_app_data_root(workspace_id=workspace_id, app_id=app_id, start_path=start_path)
    return _build_workspace_hook_payload(
        workspace_id=workspace_id,
        app_id=app_id,
        data_root=data_root,
        source_kind=binding.source_kind,
        source_record_id=binding.source_record_id,
        hook_name="health_check",
        start_path=start_path,
    )
