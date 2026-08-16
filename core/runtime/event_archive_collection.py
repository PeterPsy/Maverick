"""Physical append-position paging for runtime event collections."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.runtime.archive_pagination import page_archive_documents, page_chunked_archive_documents
from core.runtime.session_collection import _locked_collection_path
from core.shared.json_file_collection import _matches


class RuntimeEventArchivePaginationMixin:
    """Add stable archive-position reads to a session event collection."""

    def find_event_archive_page(
        self,
        query: dict[str, Any],
        *,
        before_position: int | None,
        snapshot_position: int | None,
        snapshot_event_id: str | None,
        limit: int,
    ) -> dict[str, Any]:
        for history_root in self._candidate_history_roots(query):
            paths = self._history_chunk_paths(history_root)
            if paths:
                return self._find_chunked_event_archive_page(
                    paths,
                    query,
                    before_position=before_position,
                    snapshot_position=snapshot_position,
                    snapshot_event_id=snapshot_event_id,
                    limit=limit,
                )
        for path in self._candidate_legacy_history_paths(query):
            if path.is_file():
                with self._lock:
                    with _locked_collection_path(path):
                        documents = [document for document in self._read_documents(path) if _matches(document, query)]
                return _page_documents(
                    documents,
                    before_position=before_position,
                    snapshot_position=snapshot_position,
                    snapshot_event_id=snapshot_event_id,
                    limit=limit,
                )
        return _page_documents(
            self.find(query),
            before_position=before_position,
            snapshot_position=snapshot_position,
            snapshot_event_id=snapshot_event_id,
            limit=limit,
        )

    def _find_chunked_event_archive_page(
        self,
        paths: list[Path],
        query: dict[str, Any],
        *,
        before_position: int | None,
        snapshot_position: int | None,
        snapshot_event_id: str | None,
        limit: int,
    ) -> dict[str, Any]:
        with self._lock:
            with _locked_collection_path(paths[0].parent):
                return page_chunked_archive_documents(
                    paths,
                    identity_field="event_id",
                    before_position=before_position,
                    snapshot_position=snapshot_position,
                    snapshot_record_id=snapshot_event_id,
                    limit=limit,
                    query=query,
                    read_documents=self._read_documents,
                    count_documents=self._count_documents,
                    matches=_matches,
                )


def _page_documents(
    documents: list[dict[str, Any]],
    *,
    before_position: int | None,
    snapshot_position: int | None,
    snapshot_event_id: str | None,
    limit: int,
) -> dict[str, Any]:
    return page_archive_documents(
        documents,
        identity_field="event_id",
        before_position=before_position,
        snapshot_position=snapshot_position,
        snapshot_record_id=snapshot_event_id,
        limit=limit,
    )
