"""Session-partitioned JSON collections for runtime-owned records."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from threading import RLock
from typing import Any

from core.runtime.paths import runtime_session_root
from core.shared.json_file_collection import (
    _decode_document_value,
    _encode_document_value,
    _find_json_array_close,
    _indented_array_item,
    _json_array_has_items,
    _matches,
    _query_is_contained,
)


class RuntimeSessionJsonCollection:
    """Persist runtime records under each session root instead of one global file."""

    def __init__(self, *, start_path: Path, filename: str, append_only_upserts: bool = False) -> None:
        self.start_path = start_path
        self.filename = filename
        self.append_only_upserts = append_only_upserts
        self._lock = RLock()

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            for path in self._candidate_paths(query):
                for document in self._read_documents(path):
                    if _matches(document, query):
                        return deepcopy(document)
        return None

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        with self._lock:
            matches: list[dict[str, Any]] = []
            for path in self._candidate_paths(query):
                matches.extend(deepcopy(document) for document in self._read_documents(path) if _matches(document, query))
            return matches

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> None:
        payload = deepcopy(update.get("$set", {}))
        workspace_id = str(payload.get("workspace_id") or query.get("workspace_id") or "").strip()
        session_id = str(payload.get("session_id") or query.get("session_id") or "").strip()
        if not workspace_id or not session_id:
            raise ValueError(f"Runtime {self.filename} updates require both workspace_id and session_id.")
        path = self._record_path(workspace_id=workspace_id, session_id=session_id)
        with self._lock:
            if self.append_only_upserts and upsert and query and _query_is_contained(query, payload):
                self._append_document(path, {**deepcopy(query), **payload})
                return
            documents = self._read_documents(path)
            for index, document in enumerate(documents):
                if _matches(document, query):
                    documents[index] = {**document, **payload}
                    self._write_documents(path, documents)
                    return
            if upsert:
                documents.append({**deepcopy(query), **payload})
                self._write_documents(path, documents)

    def delete_one(self, query: dict[str, Any]) -> None:
        with self._lock:
            for path in self._candidate_paths(query):
                documents = self._read_documents(path)
                filtered = [document for document in documents if not _matches(document, query)]
                if len(filtered) == len(documents):
                    continue
                if filtered:
                    self._write_documents(path, filtered)
                elif path.exists():
                    path.unlink()
                return

    def delete_session_partition(self, *, session_id: str, workspace_id: str | None = None) -> int:
        with self._lock:
            paths = (
                [self._record_path(workspace_id=workspace_id, session_id=session_id)]
                if workspace_id
                else self._candidate_paths({"session_id": session_id})
            )
            deleted = 0
            for path in paths:
                documents = self._read_documents(path)
                deleted += len(documents)
                if path.exists():
                    path.unlink()
            return deleted

    def _candidate_paths(self, query: dict[str, Any]) -> list[Path]:
        workspace_id = str(query.get("workspace_id") or "").strip()
        session_id = str(query.get("session_id") or "").strip()
        if workspace_id and session_id:
            return [self._record_path(workspace_id=workspace_id, session_id=session_id)]
        if session_id:
            return sorted((self.start_path / "workspaces").glob(f"*/runtime/sessions/{session_id}/{self.filename}"))
        return sorted((self.start_path / "workspaces").glob(f"*/runtime/sessions/*/{self.filename}"))

    def _record_path(self, *, workspace_id: str, session_id: str) -> Path:
        return runtime_session_root(workspace_id=workspace_id, session_id=session_id, start_path=self.start_path) / self.filename

    def _read_documents(self, path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"), object_hook=_decode_document_value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Unable to read malformed JSON collection: {path}") from exc
        if not isinstance(payload, list):
            return []
        return [document for document in payload if isinstance(document, dict)]

    def _write_documents(self, path: Path, documents: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(f"{path.suffix}.tmp")
        temporary_path.write_text(json.dumps(documents, indent=2, default=_encode_document_value) + "\n", encoding="utf-8")
        temporary_path.replace(path)

    def _append_document(self, path: Path, document: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = _indented_array_item(document)
        if not path.exists() or path.stat().st_size == 0:
            path.write_text(f"[\n{encoded}\n]\n", encoding="utf-8")
            return
        try:
            with path.open("r+b") as handle:
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
            documents = self._read_documents(path)
            documents.append(document)
            self._write_documents(path, documents)
