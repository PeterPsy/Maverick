"""Document storage helpers for workspace-domain records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from core.workspaces.errors import WorkspaceMembershipError, WorkspaceNotFoundError
from core.workspaces.errors import WorkspaceDataGovernanceError
from core.workspaces.data_governance import (
    WorkspaceDataAttestation,
    WorkspaceDataGovernanceAudit,
    WorkspaceResourceClassification,
    resource_classification_is_well_formed,
)
from core.workspaces.files import build_export_manifest
from core.workspaces.models import (
    ActiveWorkspaceSelection,
    ExportManifest,
    WorkspaceGovernanceRecord,
    WorkspaceMembershipRecord,
    WorkspaceQuotaRecord,
    WorkspaceRecord,
)


class DocumentCollection(Protocol):
    """Minimal collection protocol used by the control-plane stores."""

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        ...

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]] | Any:
        ...

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> Any:
        ...

    def delete_one(self, query: dict[str, Any]) -> Any:
        ...

    def compare_and_set(self, query: dict[str, Any], update: dict[str, Any]) -> bool:
        ...

    def insert_one_if_absent(
        self,
        query: dict[str, Any],
        document: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
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

    def list_memberships(self) -> list[WorkspaceMembershipRecord]:
        ...

    def list_memberships_for_workspace(self, workspace_id: str) -> list[WorkspaceMembershipRecord]:
        ...

    def delete_memberships_for_user(self, user_id: str) -> None:
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

    def delete_active_workspace(self, user_id: str) -> None:
        ...

    def get_data_attestation(self, workspace_id: str) -> WorkspaceDataAttestation | None:
        ...

    def save_data_attestation(
        self,
        record: WorkspaceDataAttestation,
        *,
        expected_revision: int,
    ) -> WorkspaceDataAttestation:
        ...

    def save_resource_classification(
        self,
        record: WorkspaceResourceClassification,
        *,
        expected_revision: int,
    ) -> WorkspaceResourceClassification:
        ...

    def get_resource_classification(
        self,
        *,
        workspace_id: str,
        resource_kind: str,
        resource_ref: str,
    ) -> WorkspaceResourceClassification | None:
        ...

    def append_data_governance_audit(
        self,
        record: WorkspaceDataGovernanceAudit,
    ) -> WorkspaceDataGovernanceAudit:
        ...

    def get_data_governance_audit(
        self,
        audit_id: str,
    ) -> WorkspaceDataGovernanceAudit | None:
        ...


@dataclass(frozen=True)
class WorkspaceCollections:
    """Collection bundle for workspace persistence."""

    workspaces: DocumentCollection
    memberships: DocumentCollection
    governance: DocumentCollection
    quotas: DocumentCollection
    active_workspace_selections: DocumentCollection
    data_attestations: DocumentCollection | None = None
    resource_classifications: DocumentCollection | None = None
    data_governance_audits: DocumentCollection | None = None


class WorkspaceDocumentStore:
    """Persist workspace-domain records in document collections."""

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

    def list_memberships(self) -> list[WorkspaceMembershipRecord]:
        return [WorkspaceMembershipRecord(**document) for document in self.collections.memberships.find({})]

    def list_memberships_for_workspace(self, workspace_id: str) -> list[WorkspaceMembershipRecord]:
        return [
            WorkspaceMembershipRecord(**document)
            for document in self.collections.memberships.find({"workspace_id": workspace_id})
        ]

    def delete_memberships_for_user(self, user_id: str) -> None:
        documents = self.collections.memberships.find({"user_id": user_id})
        for document in documents:
            membership_id = document.get("membership_id")
            if isinstance(membership_id, str):
                self.collections.memberships.delete_one({"membership_id": membership_id})

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

    def delete_active_workspace(self, user_id: str) -> None:
        self.collections.active_workspace_selections.delete_one({"user_id": user_id})

    def get_data_attestation(self, workspace_id: str) -> WorkspaceDataAttestation | None:
        collection = self._data_governance_collection("data_attestations")
        document = collection.find_one({"workspace_id": workspace_id})
        return None if document is None else _data_attestation(document, workspace_id=workspace_id)

    def save_data_attestation(
        self,
        record: WorkspaceDataAttestation,
        *,
        expected_revision: int,
    ) -> WorkspaceDataAttestation:
        if not record.well_formed:
            raise WorkspaceDataGovernanceError("attestation_invalid")
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
            or record.revision != expected_revision + 1
        ):
            raise WorkspaceDataGovernanceError("attestation_revision_conflict")
        collection = self._data_governance_collection("data_attestations")
        payload = asdict(record)
        if expected_revision == 0:
            _, created = collection.insert_one_if_absent(
                {"workspace_id": record.workspace_id},
                payload,
            )
            if not created:
                raise WorkspaceDataGovernanceError("attestation_revision_conflict")
            return record
        updated = collection.compare_and_set(
            {"workspace_id": record.workspace_id, "revision": expected_revision},
            {"$set": payload},
        )
        if not updated:
            raise WorkspaceDataGovernanceError("attestation_revision_conflict")
        return record

    def save_resource_classification(
        self,
        record: WorkspaceResourceClassification,
        *,
        expected_revision: int,
    ) -> WorkspaceResourceClassification:
        if not resource_classification_is_well_formed(record):
            raise WorkspaceDataGovernanceError("resource_classification_invalid")
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
            or record.revision != expected_revision + 1
        ):
            raise WorkspaceDataGovernanceError(
                "resource_classification_revision_conflict"
            )
        collection = self._data_governance_collection("resource_classifications")
        query = {
            "workspace_id": record.workspace_id,
            "resource_kind": record.resource_kind,
            "resource_ref": record.resource_ref,
        }
        payload = asdict(record)
        if expected_revision == 0:
            _, created = collection.insert_one_if_absent(query, payload)
            if not created:
                raise WorkspaceDataGovernanceError("resource_classification_revision_conflict")
            return record
        updated = collection.compare_and_set(
            {**query, "revision": expected_revision},
            {"$set": payload},
        )
        if not updated:
            raise WorkspaceDataGovernanceError("resource_classification_revision_conflict")
        return record

    def get_resource_classification(
        self,
        *,
        workspace_id: str,
        resource_kind: str,
        resource_ref: str,
    ) -> WorkspaceResourceClassification | None:
        collection = self._data_governance_collection("resource_classifications")
        document = collection.find_one(
            {
                "workspace_id": workspace_id,
                "resource_kind": resource_kind,
                "resource_ref": resource_ref,
            }
        )
        return None if document is None else _resource_classification(document)

    def append_data_governance_audit(
        self,
        record: WorkspaceDataGovernanceAudit,
    ) -> WorkspaceDataGovernanceAudit:
        collection = self._data_governance_collection("data_governance_audits")
        _, created = collection.insert_one_if_absent(
            {"audit_id": record.audit_id},
            asdict(record),
        )
        if not created:
            raise WorkspaceDataGovernanceError("data_governance_audit_conflict")
        return record

    def get_data_governance_audit(
        self,
        audit_id: str,
    ) -> WorkspaceDataGovernanceAudit | None:
        collection = self._data_governance_collection("data_governance_audits")
        document = collection.find_one({"audit_id": audit_id})
        return (
            None
            if document is None
            else WorkspaceDataGovernanceAudit(**document)
        )

    def list_data_governance_audits(
        self,
        *,
        workspace_id: str,
    ) -> list[WorkspaceDataGovernanceAudit]:
        collection = self._data_governance_collection("data_governance_audits")
        return [
            WorkspaceDataGovernanceAudit(**document)
            for document in collection.find({"workspace_id": workspace_id})
        ]

    def _data_governance_collection(self, name: str) -> DocumentCollection:
        collection = getattr(self.collections, name)
        if collection is None:
            raise WorkspaceDataGovernanceError("data_governance_store_unavailable")
        return collection


def export_manifest_for_files(
    workspace_id: str,
    workspace_root: Any,
    files: list[Any],
    *,
    app_bindings: list[Any] | None = None,
    schema_versions: dict[str, str] | None = None,
) -> ExportManifest:
    """Build the export manifest for a selected workspace file set."""
    return build_export_manifest(
        workspace_id=workspace_id,
        workspace_root=workspace_root,
        files=files,
        app_bindings=app_bindings,
        schema_versions=schema_versions,
    )


def _data_attestation(
    document: dict[str, Any],
    *,
    workspace_id: str,
) -> WorkspaceDataAttestation:
    """Hydrate historical documents as non-authoritative unless every field exists."""
    payload = dict(document)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    payload.setdefault("attestation_id", "legacy-unverified")
    payload["workspace_id"] = workspace_id
    payload.setdefault("declaration", "legacy_unverified")
    payload.setdefault("scope_type", "invalid")
    raw_prefixes = payload.get("resource_prefixes", ())
    if isinstance(raw_prefixes, (list, tuple)):
        payload["resource_prefixes"] = tuple(raw_prefixes)
    else:
        payload["scope_type"] = "invalid"
        payload["resource_prefixes"] = ()
    payload.setdefault("status", "revoked")
    payload.setdefault("revision", 0)
    payload.setdefault("attested_by_actor_id", "")
    payload.setdefault("attested_by_actor_kind", "")
    payload.setdefault("attested_at", epoch)
    payload.setdefault("updated_at", epoch)
    payload.setdefault("revoked_by_actor_id", None)
    payload.setdefault("revoked_at", None)
    payload.setdefault("revocation_reason", "legacy_attestation_unverified")
    allowed = WorkspaceDataAttestation.__dataclass_fields__
    return WorkspaceDataAttestation(**{key: value for key, value in payload.items() if key in allowed})


def _resource_classification(document: dict[str, Any]) -> WorkspaceResourceClassification:
    payload = dict(document)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    payload.setdefault("classification_id", "legacy-unverified")
    payload.setdefault("workspace_id", "")
    payload.setdefault("resource_kind", "")
    payload.setdefault("resource_ref", "")
    payload.setdefault("resource_identity", "")
    payload.setdefault("resource_revision", "")
    payload.setdefault("resource_digest", "")
    payload.setdefault("data_class", "unclassified")
    payload.setdefault("trust_level", "untrusted_external")
    payload.setdefault("revision", 0)
    payload.setdefault("classified_by_actor_id", "")
    payload.setdefault("classified_at", epoch)
    payload.setdefault("updated_at", epoch)
    allowed = WorkspaceResourceClassification.__dataclass_fields__
    return WorkspaceResourceClassification(**{key: value for key, value in payload.items() if key in allowed})
