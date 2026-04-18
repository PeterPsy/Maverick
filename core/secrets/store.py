"""Store contracts and Mongo-style adapters for secret-domain records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from core.secrets.errors import SecretBindingError, SecretNotFoundError
from core.secrets.models import SecretBindingRecord, SecretRecord


class MongoCollection(Protocol):
    """Minimal collection protocol used by Mongo-style store adapters."""

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        ...

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]] | Any:
        ...

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> Any:
        ...

    def delete_one(self, query: dict[str, Any]) -> Any:
        ...


class SecretStore(Protocol):
    """Persistence contract for secret metadata, raw values, and bindings."""

    def save_secret(self, record: SecretRecord) -> SecretRecord:
        ...

    def get_secret(self, secret_id: str) -> SecretRecord:
        ...

    def get_secret_by_alias(self, alias: str) -> SecretRecord:
        ...

    def list_secrets(self) -> list[SecretRecord]:
        ...

    def save_secret_value(self, *, secret_id: str, raw_value: str) -> None:
        ...

    def get_secret_value(self, *, secret_id: str) -> str:
        ...

    def delete_secret_value(self, *, secret_id: str) -> None:
        ...

    def save_secret_binding(self, record: SecretBindingRecord) -> SecretBindingRecord:
        ...

    def get_secret_binding(self, binding_id: str) -> SecretBindingRecord:
        ...

    def list_secret_bindings(
        self,
        *,
        workspace_id: str | None = None,
        app_id: str | None = None,
        provider_id: str | None = None,
        scope: str | None = None,
        logical_name: str | None = None,
    ) -> list[SecretBindingRecord]:
        ...


@dataclass(frozen=True)
class SecretCollections:
    """Mongo collection bundle for secret persistence."""

    secrets: MongoCollection
    values: MongoCollection
    bindings: MongoCollection


class MongoSecretStore:
    """Persist secret-domain records in Mongo-style collections."""

    def __init__(self, collections: SecretCollections) -> None:
        self.collections = collections

    def save_secret(self, record: SecretRecord) -> SecretRecord:
        self.collections.secrets.update_one(
            {"secret_id": record.secret_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_secret(self, secret_id: str) -> SecretRecord:
        document = self.collections.secrets.find_one({"secret_id": secret_id})
        if document is None:
            raise SecretNotFoundError(f"Secret `{secret_id}` was not found.")
        return SecretRecord(**document)

    def get_secret_by_alias(self, alias: str) -> SecretRecord:
        document = self.collections.secrets.find_one({"alias": alias})
        if document is None:
            raise SecretNotFoundError(f"Secret alias `{alias}` was not found.")
        return SecretRecord(**document)

    def list_secrets(self) -> list[SecretRecord]:
        return [SecretRecord(**document) for document in self.collections.secrets.find({})]

    def save_secret_value(self, *, secret_id: str, raw_value: str) -> None:
        self.collections.values.update_one(
            {"secret_id": secret_id},
            {"$set": {"secret_id": secret_id, "raw_value": raw_value}},
            upsert=True,
        )

    def get_secret_value(self, *, secret_id: str) -> str:
        document = self.collections.values.find_one({"secret_id": secret_id})
        if document is None:
            raise SecretNotFoundError(f"Secret value for `{secret_id}` was not found.")
        return str(document["raw_value"])

    def delete_secret_value(self, *, secret_id: str) -> None:
        self.collections.values.delete_one({"secret_id": secret_id})

    def save_secret_binding(self, record: SecretBindingRecord) -> SecretBindingRecord:
        self.collections.bindings.update_one(
            {"binding_id": record.binding_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_secret_binding(self, binding_id: str) -> SecretBindingRecord:
        document = self.collections.bindings.find_one({"binding_id": binding_id})
        if document is None:
            raise SecretBindingError(f"Secret binding `{binding_id}` was not found.")
        return SecretBindingRecord(**document)

    def list_secret_bindings(
        self,
        *,
        workspace_id: str | None = None,
        app_id: str | None = None,
        provider_id: str | None = None,
        scope: str | None = None,
        logical_name: str | None = None,
    ) -> list[SecretBindingRecord]:
        query: dict[str, Any] = {}
        if workspace_id is not None:
            query["workspace_id"] = workspace_id
        if app_id is not None:
            query["app_id"] = app_id
        if provider_id is not None:
            query["provider_id"] = provider_id
        if scope is not None:
            query["scope"] = scope
        if logical_name is not None:
            query["logical_name"] = logical_name
        return [SecretBindingRecord(**document) for document in self.collections.bindings.find(query)]
