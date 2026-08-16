"""Session-partitioned JSON collections for runtime-owned records."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, UTC
import fcntl
import json
import os
from pathlib import Path
import tempfile
from threading import local, RLock
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

MAX_RECOVERY_EVENT_SCAN_BYTES = 2 * 1024 * 1024
_LIFECYCLE_HANDOFF_LOCAL = local()


class RuntimeSessionJsonCollection:
    """Persist runtime records under each session root instead of one global file."""

    def __init__(self, *, start_path: Path, filename: str, append_only_upserts: bool = False) -> None:
        self.start_path = start_path
        self.filename = filename
        self.append_only_upserts = append_only_upserts
        self._lock = RLock()
        self._partition_counts: dict[Path, int] = {}

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            for path in self._candidate_paths(query):
                if not path.is_file():
                    continue
                with _locked_collection_path(path):
                    for document in self._read_documents(path):
                        if _matches(document, query):
                            return deepcopy(document)
        return None

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        with self._lock:
            matches: list[dict[str, Any]] = []
            for path in self._candidate_paths(query):
                if not path.is_file():
                    continue
                with _locked_collection_path(path):
                    matches.extend(deepcopy(document) for document in self._read_documents(path) if _matches(document, query))
            return matches

    def find_recent(self, query: dict[str, Any], *, limit: int, max_scan_bytes: int = MAX_RECOVERY_EVENT_SCAN_BYTES) -> list[dict[str, Any]]:
        """Return recent matches for recovery without mutating valid large partitions."""
        if limit < 1:
            return []
        with self._lock:
            matches: list[dict[str, Any]] = []
            for path in self._candidate_paths(query):
                if not path.is_file():
                    continue
                with _locked_collection_path(path):
                    if path.stat().st_size > max_scan_bytes:
                        # Large valid history files are still product data. Recovery may skip
                        # scanning them to keep startup bounded, but it must not remove them
                        # from the normal runtime history read path.
                        continue
                    try:
                        documents = self._read_documents(path)
                    except ValueError:
                        self._quarantine_partition(path, reason="malformed")
                        continue
                    matches.extend(deepcopy(document) for document in documents if _matches(document, query))
            matches.sort(key=lambda item: str(item.get("created_at") or ""))
            return matches[-limit:]

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> bool:
        payload = deepcopy(update.get("$set", {}))
        workspace_id = str(payload.get("workspace_id") or query.get("workspace_id") or "").strip()
        session_id = str(payload.get("session_id") or query.get("session_id") or "").strip()
        if not workspace_id or not session_id:
            raise ValueError(f"Runtime {self.filename} updates require both workspace_id and session_id.")
        path = self._record_path(workspace_id=workspace_id, session_id=session_id)
        with self._lock:
            with _locked_collection_path(path):
                if self.append_only_upserts and upsert and query and _query_is_contained(query, payload):
                    count = self._partition_counts.get(path)
                    if count is None:
                        count = self._count_documents(path)
                    self._append_document(path, {**deepcopy(query), **payload})
                    self._partition_counts[path] = count + 1
                    return True
                documents = self._read_documents(path)
                for index, document in enumerate(documents):
                    if _matches(document, query):
                        documents[index] = {**document, **payload}
                        self._write_documents(path, documents)
                        self._partition_counts[path] = len(documents)
                        return True
                if upsert:
                    documents.append({**deepcopy(query), **payload})
                    self._write_documents(path, documents)
                    self._partition_counts[path] = len(documents)
                    return True
        return False

    def compare_and_set(self, query: dict[str, Any], update: dict[str, Any]) -> bool:
        """Apply an exact conditional update inside one session partition."""
        return self.update_one(query, update, upsert=False)

    def insert_one_if_absent(self, query: dict[str, Any], document: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Insert one session-partitioned record atomically when the query has no match."""
        payload = {**deepcopy(query), **deepcopy(document)}
        workspace_id = str(payload.get("workspace_id") or "").strip()
        session_id = str(payload.get("session_id") or "").strip()
        if not workspace_id or not session_id:
            raise ValueError(f"Runtime {self.filename} inserts require both workspace_id and session_id.")
        path = self._record_path(workspace_id=workspace_id, session_id=session_id)
        with self._lock:
            with _locked_collection_path(path):
                documents = self._read_documents(path)
                for existing in documents:
                    if _matches(existing, query):
                        return deepcopy(existing), False
                documents.append(payload)
                self._write_documents(path, documents)
                self._partition_counts[path] = len(documents)
                return deepcopy(payload), True

    def append_bounded_upsert(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        *,
        max_documents: int,
        compaction_slack_documents: int = 0,
    ) -> None:
        """Append an upserted record while keeping a session partition bounded."""
        if max_documents < 1:
            raise ValueError("max_documents must be positive.")
        if compaction_slack_documents < 0:
            raise ValueError("compaction_slack_documents cannot be negative.")
        payload = deepcopy(update.get("$set", {}))
        workspace_id = str(payload.get("workspace_id") or query.get("workspace_id") or "").strip()
        session_id = str(payload.get("session_id") or query.get("session_id") or "").strip()
        if not workspace_id or not session_id:
            raise ValueError(f"Runtime {self.filename} updates require both workspace_id and session_id.")
        path = self._record_path(workspace_id=workspace_id, session_id=session_id)
        document = {**deepcopy(query), **payload}
        with self._lock:
            with _locked_collection_path(path):
                if self.append_only_upserts and query and _query_is_contained(query, payload):
                    count = self._partition_counts.get(path)
                    if count is None:
                        count = self._count_documents(path)
                    if count < max_documents + compaction_slack_documents:
                        self._append_document(path, document)
                        self._partition_counts[path] = count + 1
                        return
                    documents = self._read_documents(path)
                    documents.append(document)
                    documents.sort(key=lambda item: str(item.get("created_at") or ""))
                    kept_documents = documents[-max_documents:]
                    self._write_documents(path, kept_documents)
                    self._partition_counts[path] = len(kept_documents)
                    return
                self.update_one(query, update, upsert=True)

    def delete_one(self, query: dict[str, Any]) -> None:
        with self._lock:
            for path in self._candidate_paths(query):
                if not path.is_file():
                    continue
                with _locked_collection_path(path):
                    documents = self._read_documents(path)
                    filtered = [document for document in documents if not _matches(document, query)]
                    if len(filtered) == len(documents):
                        continue
                    if filtered:
                        self._write_documents(path, filtered)
                        self._partition_counts[path] = len(filtered)
                    elif path.exists():
                        path.unlink()
                        self._partition_counts.pop(path, None)
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
                if not path.is_file():
                    continue
                with _locked_collection_path(path):
                    documents = self._read_documents(path)
                    deleted += len(documents)
                    if path.exists():
                        path.unlink()
                    self._partition_counts.pop(path, None)
            return deleted

    def replace_session_partition(
        self,
        *,
        session_id: str,
        workspace_id: str,
        documents: list[dict[str, Any]],
    ) -> None:
        """Replace all records for one session with a single file write."""
        path = self._record_path(workspace_id=workspace_id, session_id=session_id)
        with self._lock:
            with _locked_collection_path(path):
                filtered = [deepcopy(document) for document in documents if _matches(document, {"session_id": session_id})]
                if filtered:
                    self._write_documents(path, filtered)
                    self._partition_counts[path] = len(filtered)
                elif path.exists():
                    path.unlink()
                    self._partition_counts.pop(path, None)

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

    def lifecycle_handoff(self, *, workspace_id: str, session_id: str):
        """Serialize authoritative lifecycle transitions for one runtime session."""
        path = runtime_session_root(
            workspace_id=workspace_id,
            session_id=session_id,
            start_path=self.start_path,
        ) / "lifecycle.json"
        return _reentrant_lifecycle_handoff(path)

    def _read_documents(self, path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"), object_hook=_decode_document_value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Unable to read malformed JSON collection: {path}") from exc
        if not isinstance(payload, list):
            raise ValueError(f"JSON collection `{path}` must contain a JSON array.")
        if not all(isinstance(document, dict) for document in payload):
            raise ValueError(f"JSON collection `{path}` must contain only JSON objects.")
        return payload

    def _count_documents(self, path: Path) -> int:
        return len(self._read_documents(path))

    def _write_documents(self, path: Path, documents: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(json.dumps(documents, indent=2, default=_encode_document_value) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary_path.replace(path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

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

    def _quarantine_partition(self, path: Path, *, reason: str) -> None:
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%d%H%M%S%f")
        quarantine_path = path.with_name(f"{path.name}.quarantined-{reason}-{timestamp}")
        try:
            path.replace(quarantine_path)
            self._partition_counts.pop(path, None)
        except OSError:
            pass


@contextmanager
def _locked_collection_path(path: Path):
    lock_path = path.with_suffix(f"{path.suffix}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@contextmanager
def _reentrant_lifecycle_handoff(path: Path):
    """Make the cross-process lifecycle lock reentrant in its owning thread."""
    key = str(path.resolve(strict=False))
    depths = getattr(_LIFECYCLE_HANDOFF_LOCAL, "depths", None)
    if depths is None:
        depths = {}
        _LIFECYCLE_HANDOFF_LOCAL.depths = depths
    depth = int(depths.get(key, 0))
    depths[key] = depth + 1
    try:
        if depth:
            yield
            return
        with _locked_collection_path(path):
            yield
    finally:
        remaining = int(depths.get(key, 1)) - 1
        if remaining > 0:
            depths[key] = remaining
        else:
            depths.pop(key, None)
