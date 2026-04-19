"""Record conversion helpers for parsed app contracts."""

from __future__ import annotations

from datetime import datetime
import re

from core.apps.models import (
    AppSourceRecord,
    ParsedAppContract,
    WorkspaceLocalAppProjectRecord,
)


CURRENT_APP_CONTRACT_VERSION = "1.0"
APP_CONTRACT_FILENAME = "app_contract.json"
APP_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

from core.apps.contract_common import _timestamp

def parsed_contract_to_app_source_record(
    *,
    parsed: ParsedAppContract,
    source_kind: str,
    source_path: str,
    source_id: str | None = None,
    now: datetime | None = None,
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
        created_at=timestamp,
        updated_at=timestamp,
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
        created_at=timestamp,
        updated_at=timestamp,
        forked_from_source_id=forked_from_source_id,
        forked_from_version=forked_from_version,
    )
