"""In-memory collection doubles shared by domain tests."""

from __future__ import annotations


class FakeCollection:
    """Small document collection double for store adapter tests."""

    def __init__(self) -> None:
        self.documents: list[dict] = []

    def find_one(self, query: dict) -> dict | None:
        for document in self.documents:
            if _matches(document, query):
                return dict(document)
        return None

    def find(self, query: dict) -> list[dict]:
        return [dict(document) for document in self.documents if _matches(document, query)]

    def update_one(self, query: dict, update: dict, *, upsert: bool = False) -> bool:
        payload = dict(update.get("$set", {}))
        for index, document in enumerate(self.documents):
            if _matches(document, query):
                self.documents[index] = {**document, **payload}
                return True
        if upsert:
            self.documents.append({**query, **payload})
            return True
        return False

    def compare_and_set(self, query: dict, update: dict) -> bool:
        payload = dict(update.get("$set", {}))
        for index, document in enumerate(self.documents):
            if _matches(document, query):
                self.documents[index] = {**document, **payload}
                return True
        return False

    def insert_one_if_absent(self, query: dict, document: dict) -> tuple[dict, bool]:
        payload = {**query, **document}
        for existing in self.documents:
            if _matches(existing, query):
                return dict(existing), False
        self.documents.append(payload)
        return dict(payload), True

    def delete_one(self, query: dict) -> None:
        for index, document in enumerate(self.documents):
            if _matches(document, query):
                self.documents.pop(index)
                return

    def delete_many(self, query: dict) -> int:
        return len(self.delete_many_documents(query))

    def delete_many_documents(self, query: dict) -> list[dict]:
        deleted = [dict(document) for document in self.documents if _matches(document, query)]
        retained = [document for document in self.documents if not _matches(document, query)]
        self.documents = retained
        return deleted


def _matches(document: dict, query: dict) -> bool:
    for key, expected in query.items():
        actual = document.get(key)
        if isinstance(expected, dict) and set(expected) == {"$in"}:
            candidates = expected["$in"]
            if not isinstance(candidates, (list, tuple, set, frozenset)) or actual not in candidates:
                return False
        elif actual != expected:
            return False
    return True
