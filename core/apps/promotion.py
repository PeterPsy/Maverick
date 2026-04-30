"""Promotion of workspace-local apps into installation-level platform apps."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Literal
from uuid import uuid4
from dataclasses import replace

from core.apps.errors import AppLifecycleError
from core.apps.paths import installed_app_root, workspace_app_source_root
from core.apps.registration import register_app_source_from_contract, register_workspace_local_app_project
from core.apps.source_policy import ignored_app_source_names
from core.apps.store import AppStore


PromotionMode = Literal["sealed", "forkable"]


def promote_workspace_local_app_project(
    store: AppStore,
    *,
    workspace_id: str,
    app_id: str,
    promotion_mode: PromotionMode,
    start_path: Path | None = None,
    actor_user_id: str | None = None,
    actor_username: str | None = None,
) -> dict[str, str]:
    """Publish or update one workspace-local app project as an installation-level platform app."""
    project = store.get_workspace_local_app_project(workspace_id=workspace_id, app_id=app_id)
    source_root = workspace_app_source_root(workspace_id=workspace_id, app_id=app_id, start_path=start_path)
    if not source_root.is_dir():
        raise AppLifecycleError(f"Workspace-local app project `{app_id}` is missing from `{source_root}`.")
    if project.owner_user_id is None and actor_user_id is not None:
        project = register_workspace_local_app_project(
            store,
            replace(project, owner_user_id=actor_user_id, owner_username=actor_username),
        )

    existing_sources = [
        source for source in store.list_app_sources() if source.app_id == app_id and source.source_kind == "platform"
    ]
    existing_owner_user_id = next((source.owner_user_id for source in existing_sources if source.owner_user_id), None)
    existing_owner_username = next((source.owner_username for source in existing_sources if source.owner_username), None)
    if existing_sources and existing_owner_user_id is None and project.owner_user_id is not None:
        existing_owner_user_id = project.owner_user_id
        existing_owner_username = project.owner_username
    if existing_sources and existing_owner_user_id is None:
        raise AppLifecycleError(
            f"Installation-level app `{app_id}` is already registered without workspace-publish ownership metadata."
        )
    if existing_owner_user_id is not None and actor_user_id != existing_owner_user_id:
        owner_label = existing_owner_username or existing_owner_user_id
        raise AppLifecycleError(
            f"Only the original app owner `{owner_label}` can publish updates for `{app_id}`."
        )
    if (
        existing_owner_user_id is not None
        and project.owner_user_id is not None
        and project.owner_user_id != existing_owner_user_id
    ):
        raise AppLifecycleError(
            f"Workspace-local project `{app_id}` belongs to `{project.owner_username or project.owner_user_id}` and "
            f"cannot update the promoted app owned by `{existing_owner_username or existing_owner_user_id}`. "
            "Fork under a different app_id to publish a separate app."
        )

    destination_root = installed_app_root(app_id=app_id, start_path=start_path)
    if existing_sources:
        _replace_promoted_app_root(source_root, destination_root)
    else:
        if destination_root.exists():
            raise AppLifecycleError(f"Installation-level app root `{destination_root}` already exists.")
        shutil.copytree(source_root, destination_root, ignore=ignored_app_source_names)
    _rewrite_promoted_contract(destination_root / "app_contract.json", promotion_mode=promotion_mode)
    source_record = register_app_source_from_contract(
        store,
        source_kind="platform",
        source_path=str(destination_root),
        owner_user_id=existing_owner_user_id or project.owner_user_id or actor_user_id,
        owner_username=existing_owner_username or project.owner_username or actor_username,
        promoted_from_workspace_id=workspace_id,
        promoted_from_project_id=project.project_id,
    )
    return {
        "status": "updated" if existing_sources else "promoted",
        "workspace_id": workspace_id,
        "app_id": app_id,
        "promotion_mode": promotion_mode,
        "source_kind": source_record.source_kind,
        "source_record_id": source_record.source_id,
        "source_path": source_record.source_path,
        "project_root": str(source_root),
    }


def _rewrite_promoted_contract(contract_path: Path, *, promotion_mode: PromotionMode) -> None:
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    if promotion_mode == "sealed":
        distribution = {"mode": "sealed", "source_access": "none"}
    elif promotion_mode == "forkable":
        distribution = {"mode": "source_available", "source_access": "forkable"}
    else:
        raise AppLifecycleError(f"Unsupported promotion mode `{promotion_mode}`.")
    payload["distribution"] = distribution
    contract_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _replace_promoted_app_root(source_root: Path, destination_root: Path) -> None:
    apps_root = destination_root.parent
    temp_root = apps_root / f".{destination_root.name}.publish-tmp-{uuid4().hex}"
    backup_root = apps_root / f".{destination_root.name}.publish-backup-{uuid4().hex}"
    backup_created = False
    try:
        shutil.copytree(source_root, temp_root, ignore=ignored_app_source_names)
        if destination_root.exists():
            destination_root.rename(backup_root)
            backup_created = True
        temp_root.rename(destination_root)
    except Exception:
        if backup_created and destination_root.exists():
            shutil.rmtree(destination_root)
        if backup_created and backup_root.exists() and not destination_root.exists():
            backup_root.rename(destination_root)
        raise
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root)
        if backup_root.exists():
            shutil.rmtree(backup_root)
