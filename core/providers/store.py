"""Store adapters for provider-domain control-plane records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from core.providers.errors import ProviderCredentialBindingError, ProviderNotFoundError
from core.providers.models import (
    ProviderCapabilitySet,
    ProviderCredentialBinding,
    ProviderCredentialRequirement,
    ProviderDefinition,
    ProviderExecutionContract,
    ProviderModelOption,
    ProviderNetworkRequirement,
    ProviderReasoningOption,
    ProviderSelection,
)


class DocumentCollection(Protocol):
    """Minimal collection protocol used by provider stores."""

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        ...

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]] | Any:
        ...

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> Any:
        ...


class ProviderStore(Protocol):
    """Persistence contract for provider definitions, bindings, and selection."""

    def save_provider_definition(self, record: ProviderDefinition) -> ProviderDefinition:
        ...

    def get_provider_definition(self, provider_id: str) -> ProviderDefinition:
        ...

    def list_provider_definitions(self) -> list[ProviderDefinition]:
        ...

    def save_provider_binding(self, record: ProviderCredentialBinding) -> ProviderCredentialBinding:
        ...

    def get_provider_binding(self, binding_id: str) -> ProviderCredentialBinding:
        ...

    def list_provider_bindings(
        self,
        *,
        workspace_id: str | None = None,
        provider_id: str | None = None,
    ) -> list[ProviderCredentialBinding]:
        ...

    def save_provider_selection(self, record: ProviderSelection) -> ProviderSelection:
        ...

    def get_provider_selection(self, workspace_id: str) -> ProviderSelection | None:
        ...


@dataclass(frozen=True)
class ProviderCollections:
    """Collection bundle for provider persistence."""

    definitions: DocumentCollection
    bindings: DocumentCollection
    selections: DocumentCollection


class ProviderDocumentStore:
    """Persist provider-domain records in document collections."""

    def __init__(self, collections: ProviderCollections) -> None:
        self.collections = collections

    def _provider_definition(self, document: dict[str, Any]) -> ProviderDefinition:
        payload = dict(document)
        if "provider_role" not in payload:
            payload["provider_role"] = "runtime_engine" if payload.get("kind") == "runtime_backend" else "model_provider"
        payload["capabilities"] = ProviderCapabilitySet(**payload["capabilities"])
        payload["model_options"] = [
            self._provider_model_option(item)
            for item in payload.get("model_options", [])
            if isinstance(item, dict)
        ]
        payload["credential_requirements"] = [
            ProviderCredentialRequirement(**item)
            for item in payload.get("credential_requirements", [])
            if isinstance(item, dict)
        ]
        payload["network_requirements"] = [
            ProviderNetworkRequirement(**item)
            for item in payload.get("network_requirements", [])
            if isinstance(item, dict)
        ]
        execution_contract = payload.get("execution_contract")
        if isinstance(execution_contract, dict):
            payload["execution_contract"] = ProviderExecutionContract(**execution_contract)
        return ProviderDefinition(**payload)

    def _provider_model_option(self, document: dict[str, Any]) -> ProviderModelOption:
        payload = dict(document)
        payload["supported_reasoning_efforts"] = [
            ProviderReasoningOption(**item)
            for item in payload.get("supported_reasoning_efforts", [])
            if isinstance(item, dict)
        ]
        return ProviderModelOption(**payload)

    def save_provider_definition(self, record: ProviderDefinition) -> ProviderDefinition:
        self.collections.definitions.update_one(
            {"provider_id": record.provider_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_provider_definition(self, provider_id: str) -> ProviderDefinition:
        document = self.collections.definitions.find_one({"provider_id": provider_id})
        if document is None:
            raise ProviderNotFoundError(f"Provider `{provider_id}` was not found.")
        return self._provider_definition(document)

    def list_provider_definitions(self) -> list[ProviderDefinition]:
        return [self._provider_definition(document) for document in self.collections.definitions.find({})]

    def save_provider_binding(self, record: ProviderCredentialBinding) -> ProviderCredentialBinding:
        self.collections.bindings.update_one(
            {"binding_id": record.binding_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_provider_binding(self, binding_id: str) -> ProviderCredentialBinding:
        document = self.collections.bindings.find_one({"binding_id": binding_id})
        if document is None:
            raise ProviderCredentialBindingError(f"Provider binding `{binding_id}` was not found.")
        return ProviderCredentialBinding(**document)

    def list_provider_bindings(
        self,
        *,
        workspace_id: str | None = None,
        provider_id: str | None = None,
    ) -> list[ProviderCredentialBinding]:
        query: dict[str, Any] = {}
        if workspace_id is not None:
            query["workspace_id"] = workspace_id
        if provider_id is not None:
            query["provider_id"] = provider_id
        return [ProviderCredentialBinding(**document) for document in self.collections.bindings.find(query)]

    def save_provider_selection(self, record: ProviderSelection) -> ProviderSelection:
        self.collections.selections.update_one(
            {"workspace_id": record.workspace_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_provider_selection(self, workspace_id: str) -> ProviderSelection | None:
        document = self.collections.selections.find_one({"workspace_id": workspace_id})
        if document is None:
            return None
        return ProviderSelection(**document)
