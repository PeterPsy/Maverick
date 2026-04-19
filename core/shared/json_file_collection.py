"""JSON-file backed collection for local hosted bootstrap persistence."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from threading import RLock
from typing import Any


DATETIME_MARKER = "__maverick_datetime__"


class JsonFileCollection:
    """Provide the Mongo-like collection protocol backed by one JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            for document in self._read_documents():
                if _matches(document, query):
                    return deepcopy(document)
        return None

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        with self._lock:
            return [deepcopy(document) for document in self._read_documents() if _matches(document, query)]

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> None:
        payload = deepcopy(update.get("$set", {}))
        with self._lock:
            documents = self._read_documents()
            for index, document in enumerate(documents):
                if _matches(document, query):
                    documents[index] = {**document, **payload}
                    self._write_documents(documents)
                    return
            if upsert:
                documents.append({**deepcopy(query), **payload})
                self._write_documents(documents)

    def delete_one(self, query: dict[str, Any]) -> None:
        with self._lock:
            documents = [document for document in self._read_documents() if not _matches(document, query)]
            self._write_documents(documents)

    def _read_documents(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"), object_hook=_decode_document_value)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        return [document for document in payload if isinstance(document, dict)]

    def _write_documents(self, documents: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text(json.dumps(documents, indent=2, default=_encode_document_value) + "\n", encoding="utf-8")
        temporary_path.replace(self.path)


def _matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    return all(document.get(key) == value for key, value in query.items())


def _encode_document_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return {DATETIME_MARKER: value.isoformat()}
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _decode_document_value(value: dict[str, Any]) -> Any:
    timestamp = value.get(DATETIME_MARKER)
    if isinstance(timestamp, str) and len(value) == 1:
        return datetime.fromisoformat(timestamp)
    return value
