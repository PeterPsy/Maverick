"""Small in-memory collection primitives for local bootstrap hosts."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
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
                if _matches(document, query):
                    return deepcopy(document)
        return None

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        with self._lock:
            return [
                deepcopy(document)
                for document in self._documents
                if _matches(document, query)
            ]

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> None:
        payload = deepcopy(update.get("$set", {}))
        with self._lock:
            for index, document in enumerate(self._documents):
                if _matches(document, query):
                    self._documents[index] = {**document, **payload}
                    return
            if upsert:
                self._documents.append({**deepcopy(query), **payload})

    def compare_and_set(self, query: dict[str, Any], update: dict[str, Any]) -> bool:
        """Apply one conditional update and report whether the query matched."""
        payload = deepcopy(update.get("$set", {}))
        with self._lock:
            for index, document in enumerate(self._documents):
                if _matches(document, query):
                    self._documents[index] = {**document, **payload}
                    return True
        return False

    def compare_and_set_if_datetime_future(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        *,
        field: str,
    ) -> bool:
        """Apply one conditional update only while a stored deadline is live."""
        payload = deepcopy(update.get("$set", {}))
        with self._lock:
            for index, document in enumerate(self._documents):
                if _matches(document, query) and _datetime_is_future(document.get(field)):
                    self._documents[index] = {**document, **payload}
                    return True
        return False

    def insert_one_if_absent(self, query: dict[str, Any], document: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        payload = {**deepcopy(query), **deepcopy(document)}
        with self._lock:
            for existing in self._documents:
                if _matches(existing, query):
                    return deepcopy(existing), False
            self._documents.append(payload)
            return deepcopy(payload), True

    def delete_one(self, query: dict[str, Any]) -> None:
        with self._lock:
            self._documents = [
                document
                for document in self._documents
                if not _matches(document, query)
            ]

    def delete_many(self, query: dict[str, Any]) -> int:
        return len(self.delete_many_documents(query))

    def delete_many_documents(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        with self._lock:
            deleted = [deepcopy(document) for document in self._documents if _matches(document, query)]
            retained = [document for document in self._documents if not _matches(document, query)]
            self._documents = retained
            return deleted


def _matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        actual = document.get(key)
        if isinstance(expected, dict) and set(expected) == {"$in"}:
            candidates = expected["$in"]
            if not isinstance(candidates, (list, tuple, set, frozenset)) or actual not in candidates:
                return False
        elif actual != expected:
            return False
    return True


def _datetime_is_future(value: Any) -> bool:
    if not isinstance(value, datetime):
        return False
    now = datetime.now(tz=value.tzinfo) if value.tzinfo is not None else datetime.now()
    return value > now
