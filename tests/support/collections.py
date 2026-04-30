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

    def update_one(self, query: dict, update: dict, *, upsert: bool = False) -> None:
        payload = dict(update.get("$set", {}))
        for index, document in enumerate(self.documents):
            if _matches(document, query):
                self.documents[index] = {**document, **payload}
                return
        if upsert:
            self.documents.append({**query, **payload})

    def delete_one(self, query: dict) -> None:
        for index, document in enumerate(self.documents):
            if _matches(document, query):
                self.documents.pop(index)
                return


def _matches(document: dict, query: dict) -> bool:
    return all(document.get(key) == value for key, value in query.items())
