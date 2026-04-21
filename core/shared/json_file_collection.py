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

    def __init__(self, path: Path, *, append_only_upserts: bool = False) -> None:
        self.path = path
        self.append_only_upserts = append_only_upserts
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
            if self.append_only_upserts and upsert and query and _query_is_contained(query, payload):
                self._append_document({**deepcopy(query), **payload})
                return
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
        except json.JSONDecodeError as exc:
            raise ValueError(f"Unable to read malformed JSON collection: {self.path}") from exc
        if not isinstance(payload, list):
            return []
        return [document for document in payload if isinstance(document, dict)]

    def _write_documents(self, documents: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text(json.dumps(documents, indent=2, default=_encode_document_value) + "\n", encoding="utf-8")
        temporary_path.replace(self.path)

    def _append_document(self, document: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = _indented_array_item(document)
        if not self.path.exists() or self.path.stat().st_size == 0:
            self.path.write_text(f"[\n{encoded}\n]\n", encoding="utf-8")
            return
        try:
            with self.path.open("r+b") as handle:
                handle.seek(0, 2)
                file_size = handle.tell()
                close_position = _find_json_array_close(handle, file_size)
                if close_position is None:
                    raise ValueError("JSON array close marker not found.")
                has_existing_items = _json_array_has_items(handle, close_position)
                handle.seek(close_position)
                separator = ",\n" if has_existing_items else "\n"
                handle.write((separator + encoded + "\n]\n").encode("utf-8"))
                handle.truncate()
        except (OSError, ValueError):
            documents = self._read_documents()
            documents.append(document)
            self._write_documents(documents)


def _matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    return all(document.get(key) == value for key, value in query.items())


def _query_is_contained(query: dict[str, Any], payload: dict[str, Any]) -> bool:
    return all(payload.get(key) == value for key, value in query.items())


def _indented_array_item(document: dict[str, Any]) -> str:
    encoded = json.dumps(document, indent=2, default=_encode_document_value)
    return "\n".join(f"  {line}" for line in encoded.splitlines())


def _find_json_array_close(handle, file_size: int) -> int | None:
    position = file_size
    while position > 0:
        position -= 1
        handle.seek(position)
        byte = handle.read(1)
        if byte in {b" ", b"\n", b"\r", b"\t"}:
            continue
        return position if byte == b"]" else None
    return None


def _json_array_has_items(handle, close_position: int) -> bool:
    position = close_position
    while position > 0:
        position -= 1
        handle.seek(position)
        byte = handle.read(1)
        if byte in {b" ", b"\n", b"\r", b"\t"}:
            continue
        return byte != b"["
    return False


def _encode_document_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return {DATETIME_MARKER: value.isoformat()}
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _decode_document_value(value: dict[str, Any]) -> Any:
    timestamp = value.get(DATETIME_MARKER)
    if isinstance(timestamp, str) and len(value) == 1:
        return datetime.fromisoformat(timestamp)
    return value
