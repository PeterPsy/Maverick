"""JSON-file backed collection for local hosted bootstrap persistence."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import stat
from threading import RLock
import tempfile
from typing import Any


DATETIME_MARKER = "__maverick_datetime__"
COLLECTION_FILE_MODE = 0o660
COLLECTION_DIRECTORY_MODE = 0o2770


class JsonFileCollection:
    """Provide the document collection protocol backed by one JSON file."""

    def __init__(self, path: Path, *, append_only_upserts: bool = False) -> None:
        self.path = path
        self.append_only_upserts = append_only_upserts
        self._lock = RLock()

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            with self._process_lock(exclusive=False):
                for document in self._read_documents():
                    if _matches(document, query):
                        return deepcopy(document)
        return None

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        with self._lock:
            with self._process_lock(exclusive=False):
                return [deepcopy(document) for document in self._read_documents() if _matches(document, query)]

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> None:
        payload = deepcopy(update.get("$set", {}))
        with self._lock:
            with self._process_lock(exclusive=True):
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

    def insert_one_if_absent(self, query: dict[str, Any], document: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Insert one document only when no existing document matches the query."""
        payload = {**deepcopy(query), **deepcopy(document)}
        with self._lock:
            with self._process_lock(exclusive=True):
                documents = self._read_documents()
                for existing in documents:
                    if _matches(existing, query):
                        return deepcopy(existing), False
                documents.append(payload)
                self._write_documents(documents)
                return deepcopy(payload), True

    def delete_one(self, query: dict[str, Any]) -> None:
        with self._lock:
            with self._process_lock(exclusive=True):
                documents = [document for document in self._read_documents() if not _matches(document, query)]
                self._write_documents(documents)

    def replace_all(self, documents: list[dict[str, Any]]) -> None:
        """Replace the full collection through the same lock and atomic write path."""
        if not all(isinstance(document, dict) for document in documents):
            raise ValueError("JSON collections can only store object documents.")
        with self._lock:
            with self._process_lock(exclusive=True):
                self._write_documents(deepcopy(documents))

    def _process_lock(self, *, exclusive: bool):
        _ensure_collection_directory(self.path.parent)
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        return _FileLock(lock_path, exclusive=exclusive)

    def _read_documents(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"), object_hook=_decode_document_value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Unable to read malformed JSON collection: {self.path}") from exc
        if not isinstance(payload, list):
            raise ValueError(f"JSON collection `{self.path}` must contain a JSON array.")
        if not all(isinstance(document, dict) for document in payload):
            raise ValueError(f"JSON collection `{self.path}` must contain only JSON objects.")
        return payload

    def _write_documents(self, documents: list[dict[str, Any]]) -> None:
        _ensure_collection_directory(self.path.parent)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(json.dumps(documents, indent=2, default=_encode_document_value) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            _apply_collection_file_mode(temporary_path)
            temporary_path.replace(self.path)
            _apply_collection_file_mode(self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def _append_document(self, document: dict[str, Any]) -> None:
        _ensure_collection_directory(self.path.parent)
        encoded = _indented_array_item(document)
        if not self.path.exists() or self.path.stat().st_size == 0:
            self.path.write_text(f"[\n{encoded}\n]\n", encoding="utf-8")
            _apply_collection_file_mode(self.path)
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
            _apply_collection_file_mode(self.path)
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


def _ensure_collection_directory(path: Path) -> None:
    missing_directories = _missing_directories(path)
    path.mkdir(parents=True, exist_ok=True)
    for directory in missing_directories:
        _apply_collection_directory_mode(directory)


def _missing_directories(path: Path) -> list[Path]:
    missing: list[Path] = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    return missing


def _apply_collection_directory_mode(path: Path) -> None:
    try:
        current_mode = stat.S_IMODE(path.stat().st_mode)
        path.chmod(current_mode | COLLECTION_DIRECTORY_MODE)
    except OSError:
        return


def _apply_collection_file_mode(path: Path) -> None:
    try:
        path.chmod(COLLECTION_FILE_MODE)
    except OSError:
        return


class _FileLock:
    def __init__(self, path: Path, *, exclusive: bool) -> None:
        self.path = path
        self.exclusive = exclusive
        self._handle = None

    def __enter__(self):
        _ensure_collection_directory(self.path.parent)
        self._handle = self.path.open("a+b")
        _apply_collection_file_mode(self.path)
        operation = fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH
        fcntl.flock(self._handle.fileno(), operation)
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._handle is None:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None
