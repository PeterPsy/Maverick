"""Append-position pagination primitives for immutable runtime archives."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def page_archive_documents(
    documents: list[dict[str, Any]],
    *,
    identity_field: str,
    before_position: int | None,
    snapshot_position: int | None,
    snapshot_record_id: str | None,
    limit: int,
) -> dict[str, Any]:
    """Page documents by their stable physical append position."""
    resolved_position = len(documents) - 1 if snapshot_position is None else int(snapshot_position)
    if resolved_position == -1:
        found = not documents or snapshot_position == -1
        return _empty_page(snapshot_found=found, snapshot_position=-1, snapshot_record_id=None)
    if resolved_position < 0 or resolved_position >= len(documents):
        return _empty_page(
            snapshot_found=False,
            snapshot_position=resolved_position,
            snapshot_record_id=snapshot_record_id,
        )
    resolved_record_id = str(documents[resolved_position].get(identity_field) or "").strip()
    if snapshot_position is not None and resolved_record_id != str(snapshot_record_id or "").strip():
        return _empty_page(
            snapshot_found=False,
            snapshot_position=resolved_position,
            snapshot_record_id=snapshot_record_id,
        )
    end = min(resolved_position + 1, int(before_position) if before_position is not None else resolved_position + 1)
    start = max(0, end - max(1, int(limit)))
    return {
        "documents": documents[start:end],
        "has_more_before": start > 0,
        "oldest_position": start if start < end else None,
        "newest_position": end - 1 if start < end else None,
        "snapshot_position": resolved_position,
        "snapshot_record_id": resolved_record_id,
        "snapshot_found": True,
    }


def page_chunked_archive_documents(
    paths: list[Path],
    *,
    identity_field: str,
    before_position: int | None,
    snapshot_position: int | None,
    snapshot_record_id: str | None,
    limit: int,
    query: dict[str, Any],
    read_documents: Callable[[Path], list[dict[str, Any]]],
    count_documents: Callable[[Path], int],
    matches: Callable[[dict[str, Any], dict[str, Any]], bool],
) -> dict[str, Any]:
    """Read only archive chunks intersecting one physical-position page."""
    counts = [count_documents(path) for path in paths]
    total = sum(counts)
    resolved_snapshot = total - 1 if snapshot_position is None else int(snapshot_position)
    if resolved_snapshot == -1:
        return page_archive_documents(
            [],
            identity_field=identity_field,
            before_position=before_position,
            snapshot_position=-1,
            snapshot_record_id=None,
            limit=limit,
        )
    snapshot_document = _document_at(paths, counts, resolved_snapshot, read_documents=read_documents)
    resolved_record_id = str((snapshot_document or {}).get(identity_field) or "").strip()
    if (
        snapshot_document is None
        or not matches(snapshot_document, query)
        or (snapshot_position is not None and resolved_record_id != str(snapshot_record_id or "").strip())
    ):
        return missing_archive_snapshot(resolved_snapshot, snapshot_record_id)
    end = min(
        resolved_snapshot + 1,
        int(before_position) if before_position is not None else resolved_snapshot + 1,
    )
    start = max(0, end - max(1, int(limit)))
    documents = _documents_in_range(paths, counts, start=start, end=end, read_documents=read_documents)
    if not all(matches(document, query) for document in documents):
        return missing_archive_snapshot(resolved_snapshot, snapshot_record_id)
    return {
        "documents": documents,
        "has_more_before": start > 0,
        "oldest_position": start if start < end else None,
        "newest_position": end - 1 if start < end else None,
        "snapshot_position": resolved_snapshot,
        "snapshot_record_id": resolved_record_id,
        "snapshot_found": True,
    }


def missing_archive_snapshot(position: int, record_id: str | None) -> dict[str, Any]:
    return _empty_page(
        snapshot_found=False,
        snapshot_position=position,
        snapshot_record_id=record_id,
    )


def _document_at(
    paths: list[Path],
    counts: list[int],
    position: int,
    *,
    read_documents: Callable[[Path], list[dict[str, Any]]],
) -> dict[str, Any] | None:
    offset = 0
    for path, count in zip(paths, counts, strict=True):
        if position < offset + count:
            documents = read_documents(path)
            local_position = position - offset
            return documents[local_position] if local_position < len(documents) else None
        offset += count
    return None


def _documents_in_range(
    paths: list[Path],
    counts: list[int],
    *,
    start: int,
    end: int,
    read_documents: Callable[[Path], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    offset = 0
    for path, count in zip(paths, counts, strict=True):
        chunk_end = offset + count
        if chunk_end <= start:
            offset = chunk_end
            continue
        if offset >= end:
            break
        documents = read_documents(path)
        selected.extend(documents[max(0, start - offset) : min(count, end - offset)])
        offset = chunk_end
    return selected


def _empty_page(
    *,
    snapshot_found: bool,
    snapshot_position: int,
    snapshot_record_id: str | None,
) -> dict[str, Any]:
    return {
        "documents": [],
        "has_more_before": False,
        "oldest_position": None,
        "newest_position": None,
        "snapshot_position": snapshot_position,
        "snapshot_record_id": snapshot_record_id,
        "snapshot_found": snapshot_found,
    }
