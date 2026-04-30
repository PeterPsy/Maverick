"""Record conversion helpers for parsed app contracts."""

from __future__ import annotations

from datetime import datetime

from core.apps.models import (
    AppSourceRecord,
    ParsedAppContract,
    WorkspaceLocalAppProjectRecord,
)

from core.apps.contract_common import _timestamp

def parsed_contract_to_app_source_record(
    *,
    parsed: ParsedAppContract,
    source_kind: str,
    source_path: str,
    source_id: str | None = None,
    now: datetime | None = None,
    created_at: str | None = None,
    owner_user_id: str | None = None,
    owner_username: str | None = None,
    promoted_from_workspace_id: str | None = None,
    promoted_from_project_id: str | None = None,
) -> AppSourceRecord:
    """Persist one parsed app contract as an installation-level app source record."""
    timestamp = _timestamp(now)
    return AppSourceRecord(
        source_id=source_id or f"{source_kind}:{parsed.app_id}:{parsed.version}",
        app_id=parsed.app_id,
        name=parsed.name,
        version=parsed.version,
        description=parsed.description,
        publisher=parsed.publisher,
        source_kind=source_kind,
        source_path=source_path,
        contract=parsed.contract,
        created_at=created_at or timestamp,
        updated_at=timestamp,
        owner_user_id=owner_user_id,
        owner_username=owner_username,
        promoted_from_workspace_id=promoted_from_workspace_id,
        promoted_from_project_id=promoted_from_project_id,
        public_app_id=parsed.app_id,
    )

def parsed_contract_to_workspace_local_project_record(
    *,
    parsed: ParsedAppContract,
    workspace_id: str,
    project_root: str,
    project_id: str | None = None,
    forked_from_source_id: str | None = None,
    forked_from_version: str | None = None,
    now: datetime | None = None,
    created_at: str | None = None,
    owner_user_id: str | None = None,
    owner_username: str | None = None,
) -> WorkspaceLocalAppProjectRecord:
    """Persist one parsed app contract as a workspace-local project record."""
    timestamp = _timestamp(now)
    return WorkspaceLocalAppProjectRecord(
        project_id=project_id or f"{workspace_id}:{parsed.app_id}",
        workspace_id=workspace_id,
        app_id=parsed.app_id,
        name=parsed.name,
        version=parsed.version,
        description=parsed.description,
        publisher=parsed.publisher,
        project_root=project_root,
        contract=parsed.contract,
        created_at=created_at or timestamp,
        updated_at=timestamp,
        owner_user_id=owner_user_id,
        owner_username=owner_username,
        forked_from_source_id=forked_from_source_id,
        forked_from_version=forked_from_version,
        public_app_id=parsed.app_id,
        local_app_id=parsed.app_id,
    )
