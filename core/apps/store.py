"""Store adapters for app-hosting control-plane records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from core.apps.errors import (
    AppSourceNotFoundError,
    WorkspaceAppBindingNotFoundError,
    WorkspaceLocalAppProjectNotFoundError,
)
from core.apps.models import (
    AppCapabilities,
    AppContractDescriptor,
    AppDistributionDeclaration,
    AppEntrypoints,
    AppFailureSemantics,
    AppHealthContract,
    AppHookTimeouts,
    AppLifecycleDeclaration,
    AppCompatibilityDescriptor,
    AppReferenceEntityDeclaration,
    AppRollbackSupport,
    AppSourceRecord,
    AppStorageDeclaration,
    AppStorageIndices,
    AppViewStateActionDeclaration,
    AppViewSurfaceDeclaration,
    AppVisibilityDeclaration,
    WidgetActionDeclaration,
    WidgetDeclaration,
    WidgetFrontendDeclaration,
    WorkspaceAppBindingRecord,
    WorkspaceLocalAppProjectRecord,
)


class MongoCollection(Protocol):
    """Minimal collection protocol used by Mongo-backed control-plane stores."""

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        ...

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]] | Any:
        ...

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> Any:
        ...

    def delete_one(self, query: dict[str, Any]) -> Any:
        ...


class AppStore(Protocol):
    """Persistence contract for app-hosting control-plane records."""

    def save_app_source(self, record: AppSourceRecord) -> AppSourceRecord:
        ...

    def get_app_source(self, source_id: str) -> AppSourceRecord:
        ...

    def list_app_sources(self) -> list[AppSourceRecord]:
        ...

    def save_workspace_local_app_project(self, record: WorkspaceLocalAppProjectRecord) -> WorkspaceLocalAppProjectRecord:
        ...

    def get_workspace_local_app_project(self, *, workspace_id: str, app_id: str) -> WorkspaceLocalAppProjectRecord:
        ...

    def list_workspace_local_app_projects(self, workspace_id: str) -> list[WorkspaceLocalAppProjectRecord]:
        ...

    def delete_workspace_local_app_project(self, *, workspace_id: str, app_id: str) -> None:
        ...

    def save_workspace_app_binding(self, record: WorkspaceAppBindingRecord) -> WorkspaceAppBindingRecord:
        ...

    def get_workspace_app_binding(self, *, workspace_id: str, app_id: str) -> WorkspaceAppBindingRecord:
        ...

    def list_workspace_app_bindings(self, workspace_id: str) -> list[WorkspaceAppBindingRecord]:
        ...

    def delete_workspace_app_binding(self, *, workspace_id: str, app_id: str) -> None:
        ...


@dataclass(frozen=True)
class AppCollections:
    """Mongo collection bundle for app-hosting control-plane persistence."""

    app_sources: MongoCollection
    workspace_local_app_projects: MongoCollection
    workspace_app_bindings: MongoCollection


class MongoAppStore:
    """Persist app-hosting control-plane records in Mongo-style collections."""

    def __init__(self, collections: AppCollections) -> None:
        self.collections = collections

    def _app_contract(self, payload: dict[str, Any]) -> AppContractDescriptor:
        capabilities_payload = dict(payload["capabilities"])
        capabilities_payload["reference_entities"] = [
            AppReferenceEntityDeclaration(**entity)
            for entity in capabilities_payload.get("reference_entities", [])
        ]
        capabilities_payload["view_surfaces"] = [
            AppViewSurfaceDeclaration(
                **{
                    **surface,
                    "state_actions": [
                        AppViewStateActionDeclaration(**action)
                        for action in surface.get("state_actions", [])
                    ],
                }
            )
            for surface in capabilities_payload.get("view_surfaces", [])
        ]
        return AppContractDescriptor(
            distribution=AppDistributionDeclaration(**payload["distribution"]),
            visibility=AppVisibilityDeclaration(**payload.get("visibility", {"platform_roles": None})),
            compatibility=AppCompatibilityDescriptor(**payload["compatibility"]),
            storage=AppStorageDeclaration(
                **{
                    **payload["storage"],
                    "indices": (
                        AppStorageIndices(**payload["storage"]["indices"])
                        if payload["storage"].get("indices") is not None
                        else None
                    ),
                }
            ),
            capabilities=AppCapabilities(**capabilities_payload),
            lifecycle=AppLifecycleDeclaration(**payload["lifecycle"]),
            entrypoints=AppEntrypoints(**payload["entrypoints"]),
            hook_timeouts=AppHookTimeouts(**payload["hook_timeouts"]),
            failure_semantics=AppFailureSemantics(**payload["failure_semantics"]),
            health_contract=AppHealthContract(**payload["health_contract"]),
            rollback_support=AppRollbackSupport(**payload["rollback_support"]),
            widgets=[
                WidgetDeclaration(
                    widget_id=widget["widget_id"],
                    host=widget["host"],
                    content_kinds=list(widget["content_kinds"]),
                    frontend=WidgetFrontendDeclaration(**widget["frontend"]),
                    actions=WidgetActionDeclaration(**widget["actions"]),
                )
                for widget in payload.get("widgets", [])
            ],
        )

    def _app_source_record(self, document: dict[str, Any]) -> AppSourceRecord:
        payload = dict(document)
        payload["contract"] = self._app_contract(payload["contract"])
        return AppSourceRecord(**payload)

    def _workspace_local_project_record(self, document: dict[str, Any]) -> WorkspaceLocalAppProjectRecord:
        payload = dict(document)
        payload["contract"] = self._app_contract(payload["contract"])
        return WorkspaceLocalAppProjectRecord(**payload)

    def save_app_source(self, record: AppSourceRecord) -> AppSourceRecord:
        self.collections.app_sources.update_one(
            {"source_id": record.source_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_app_source(self, source_id: str) -> AppSourceRecord:
        document = self.collections.app_sources.find_one({"source_id": source_id})
        if document is None:
            raise AppSourceNotFoundError(f"App source `{source_id}` was not found.")
        return self._app_source_record(document)

    def list_app_sources(self) -> list[AppSourceRecord]:
        return [self._app_source_record(document) for document in self.collections.app_sources.find({})]

    def save_workspace_local_app_project(self, record: WorkspaceLocalAppProjectRecord) -> WorkspaceLocalAppProjectRecord:
        self.collections.workspace_local_app_projects.update_one(
            {"workspace_id": record.workspace_id, "app_id": record.app_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_workspace_local_app_project(self, *, workspace_id: str, app_id: str) -> WorkspaceLocalAppProjectRecord:
        document = self.collections.workspace_local_app_projects.find_one(
            {"workspace_id": workspace_id, "app_id": app_id}
        )
        if document is None:
            raise WorkspaceLocalAppProjectNotFoundError(
                f"Workspace-local app project `{app_id}` was not found in workspace `{workspace_id}`."
            )
        return self._workspace_local_project_record(document)

    def list_workspace_local_app_projects(self, workspace_id: str) -> list[WorkspaceLocalAppProjectRecord]:
        return [
            self._workspace_local_project_record(document)
            for document in self.collections.workspace_local_app_projects.find({"workspace_id": workspace_id})
        ]

    def delete_workspace_local_app_project(self, *, workspace_id: str, app_id: str) -> None:
        self.collections.workspace_local_app_projects.delete_one({"workspace_id": workspace_id, "app_id": app_id})

    def save_workspace_app_binding(self, record: WorkspaceAppBindingRecord) -> WorkspaceAppBindingRecord:
        self.collections.workspace_app_bindings.update_one(
            {"workspace_id": record.workspace_id, "app_id": record.app_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_workspace_app_binding(self, *, workspace_id: str, app_id: str) -> WorkspaceAppBindingRecord:
        document = self.collections.workspace_app_bindings.find_one({"workspace_id": workspace_id, "app_id": app_id})
        if document is None:
            raise WorkspaceAppBindingNotFoundError(
                f"Workspace app binding `{app_id}` was not found in workspace `{workspace_id}`."
            )
        return WorkspaceAppBindingRecord(**document)

    def list_workspace_app_bindings(self, workspace_id: str) -> list[WorkspaceAppBindingRecord]:
        return [
            WorkspaceAppBindingRecord(**document)
            for document in self.collections.workspace_app_bindings.find({"workspace_id": workspace_id})
        ]

    def delete_workspace_app_binding(self, *, workspace_id: str, app_id: str) -> None:
        self.collections.workspace_app_bindings.delete_one({"workspace_id": workspace_id, "app_id": app_id})
