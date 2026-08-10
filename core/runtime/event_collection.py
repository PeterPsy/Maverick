"""Session-partitioned JSON collection for runtime event history."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.runtime.session_collection import RuntimeSessionJsonCollection, _locked_collection_path
from core.shared.json_file_collection import _matches


HISTORY_CHUNK_SIZE = 500
HISTORY_CHUNK_SUFFIX = ".json"
LEGACY_HISTORY_FILENAME = "events-history.json"


class RuntimeEventJsonCollection(RuntimeSessionJsonCollection):
    """Persist runtime events under each session runtime root."""

    def __init__(self, *, start_path: Path) -> None:
        super().__init__(start_path=start_path, filename="events.json", append_only_upserts=True)
        self.history_directory_name = "events-history"
        self.legacy_history_filename = LEGACY_HISTORY_FILENAME

    def append_history_upsert(self, query: dict[str, Any], update: dict[str, Any]) -> None:
        """Append one event to the chunked history archive."""
        payload = dict(update.get("$set", {}))
        workspace_id = str(payload.get("workspace_id") or query.get("workspace_id") or "").strip()
        session_id = str(payload.get("session_id") or query.get("session_id") or "").strip()
        if not workspace_id or not session_id:
            raise ValueError("Runtime event history updates require both workspace_id and session_id.")
        history_root = self._history_root(workspace_id=workspace_id, session_id=session_id)
        document = {**dict(query), **payload}
        with self._lock:
            with _locked_collection_path(history_root):
                path = self._history_chunk_for_append(history_root)
                self._append_document(path, document)
                count = self._partition_counts.get(path)
                self._partition_counts[path] = self._count_documents(path) if count is None else count + 1

    def append_history_upsert_if_absent(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """Append once to full history while holding its cross-process partition lock."""
        payload = dict(update.get("$set", {}))
        workspace_id = str(payload.get("workspace_id") or query.get("workspace_id") or "").strip()
        session_id = str(payload.get("session_id") or query.get("session_id") or "").strip()
        if not workspace_id or not session_id:
            raise ValueError("Runtime event history updates require both workspace_id and session_id.")
        history_root = self._history_root(workspace_id=workspace_id, session_id=session_id)
        document = {**dict(query), **payload}
        with self._lock:
            with _locked_collection_path(history_root):
                for path in self._history_chunk_paths(history_root):
                    for existing in self._read_documents(path):
                        if _matches(existing, query):
                            return existing, False
                for path in self._candidate_legacy_history_paths(query):
                    if not path.is_file():
                        continue
                    for existing in self._read_documents(path):
                        if _matches(existing, query):
                            return existing, False
                path = self._history_chunk_for_append(history_root)
                self._append_document(path, document)
                count = self._partition_counts.get(path)
                self._partition_counts[path] = self._count_documents(path) if count is None else count + 1
                return document, True

    def find_history_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        """Find one event in the complete history archive."""
        for history_root in self._candidate_history_roots(query):
            if not history_root.is_dir():
                continue
            with self._lock:
                with _locked_collection_path(history_root):
                    for path in reversed(self._history_chunk_paths(history_root)):
                        for document in reversed(self._read_documents(path)):
                            if _matches(document, query):
                                return document
        for path in self._candidate_legacy_history_paths(query):
            if not path.is_file():
                continue
            with self._lock:
                with _locked_collection_path(path):
                    for document in reversed(self._read_documents(path)):
                        if _matches(document, query):
                            return document
        return None

    def find_event_page(self, query: dict[str, Any], *, before_event_id: str | None, limit: int) -> dict[str, Any]:
        """Return a bounded page from history without scanning the whole archive."""
        if limit < 1:
            return {"documents": [], "has_more_before": False}
        for history_root in self._candidate_history_roots(query):
            page = self._find_chunked_event_page(history_root, query, before_event_id=before_event_id, limit=limit)
            if page["documents"] or page.get("cursor_found"):
                return page
        for legacy_path in self._candidate_legacy_history_paths(query):
            page = self._find_legacy_event_page(legacy_path, query, before_event_id=before_event_id, limit=limit)
            if page["documents"] or page.get("cursor_found"):
                return page
        return self._find_tail_event_page(query, before_event_id=before_event_id, limit=limit)

    def has_event_before(self, query: dict[str, Any], *, before_event_id: str | None) -> bool:
        """Return whether persisted history has an event older than the cursor."""
        if not before_event_id:
            return False
        for history_root in self._candidate_history_roots(query):
            page = self._find_chunked_event_page(history_root, query, before_event_id=before_event_id, limit=1)
            if page["documents"]:
                return True
            if page.get("cursor_found"):
                return False
        # Legacy single-file archives are intentionally not read on initial load.
        # A true value may over-advertise history, but keeps opening bounded.
        return any(path.is_file() and path.stat().st_size > 4 for path in self._candidate_legacy_history_paths(query))

    def delete_session_partition(self, *, session_id: str, workspace_id: str | None = None) -> int:
        tail_deleted = super().delete_session_partition(session_id=session_id, workspace_id=workspace_id)
        history_deleted = 0
        with self._lock:
            roots = (
                [self._history_root(workspace_id=workspace_id, session_id=session_id)]
                if workspace_id
                else self._candidate_history_roots({"session_id": session_id})
            )
            for root in roots:
                if not root.is_dir():
                    continue
                with _locked_collection_path(root):
                    for path in self._history_chunk_paths(root):
                        history_deleted += len(self._read_documents(path))
                        path.unlink(missing_ok=True)
                        self._partition_counts.pop(path, None)
                    root.rmdir()
            legacy_paths = (
                [self._legacy_history_path(workspace_id=workspace_id, session_id=session_id)]
                if workspace_id
                else self._candidate_legacy_history_paths({"session_id": session_id})
            )
            for path in legacy_paths:
                if not path.is_file():
                    continue
                with _locked_collection_path(path):
                    history_deleted += len(self._read_documents(path))
                    path.unlink(missing_ok=True)
                    self._partition_counts.pop(path, None)
        return tail_deleted + history_deleted

    def _find_chunked_event_page(
        self,
        history_root: Path,
        query: dict[str, Any],
        *,
        before_event_id: str | None,
        limit: int,
    ) -> dict[str, Any]:
        if not history_root.is_dir():
            return {"documents": [], "has_more_before": False, "cursor_found": False}
        selected_reversed: list[dict[str, Any]] = []
        cursor_found = before_event_id is None
        with self._lock:
            with _locked_collection_path(history_root):
                for path in reversed(self._history_chunk_paths(history_root)):
                    documents = self._matching_sorted_documents(path, query)
                    if not cursor_found:
                        for index, document in enumerate(documents):
                            if document.get("event_id") == before_event_id:
                                documents = documents[:index]
                                cursor_found = True
                                break
                        if not cursor_found:
                            continue
                    for document in reversed(documents):
                        if len(selected_reversed) >= limit:
                            return {
                                "documents": list(reversed(selected_reversed)),
                                "has_more_before": True,
                                "cursor_found": cursor_found,
                            }
                        selected_reversed.append(document)
        return {
            "documents": list(reversed(selected_reversed)),
            "has_more_before": False,
            "cursor_found": cursor_found,
        }

    def _find_legacy_event_page(
        self,
        path: Path,
        query: dict[str, Any],
        *,
        before_event_id: str | None,
        limit: int,
    ) -> dict[str, Any]:
        if not path.is_file():
            return {"documents": [], "has_more_before": False, "cursor_found": False}
        with self._lock:
            with _locked_collection_path(path):
                documents = self._matching_sorted_documents(path, query)
        cursor_found = before_event_id is None
        if before_event_id:
            for index, document in enumerate(documents):
                if document.get("event_id") == before_event_id:
                    documents = documents[:index]
                    cursor_found = True
                    break
            if not cursor_found:
                return {"documents": [], "has_more_before": False, "cursor_found": False}
        has_more_before = len(documents) > limit
        return {"documents": documents[-limit:], "has_more_before": has_more_before, "cursor_found": cursor_found}

    def _find_tail_event_page(self, query: dict[str, Any], *, before_event_id: str | None, limit: int) -> dict[str, Any]:
        documents = self.find(query)
        documents.sort(key=self._event_sort_key)
        cursor_found = before_event_id is None
        if before_event_id:
            for index, document in enumerate(documents):
                if document.get("event_id") == before_event_id:
                    documents = documents[:index]
                    cursor_found = True
                    break
            if not cursor_found:
                return {"documents": [], "has_more_before": False, "cursor_found": False}
        has_more_before = len(documents) > limit
        return {"documents": documents[-limit:], "has_more_before": has_more_before, "cursor_found": cursor_found}

    def _history_chunk_for_append(self, history_root: Path) -> Path:
        paths = self._history_chunk_paths(history_root)
        if not paths:
            return history_root / f"{0:06d}{HISTORY_CHUNK_SUFFIX}"
        latest_path = paths[-1]
        count = self._partition_counts.get(latest_path)
        if count is None:
            count = self._count_documents(latest_path)
        if count >= HISTORY_CHUNK_SIZE:
            return history_root / f"{self._history_chunk_index(latest_path) + 1:06d}{HISTORY_CHUNK_SUFFIX}"
        return latest_path

    def _history_chunk_paths(self, history_root: Path) -> list[Path]:
        if not history_root.is_dir():
            return []
        return sorted(path for path in history_root.glob(f"*{HISTORY_CHUNK_SUFFIX}") if path.stem.isdigit())

    def _matching_sorted_documents(self, path: Path, query: dict[str, Any]) -> list[dict[str, Any]]:
        documents = [document for document in self._read_documents(path) if _matches(document, query)]
        documents.sort(key=self._event_sort_key)
        return documents

    def _event_sort_key(self, item: dict[str, Any]) -> tuple[str, str]:
        return (str(item.get("created_at") or ""), str(item.get("event_id") or ""))

    def _candidate_history_roots(self, query: dict[str, Any]) -> list[Path]:
        return [path.with_name(self.history_directory_name) for path in self._candidate_paths(query)]

    def _candidate_legacy_history_paths(self, query: dict[str, Any]) -> list[Path]:
        return [path.with_name(self.legacy_history_filename) for path in self._candidate_paths(query)]

    def _history_chunk_index(self, path: Path) -> int:
        try:
            return int(path.stem)
        except ValueError:
            return 0

    def _history_root(self, *, workspace_id: str, session_id: str) -> Path:
        return self._record_path(workspace_id=workspace_id, session_id=session_id).with_name(self.history_directory_name)

    def _legacy_history_path(self, *, workspace_id: str, session_id: str) -> Path:
        return self._record_path(workspace_id=workspace_id, session_id=session_id).with_name(self.legacy_history_filename)
