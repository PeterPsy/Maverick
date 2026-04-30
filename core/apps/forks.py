"""Workspace-local app fork orchestration."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
import shutil
from uuid import uuid4

from core.apps.contracts import (
    build_app_distribution,
    parsed_contract_to_workspace_local_project_record,
    write_app_contract_file,
)
from core.apps.errors import AppLifecycleError
from core.apps.models import (
    ParsedAppContract,
    WorkspaceLocalAppProjectRecord,
)
from core.apps.store import AppStore
from core.apps.lifecycle import load_contract_from_source_record
from core.observability.service import record_platform_audit, record_platform_event
from core.workspaces.paths import workspace_paths

from core.apps.registration import register_workspace_local_app_project

def fork_store_app_to_workspace(
    store: AppStore,
    *,
    source_id: str,
    workspace_id: str,
    now: datetime | None = None,
    start_path: Path | None = None,
    overwrite: bool = False,
    observability_store=None,
) -> WorkspaceLocalAppProjectRecord:
    """Create an explicit workspace-local fork from a source-available store app."""
    source = store.get_app_source(source_id)
    source_root, parsed = load_contract_from_source_record(source, start_path=start_path)
    distribution = parsed.contract.distribution
    if distribution.mode != "source_available" or distribution.source_access != "forkable":
        raise AppLifecycleError(f"App source `{source_id}` is not forkable into a workspace.")
    workspace = workspace_paths(workspace_id=workspace_id, start_path=start_path)
    project_root = workspace.apps / parsed.app_id
    temp_root = workspace.apps / f".{parsed.app_id}.fork-tmp-{uuid4().hex}"
    backup_root = workspace.apps / f".{parsed.app_id}.fork-backup-{uuid4().hex}"
    if project_root.exists():
        if not overwrite:
            raise AppLifecycleError(f"Workspace-local app project `{project_root}` already exists.")
    workspace.apps.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns(
        "__pycache__",
        "*.pyc",
        "node_modules",
        "dist",
        "build",
        ".venv",
        ".mypy_cache",
        ".pytest_cache",
    )
    forked_contract = replace(
        parsed.contract,
        distribution=build_app_distribution(
            mode="workspace_local",
            source_access="editable",
        ),
    )
    forked = ParsedAppContract(
        app_id=parsed.app_id,
        name=parsed.name,
        version=parsed.version,
        description=parsed.description,
        publisher=parsed.publisher,
        contract=forked_contract,
    )
    backup_created = False
    try:
        shutil.copytree(source_root, temp_root, ignore=ignore)
        write_app_contract_file(temp_root, forked)
        if project_root.exists():
            project_root.rename(backup_root)
            backup_created = True
        temp_root.rename(project_root)
    except Exception:
        if backup_created and project_root.exists():
            shutil.rmtree(project_root)
        if backup_created and backup_root.exists() and not project_root.exists():
            backup_root.rename(project_root)
        raise
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root)
        if backup_root.exists():
            shutil.rmtree(backup_root)
    record = parsed_contract_to_workspace_local_project_record(
        parsed=forked,
        workspace_id=workspace_id,
        project_root=str(project_root),
        forked_from_source_id=source.source_id,
        forked_from_version=source.version,
        now=now,
    )
    saved = register_workspace_local_app_project(store, record)
    if observability_store is not None:
        payload = {
            "workspace_id": workspace_id,
            "app_id": parsed.app_id,
            "source_id": source.source_id,
            "source_version": source.version,
            "project_id": saved.project_id,
        }
        record_platform_audit(
            observability_store,
            action="app.fork",
            status="succeeded",
            source_domain="apps",
            detail=f"Forked store app `{parsed.app_id}` into workspace `{workspace_id}`.",
            workspace_id=workspace_id,
            app_id=parsed.app_id,
            payload=payload,
        )
        record_platform_event(
            observability_store,
            event_type="app.forked",
            event_plane="workspace",
            source_domain="apps",
            workspace_id=workspace_id,
            app_id=parsed.app_id,
            payload=payload,
        )
    return saved
