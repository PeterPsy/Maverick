"""Small in-memory collection primitives for local bootstrap hosts."""

from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any


class InMemoryCollection:
    """Provide the minimal document collection protocol used by store adapters."""

    def __init__(self) -> None:
        self._documents: list[dict[str, Any]] = []
        self._lock = RLock()

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            for document in self._documents:
                if all(document.get(key) == value for key, value in query.items()):
                    return deepcopy(document)
        return None

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        with self._lock:
            return [
                deepcopy(document)
                for document in self._documents
                if all(document.get(key) == value for key, value in query.items())
            ]

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> None:
        payload = deepcopy(update.get("$set", {}))
        with self._lock:
            for index, document in enumerate(self._documents):
                if all(document.get(key) == value for key, value in query.items()):
                    self._documents[index] = {**document, **payload}
                    return
            if upsert:
                self._documents.append({**deepcopy(query), **payload})

    def insert_one_if_absent(self, query: dict[str, Any], document: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        payload = {**deepcopy(query), **deepcopy(document)}
        with self._lock:
            for existing in self._documents:
                if all(existing.get(key) == value for key, value in query.items()):
                    return deepcopy(existing), False
            self._documents.append(payload)
            return deepcopy(payload), True

    def delete_one(self, query: dict[str, Any]) -> None:
        with self._lock:
            self._documents = [
                document
                for document in self._documents
                if not all(document.get(key) == value for key, value in query.items())
            ]
