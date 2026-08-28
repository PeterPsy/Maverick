"""Stable text search over the descriptor-confined workspace filesystem."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os

from core.egress.classification import CanonicalSourceClassification, join_classifications
from core.runtime.confined_filesystem import (
    _CURSOR_DOMAIN,
    _snapshot_digest,
    FilesystemResourceObservation,
    ConfinedFilesystemResult,
    ConfinedWorkspaceFilesystem,
)
from core.runtime.tool_errors import RuntimeToolError


MAX_SEARCH_DEPTH = 8
MAX_SEARCH_RESULTS = 500
MAX_SEARCH_FILE_BYTES = 1_048_576
MAX_SEARCH_TOTAL_BYTES = 16_777_216
MAX_SEARCH_LINE_CHARS = 1_000


def search_confined_text(
    filesystem: ConfinedWorkspaceFilesystem,
    relative_path: str,
    *,
    query: str,
    max_depth: int,
    page_size: int,
    cursor: str | None,
    case_sensitive: bool,
) -> ConfinedFilesystemResult:
    """Return a stable page of literal UTF-8 matches without following links."""
    if (
        not isinstance(query, str)
        or not query
        or len(query.encode("utf-8")) > 4096
        or not isinstance(max_depth, int)
        or isinstance(max_depth, bool)
        or not 1 <= max_depth <= MAX_SEARCH_DEPTH
        or not isinstance(page_size, int)
        or isinstance(page_size, bool)
        or not 1 <= page_size <= MAX_SEARCH_RESULTS
        or not isinstance(case_sensitive, bool)
    ):
        raise RuntimeToolError("tool_arguments_invalid")
    cursor_data = _decode_search_cursor(filesystem, cursor) if cursor else None
    if cursor_data is not None:
        relative_path = str(cursor_data["path"])
        query = str(cursor_data["query"])
        max_depth = int(cursor_data["max_depth"])
        page_size = int(cursor_data["page_size"])
        case_sensitive = bool(cursor_data["case_sensitive"])
    components = filesystem._components(relative_path, allow_root=True)
    with filesystem._open_chain(components) as requested:
        requested_before = os.fstat(requested.leaf_fd)
        root_observation = filesystem._observation(
            "filesystem_directory",
            filesystem._relative(components),
            requested_before,
        )
        entries, anchors, entry_anchors = filesystem._scan_tree(
            requested.leaf_fd,
            base_components=components,
            max_depth=max_depth,
        )
        try:
            matches, classifications, skipped, scanned_bytes = _collect_matches(
                filesystem,
                entries,
                query=query,
                case_sensitive=case_sensitive,
            )
            filesystem._hook("search_scanned", relative_path)
            filesystem._assert_same_version(
                requested_before,
                os.fstat(requested.leaf_fd),
                "filesystem_snapshot_changed",
            )
            for anchor in anchors:
                filesystem._assert_anchor(anchor, version=True)
            for entry_anchor in entry_anchors:
                filesystem._assert_entry_snapshot(entry_anchor)
            filesystem._assert_chain(requested)
            snapshot_id = _search_snapshot_digest(
                root_observation,
                entries,
                matches,
                query=query,
                case_sensitive=case_sensitive,
                max_depth=max_depth,
            )
            offset = 0
            if cursor_data is not None:
                if (
                    cursor_data["snapshot_id"] != snapshot_id
                    or cursor_data["resource_identity"]
                    != root_observation.resource_identity
                ):
                    raise RuntimeToolError("filesystem_snapshot_changed")
                offset = int(cursor_data["offset"])
            page = matches[offset : offset + page_size]
            next_offset = offset + len(page)
            next_cursor = None
            if next_offset < len(matches):
                next_cursor = filesystem._encode_cursor(
                    {
                        "v": 1,
                        "kind": "search",
                        "path": filesystem._relative(components),
                        "query": query,
                        "case_sensitive": case_sensitive,
                        "max_depth": max_depth,
                        "page_size": page_size,
                        "snapshot_id": snapshot_id,
                        "resource_identity": root_observation.resource_identity,
                        "offset": next_offset,
                    }
                )
            observation = FilesystemResourceObservation(
                workspace_id=filesystem.workspace_id,
                resource_kind="filesystem_search",
                resource_ref=filesystem._relative(components),
                resource_identity=(
                    f"filesystem-search:{root_observation.resource_identity}"
                ),
                resource_revision=snapshot_id,
                resource_digest=snapshot_id,
            )
            return ConfinedFilesystemResult(
                {
                    "path": observation.resource_ref,
                    "query": query,
                    "case_sensitive": case_sensitive,
                    "matches": page,
                    "result_count": len(page),
                    "total_result_count": len(matches),
                    "truncated": next_cursor is not None,
                    "next_cursor": next_cursor,
                    "snapshot_id": snapshot_id,
                    "resource_identity": observation.resource_identity,
                    "resource_revision": observation.resource_revision,
                    "resource_digest": observation.resource_digest,
                    "skipped": skipped,
                    "scanned_bytes": scanned_bytes,
                },
                _aggregate_classification(
                    filesystem,
                    observation,
                    classifications,
                ),
            )
        finally:
            for anchor in reversed(anchors):
                try:
                    os.close(anchor.fd)
                except OSError:
                    pass


def _collect_matches(
    filesystem: ConfinedWorkspaceFilesystem,
    entries: list[dict[str, object]],
    *,
    query: str,
    case_sensitive: bool,
) -> tuple[
    list[dict[str, object]],
    list[CanonicalSourceClassification],
    list[dict[str, object]],
    int,
]:
    matches: list[dict[str, object]] = []
    classifications: list[CanonicalSourceClassification] = []
    skipped: list[dict[str, object]] = []
    scanned_bytes = 0
    needle = query if case_sensitive else query.casefold()
    for entry in entries:
        if entry["type"] != "file":
            continue
        path = str(entry["path"])
        size = int(entry.get("size_bytes") or 0)
        entry_revision = str(entry["resource_revision"])
        classifications.append(
            filesystem._classification(
                FilesystemResourceObservation(
                    workspace_id=filesystem.workspace_id,
                    resource_kind="filesystem_file",
                    resource_ref=path,
                    resource_identity=str(entry["resource_identity"]),
                    resource_revision=entry_revision,
                    resource_digest=entry_revision,
                ),
                "tool_result",
            )
        )
        if size > MAX_SEARCH_FILE_BYTES:
            skipped.append({"path": path, "reason": "file_too_large"})
            continue
        if scanned_bytes + size > MAX_SEARCH_TOTAL_BYTES:
            skipped.append({"path": path, "reason": "search_byte_budget_exceeded"})
            continue
        result = filesystem.read_text(
            path,
            offset=0,
            max_bytes=max(1, MAX_SEARCH_FILE_BYTES),
            expected_resource_identity=str(entry["resource_identity"]),
            expected_resource_revision=str(entry["resource_revision"]),
        )
        if result.payload["next_offset"] is not None:
            skipped.append({"path": path, "reason": "file_too_large"})
            continue
        scanned_bytes += size
        for line_number, line in enumerate(
            str(result.payload["content"]).splitlines(),
            start=1,
        ):
            haystack = line if case_sensitive else line.casefold()
            start = 0
            while True:
                column = haystack.find(needle, start)
                if column < 0:
                    break
                matches.append(
                    {
                        "path": path,
                        "line": line_number,
                        "column": column + 1,
                        "text": line[:MAX_SEARCH_LINE_CHARS],
                    }
                )
                if len(matches) > 10_000:
                    raise RuntimeToolError("filesystem_search_too_large")
                start = column + max(1, len(needle))
    matches.sort(key=lambda item: (str(item["path"]), int(item["line"]), int(item["column"])))
    return matches, classifications, skipped, scanned_bytes


def _aggregate_classification(
    filesystem: ConfinedWorkspaceFilesystem,
    observation: FilesystemResourceObservation,
    classifications: list[CanonicalSourceClassification],
) -> CanonicalSourceClassification:
    if not classifications:
        return filesystem._classification(observation, "tool_result")
    joined = join_classifications(classifications)
    revisions = tuple(
        item.classification_revision for item in joined.sources
    )
    return CanonicalSourceClassification(
        data_class=joined.effective_data_class,
        provenance="tool_result",
        trust_level=joined.effective_trust_level,
        source_ref=observation.resource_ref,
        source_revision=observation.resource_revision,
        source_digest=observation.resource_digest,
        resource_identity=observation.resource_identity,
        classification_revision=(
            max(revisions) if revisions and all(item is not None for item in revisions) else None
        ),
    )


def _search_snapshot_digest(
    observation: FilesystemResourceObservation,
    entries: list[dict[str, object]],
    matches: list[dict[str, object]],
    *,
    query: str,
    case_sensitive: bool,
    max_depth: int,
) -> str:
    listing_digest = _snapshot_digest(observation, entries, max_depth)
    return hashlib.sha256(
        json.dumps(
            {
                "listing_digest": listing_digest,
                "query": query,
                "case_sensitive": case_sensitive,
                "matches": matches,
            },
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _decode_search_cursor(
    filesystem: ConfinedWorkspaceFilesystem,
    value: str,
) -> dict[str, object]:
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        signature, raw = decoded[:32], decoded[32:]
        expected = hmac.new(
            filesystem.cursor_key,
            _CURSOR_DOMAIN + raw,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(raw)
        required = {
            "v",
            "kind",
            "path",
            "query",
            "case_sensitive",
            "max_depth",
            "page_size",
            "snapshot_id",
            "resource_identity",
            "offset",
        }
        if (
            not isinstance(payload, dict)
            or set(payload) != required
            or payload["v"] != 1
            or payload["kind"] != "search"
        ):
            raise ValueError
        return payload
    except (UnicodeError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeToolError("filesystem_cursor_invalid") from error
