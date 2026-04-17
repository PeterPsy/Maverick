"""Mongo-oriented storage helpers for workspace-domain records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from core.workspaces.errors import WorkspaceMembershipError, WorkspaceNotFoundError
from core.workspaces.files import build_export_manifest
from core.workspaces.models import (
    ActiveWorkspaceSelection,
    ExportManifest,
    WorkspaceGovernanceRecord,
    WorkspaceMembershipRecord,
    WorkspaceQuotaRecord,
    WorkspaceRecord,
)


class MongoCollection(Protocol):
    """Minimal collection protocol used by the control-plane stores."""

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        ...

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]] | Any:
        ...

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> Any:
        ...


class WorkspaceStore(Protocol):
    """Persistence contract for workspace-domain records."""

    def save_workspace(self, record: WorkspaceRecord) -> WorkspaceRecord:
        ...

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord:
        ...

    def list_workspaces(self) -> list[WorkspaceRecord]:
        ...

    def save_membership(self, record: WorkspaceMembershipRecord) -> WorkspaceMembershipRecord:
        ...

    def get_membership(self, *, user_id: str, workspace_id: str) -> WorkspaceMembershipRecord:
        ...

    def list_memberships_for_user(self, user_id: str) -> list[WorkspaceMembershipRecord]:
        ...

    def save_governance(self, record: WorkspaceGovernanceRecord) -> WorkspaceGovernanceRecord:
        ...

    def get_governance(self, workspace_id: str) -> WorkspaceGovernanceRecord:
        ...

    def save_quota(self, record: WorkspaceQuotaRecord) -> WorkspaceQuotaRecord:
        ...

    def get_quota(self, workspace_id: str) -> WorkspaceQuotaRecord:
        ...

    def set_active_workspace(self, selection: ActiveWorkspaceSelection) -> ActiveWorkspaceSelection:
        ...

    def get_active_workspace(self, user_id: str) -> ActiveWorkspaceSelection | None:
        ...


@dataclass(frozen=True)
class WorkspaceCollections:
    """Mongo collection bundle for workspace persistence."""

    workspaces: MongoCollection
    memberships: MongoCollection
    governance: MongoCollection
    quotas: MongoCollection
    active_workspace_selections: MongoCollection


class MongoWorkspaceStore:
    """Persist workspace-domain records in Mongo-style collections."""

    def __init__(self, collections: WorkspaceCollections) -> None:
        self.collections = collections

    def save_workspace(self, record: WorkspaceRecord) -> WorkspaceRecord:
        self.collections.workspaces.update_one(
            {"workspace_id": record.workspace_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord:
        document = self.collections.workspaces.find_one({"workspace_id": workspace_id})
        if document is None:
            raise WorkspaceNotFoundError(f"Workspace `{workspace_id}` was not found.")
        return WorkspaceRecord(**document)

    def list_workspaces(self) -> list[WorkspaceRecord]:
        return [WorkspaceRecord(**document) for document in self.collections.workspaces.find({})]

    def save_membership(self, record: WorkspaceMembershipRecord) -> WorkspaceMembershipRecord:
        self.collections.memberships.update_one(
            {"membership_id": record.membership_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_membership(self, *, user_id: str, workspace_id: str) -> WorkspaceMembershipRecord:
        document = self.collections.memberships.find_one({"user_id": user_id, "workspace_id": workspace_id})
        if document is None:
            raise WorkspaceMembershipError(
                f"User `{user_id}` does not have a membership in workspace `{workspace_id}`."
            )
        return WorkspaceMembershipRecord(**document)

    def list_memberships_for_user(self, user_id: str) -> list[WorkspaceMembershipRecord]:
        return [WorkspaceMembershipRecord(**document) for document in self.collections.memberships.find({"user_id": user_id})]

    def save_governance(self, record: WorkspaceGovernanceRecord) -> WorkspaceGovernanceRecord:
        self.collections.governance.update_one(
            {"workspace_id": record.workspace_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_governance(self, workspace_id: str) -> WorkspaceGovernanceRecord:
        document = self.collections.governance.find_one({"workspace_id": workspace_id})
        if document is None:
            raise WorkspaceNotFoundError(f"Workspace governance for `{workspace_id}` was not found.")
        return WorkspaceGovernanceRecord(**document)

    def save_quota(self, record: WorkspaceQuotaRecord) -> WorkspaceQuotaRecord:
        self.collections.quotas.update_one(
            {"workspace_id": record.workspace_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_quota(self, workspace_id: str) -> WorkspaceQuotaRecord:
        document = self.collections.quotas.find_one({"workspace_id": workspace_id})
        if document is None:
            raise WorkspaceNotFoundError(f"Workspace quota for `{workspace_id}` was not found.")
        return WorkspaceQuotaRecord(**document)

    def set_active_workspace(self, selection: ActiveWorkspaceSelection) -> ActiveWorkspaceSelection:
        self.collections.active_workspace_selections.update_one(
            {"user_id": selection.user_id},
            {"$set": asdict(selection)},
            upsert=True,
        )
        return selection

    def get_active_workspace(self, user_id: str) -> ActiveWorkspaceSelection | None:
        document = self.collections.active_workspace_selections.find_one({"user_id": user_id})
        if document is None:
            return None
        return ActiveWorkspaceSelection(**document)


def export_manifest_for_files(workspace_id: str, workspace_root: Any, files: list[Any]) -> ExportManifest:
    """Build the export manifest for a selected workspace file set."""
    return build_export_manifest(workspace_id=workspace_id, workspace_root=workspace_root, files=files)
