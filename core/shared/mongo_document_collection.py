"""MongoDB-backed document collection for control-plane persistence."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any


class MongoDocumentCollection:
    """Provide the document collection protocol backed by a Mongo collection."""

    def __init__(self, collection: Any) -> None:
        self.collection = collection

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        document = self.collection.find_one(deepcopy(query))
        if document is None:
            return None
        return _without_mongo_id(document)

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        return [_without_mongo_id(document) for document in self.collection.find(deepcopy(query))]

    def find_recent(self, query: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        cursor = self.collection.find(deepcopy(query)).sort([("created_at", -1), ("event_id", -1), ("turn_id", -1)]).limit(limit)
        return [_without_mongo_id(document) for document in reversed(list(cursor))]

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> None:
        payload = deepcopy(update.get("$set", {}))
        if upsert:
            payload = {**deepcopy(query), **payload}
        mongo_update: dict[str, Any] = {}
        if payload:
            mongo_update["$set"] = payload
        unset_payload = deepcopy(update.get("$unset", {}))
        if unset_payload:
            mongo_update["$unset"] = unset_payload
        if not mongo_update:
            return
        self.collection.update_one(deepcopy(query), mongo_update, upsert=upsert)

    def insert_one_if_absent(self, query: dict[str, Any], document: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Atomically insert one document when no record matches the identity query."""
        payload = {**deepcopy(query), **deepcopy(document)}
        try:
            update_result = self.collection.update_one(
                deepcopy(query),
                {"$setOnInsert": payload},
                upsert=True,
            )
        except Exception as error:
            if not _is_duplicate_key_error(error):
                raise
            document_result = self.collection.find_one(deepcopy(query))
            if document_result is None:
                raise
            return _without_mongo_id(document_result), False
        document_result = self.collection.find_one(deepcopy(query))
        if document_result is None:
            raise RuntimeError("Mongo insert-if-absent did not return a document.")
        inserted = getattr(update_result, "upserted_id", None) is not None
        return _without_mongo_id(document_result), inserted

    def delete_one(self, query: dict[str, Any]) -> None:
        self.collection.delete_one(deepcopy(query))

    def replace_all(self, documents: list[dict[str, Any]]) -> None:
        """Replace the full collection content."""
        if not all(isinstance(document, dict) for document in documents):
            raise ValueError("Mongo collections can only store object documents.")
        self.collection.delete_many({})
        if documents:
            self.collection.insert_many([deepcopy(document) for document in documents])


def _without_mongo_id(document: dict[str, Any]) -> dict[str, Any]:
    sanitized = deepcopy(document)
    sanitized.pop("_id", None)
    return _normalize_document_values(sanitized)


def _is_duplicate_key_error(error: Exception) -> bool:
    """Recognize the optional driver's duplicate-key error without importing it eagerly."""
    try:
        from pymongo.errors import DuplicateKeyError
    except ImportError:
        return type(error).__name__ == "DuplicateKeyError"
    return isinstance(error, DuplicateKeyError)


def _normalize_document_values(value: Any) -> Any:
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    if isinstance(value, dict):
        return {key: _normalize_document_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_document_values(item) for item in value]
    return value
