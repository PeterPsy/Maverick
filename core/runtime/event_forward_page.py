"""Forward reads of one session's existing chunked event archive."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.runtime.session_collection import _locked_collection_path

if TYPE_CHECKING:
    from core.runtime.event_collection import RuntimeEventJsonCollection


def forward_event_page(
    collection: RuntimeEventJsonCollection, query: dict[str, Any], *, after_event_id: str, limit: int,
) -> dict[str, Any]:
    empty = {"documents": [], "has_more_before": False, "has_more_after": False, "cursor_found": False}
    if limit < 1:
        return empty
    for root in collection._candidate_history_roots(query):
        if not root.is_dir():
            continue
        with collection._lock, _locked_collection_path(root):
            paths = collection._history_chunk_paths(root)
            for index in range(len(paths) - 1, -1, -1):
                documents = collection._matching_sorted_documents(paths[index], query)
                cursor = next(
                    (offset for offset, item in enumerate(documents) if item.get("event_id") == after_event_id), None,
                )
                if cursor is None:
                    continue
                selected = documents[cursor + 1 : cursor + limit + 2]
                for path in paths[index + 1 :]:
                    if len(selected) > limit:
                        break
                    following = collection._matching_sorted_documents(path, query)
                    selected.extend(following[: limit + 1 - len(selected)])
                return _page(selected, limit)
    # Preserve the existing single-file/tail adapter boundaries for histories
    # which have not been archived into chunks. Never mix distinct partitions.
    for path in collection._candidate_legacy_history_paths(query):
        if path.is_file():
            with collection._lock, _locked_collection_path(path):
                documents = collection._matching_sorted_documents(path, query)
            selected = _after(documents, after_event_id, limit)
            if selected is not None:
                return _page(selected, limit)
    documents = sorted(collection.find(query), key=collection._event_sort_key)
    selected = _after(documents, after_event_id, limit)
    return _page(selected, limit) if selected is not None else empty


def _after(documents: list[dict[str, Any]], cursor: str, limit: int) -> list[dict[str, Any]] | None:
    for index, document in enumerate(documents):
        if document.get("event_id") == cursor:
            return documents[index + 1 : index + limit + 2]
    return None


def _page(documents: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    return {
        "documents": documents[:limit], "has_more_before": True,
        "has_more_after": len(documents) > limit, "cursor_found": True,
    }
