"""Bounded agent-facing context payloads for Memory retrieval."""

from __future__ import annotations

import json
from typing import Any


MEMORY_CONTEXT_PROFILE = "agent_compact"
MEMORY_CONTEXT_TARGET_BYTES = 9_500
MEMORY_CONTEXT_QUERY_SNIPPET_CHARS = 420
MEMORY_CONTEXT_COMPACTION_LEVELS = (
    {
        "summary_chars": 360,
        "body_chars": 520,
        "compiled_summary_chars": 320,
        "claim_chars": 260,
        "quote_chars": 220,
        "reason_chars": 220,
        "ref_limit": 3,
        "source_chunk_limit": 3,
        "claim_limit": 3,
        "citation_limit": 3,
        "lint_limit": 2,
    },
    {
        "summary_chars": 260,
        "body_chars": 280,
        "compiled_summary_chars": 180,
        "claim_chars": 180,
        "quote_chars": 160,
        "reason_chars": 160,
        "ref_limit": 2,
        "source_chunk_limit": 2,
        "claim_limit": 2,
        "citation_limit": 2,
        "lint_limit": 1,
    },
    {
        "summary_chars": 180,
        "body_chars": 140,
        "compiled_summary_chars": 120,
        "claim_chars": 120,
        "quote_chars": 100,
        "reason_chars": 120,
        "ref_limit": 1,
        "source_chunk_limit": 1,
        "claim_limit": 1,
        "citation_limit": 1,
        "lint_limit": 1,
    },
    {
        "summary_chars": 140,
        "body_chars": 0,
        "compiled_summary_chars": 0,
        "claim_chars": 0,
        "quote_chars": 0,
        "reason_chars": 80,
        "ref_limit": 1,
        "source_chunk_limit": 1,
        "claim_limit": 0,
        "citation_limit": 1,
        "lint_limit": 0,
    },
)


def agent_compact_context_payload(
    query: str,
    items: list[dict[str, Any]],
    *,
    requested_limit: int,
) -> dict[str, Any]:
    """Return a bounded Memory context payload suitable for agent provider context."""
    for options in MEMORY_CONTEXT_COMPACTION_LEVELS:
        payload = build_agent_context_payload(query, items, requested_limit=requested_limit, options=options)
        if json_byte_len(payload) <= MEMORY_CONTEXT_TARGET_BYTES:
            return payload

    tight_options = MEMORY_CONTEXT_COMPACTION_LEVELS[-1]
    included = list(items)
    while included:
        payload = build_agent_context_payload(
            query,
            included,
            requested_limit=requested_limit,
            options=tight_options,
            omitted_item_count=len(items) - len(included),
        )
        if json_byte_len(payload) <= MEMORY_CONTEXT_TARGET_BYTES:
            return payload
        included.pop()
    return build_agent_context_payload(
        query,
        [],
        requested_limit=requested_limit,
        options=tight_options,
        omitted_item_count=len(items),
    )


def build_agent_context_payload(
    query: str,
    items: list[dict[str, Any]],
    *,
    requested_limit: int,
    options: dict[str, int],
    omitted_item_count: int = 0,
) -> dict[str, Any]:
    compact_items = [agent_compact_memory_item(item, options=options) for item in items]
    query_text = normalize_spaces(query)
    query_snippet = bounded_text(query_text, MEMORY_CONTEXT_QUERY_SNIPPET_CHARS)
    return {
        "query": query_snippet,
        "query_snippet": query_snippet,
        "query_char_count": len(query_text),
        "query_truncated": query_snippet != query_text,
        "profile": MEMORY_CONTEXT_PROFILE,
        "requested_limit": requested_limit,
        "item_count": len(compact_items),
        "total_candidate_count": len(items) + omitted_item_count,
        "has_more": omitted_item_count > 0,
        "omitted_item_count": omitted_item_count,
        "items": compact_items,
        "expand": {
            "node_tool": "memory_inspect_node",
            "node_arguments": {"node_id": "<items[].node_id>"},
            "source_chunks_tool": "memory_fetch_chunks",
            "source_chunks_arguments": {"chunk_ids": "<items[].source_chunk_matches[].chunk_id>"},
            "note": (
                "Use memory_inspect_node for full node body, compiled wiki body, claims, citations, "
                "sources, and lint findings; use memory_fetch_chunks for source chunk body text."
            ),
        },
    }


def agent_compact_memory_item(item: dict[str, Any], *, options: dict[str, int]) -> dict[str, Any]:
    node = item.get("node") if isinstance(item.get("node"), dict) else {}
    node_id = str(item.get("node_id") or item.get("id") or node.get("node_id") or node.get("id") or "").strip()
    body_text = str(item.get("body_text") or node.get("body_text") or "")
    summary_source = str(item.get("summary") or node.get("summary") or body_text)
    body_snippet = bounded_text(body_text, options["body_chars"])
    compact: dict[str, Any] = {
        "kind": item.get("kind") or "memory_node",
        "id": str(item.get("id") or node_id),
        "node_id": node_id,
        "entity": compact_entity(item.get("entity"), node_id=node_id),
        "locator": compact_locator(item.get("locator"), node_id=node_id),
        "source_version_id": str(item.get("source_version_id") or ""),
        "chunk_id": str(item.get("chunk_id") or ""),
        "freshness": item.get("freshness") or "unknown",
        "type": item.get("type") or node.get("type") or "",
        "title": bounded_text(item.get("title") or node.get("title") or node_id, 240),
        "summary": bounded_text(summary_source, options["summary_chars"]),
        "status": item.get("status") or node.get("status") or "active",
        "importance": item.get("importance") if item.get("importance") is not None else node.get("importance"),
        "confidence": item.get("confidence") if item.get("confidence") is not None else node.get("confidence"),
        "body_text_char_count": len(body_text),
        "body_text_truncated": bool(body_text and body_snippet != normalize_spaces(body_text)),
        "match_sources": string_list(item.get("match_sources")),
        "source_chunk_matches": compact_source_chunk_matches(
            item.get("source_chunk_matches"),
            limit=options["source_chunk_limit"],
            citation_limit=options["citation_limit"],
            quote_chars=options["quote_chars"],
        ),
        "citations": compact_citations(
            item.get("citations"),
            limit=options["citation_limit"],
            quote_chars=options["quote_chars"],
        ),
        "provenance": compact_external_refs(item.get("provenance"), limit=options["ref_limit"]),
        "storage_references": compact_storage_references(item.get("storage_references"), limit=options["ref_limit"]),
        "compiled": compact_context_compiled_payload(item.get("compiled"), options=options),
    }
    if body_snippet:
        compact["body_text"] = body_snippet
    relevance = item.get("relevance")
    if isinstance(relevance, (int, float)):
        compact["relevance"] = round(float(relevance), 3)
    reason = bounded_text(item.get("reason"), options["reason_chars"])
    if reason:
        compact["reason"] = reason
    return compact


def compact_context_compiled_payload(value: Any, *, options: dict[str, int]) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}
    body_markdown = str(value.get("body_markdown") or "")
    compact: dict[str, Any] = {
        "wiki_page_id": value.get("wiki_page_id") or "",
        "summary": bounded_text(value.get("summary"), options["compiled_summary_chars"]),
        "body_markdown_char_count": len(body_markdown),
        "body_markdown_available": bool(body_markdown),
        "freshness": value.get("freshness") or "unknown",
        "compiled_at": value.get("compiled_at") or "",
        "claims": compact_claims(
            value.get("claims"),
            limit=options["claim_limit"],
            claim_chars=options["claim_chars"],
            citation_limit=options["citation_limit"],
            quote_chars=options["quote_chars"],
        ),
        "citations": compact_citations(
            value.get("citations"),
            limit=options["citation_limit"],
            quote_chars=options["quote_chars"],
        ),
        "storage_references": compact_storage_references(value.get("storage_references"), limit=options["ref_limit"]),
        "lint_findings": compact_lint_findings(value.get("lint_findings"), limit=options["lint_limit"]),
    }
    return compact_dict(compact)


def compact_claims(value: Any, *, limit: int, claim_chars: int, citation_limit: int, quote_chars: int) -> list[dict[str, Any]]:
    claims = value if isinstance(value, list) else []
    compacted: list[dict[str, Any]] = []
    for claim in claims[:limit]:
        if not isinstance(claim, dict):
            continue
        compacted.append(
            compact_dict(
                {
                    "id": claim.get("id"),
                    "claim_id": claim.get("claim_id"),
                    "node_id": claim.get("node_id"),
                    "claim_text": bounded_text(claim.get("claim_text") or claim.get("summary"), claim_chars),
                    "status": claim.get("status"),
                    "confidence": claim.get("confidence"),
                    "citations": compact_citations(
                        claim.get("citations"),
                        limit=citation_limit,
                        quote_chars=quote_chars,
                    ),
                }
            )
        )
    return compacted


def compact_citations(value: Any, *, limit: int, quote_chars: int) -> list[dict[str, Any]]:
    citations = value if isinstance(value, list) else []
    compacted: list[dict[str, Any]] = []
    for citation in citations[:limit]:
        if not isinstance(citation, dict):
            continue
        compacted.append(
            compact_dict(
                {
                    "id": citation.get("id"),
                    "claim_id": citation.get("claim_id"),
                    "source_id": citation.get("source_id"),
                    "source_version_id": citation.get("source_version_id"),
                    "source_chunk_id": citation.get("source_chunk_id"),
                    "external_ref_id": citation.get("external_ref_id"),
                    "locator": citation.get("locator"),
                    "locator_kind": citation.get("locator_kind"),
                    "char_start": citation.get("char_start"),
                    "char_end": citation.get("char_end"),
                    "quote": bounded_text(citation.get("quote"), quote_chars),
                    "quote_sha256": citation.get("quote_sha256"),
                    "source_version": citation.get("source_version"),
                    "storage_reference": compact_storage_reference(citation.get("storage_reference")),
                }
            )
        )
    return compacted


def compact_source_chunk_matches(
    value: Any,
    *,
    limit: int,
    citation_limit: int,
    quote_chars: int,
) -> list[dict[str, Any]]:
    matches = value if isinstance(value, list) else []
    compacted: list[dict[str, Any]] = []
    for match in matches[:limit]:
        if not isinstance(match, dict):
            continue
        source = match.get("source") if isinstance(match.get("source"), dict) else {}
        compacted.append(
            compact_dict(
                {
                    "kind": match.get("kind"),
                    "source_id": match.get("source_id"),
                    "source_document_id": match.get("source_document_id"),
                    "source_version_id": match.get("source_version_id"),
                    "chunk_id": match.get("chunk_id"),
                    "title": bounded_text(match.get("title"), 180),
                    "freshness": match.get("freshness"),
                    "hash": match.get("hash"),
                    "locator": compact_locator(match.get("locator"), node_id=""),
                    "source": compact_dict(
                        {
                            "file_id": source.get("file_id"),
                            "workspace_relative_path": source.get("workspace_relative_path"),
                            "entity_id": source.get("entity_id"),
                            "hash_kind": source.get("hash_kind"),
                            "extraction_status": source.get("extraction_status"),
                        }
                    ),
                    "citations": compact_citations(match.get("citations"), limit=citation_limit, quote_chars=quote_chars),
                }
            )
        )
    return compacted


def compact_lint_findings(value: Any, *, limit: int) -> list[dict[str, Any]]:
    findings = value if isinstance(value, list) else []
    compacted: list[dict[str, Any]] = []
    for finding in findings[:limit]:
        if not isinstance(finding, dict):
            continue
        compacted.append(
            compact_dict(
                {
                    "id": finding.get("id"),
                    "finding_type": finding.get("finding_type"),
                    "severity": finding.get("severity"),
                    "message": bounded_text(finding.get("message"), 180),
                    "node_id": finding.get("node_id"),
                    "source_id": finding.get("source_id"),
                }
            )
        )
    return compacted


def compact_external_refs(value: Any, *, limit: int) -> list[dict[str, Any]]:
    refs = value if isinstance(value, list) else []
    compacted: list[dict[str, Any]] = []
    for ref in refs[:limit]:
        if not isinstance(ref, dict):
            continue
        metadata = ref.get("metadata") if isinstance(ref.get("metadata"), dict) else {}
        compacted.append(
            compact_dict(
                {
                    "id": ref.get("id"),
                    "ref_kind": ref.get("ref_kind"),
                    "owning_app_id": ref.get("owning_app_id"),
                    "entity_type": ref.get("entity_type"),
                    "entity_id": ref.get("entity_id"),
                    "file_id": ref.get("file_id"),
                    "workspace_relative_path": ref.get("workspace_relative_path"),
                    "uri": ref.get("uri"),
                    "title": bounded_text(ref.get("title"), 180),
                    "metadata": compact_dict(
                        {
                            "provider": metadata.get("provider"),
                            "connection_id": metadata.get("connection_id"),
                            "drive_file_id": metadata.get("drive_file_id"),
                            "source_version": metadata.get("source_version"),
                            "indexed_source_version": metadata.get("indexed_source_version"),
                            "display_path": metadata.get("display_path"),
                        }
                    ),
                }
            )
        )
    return compacted


def compact_storage_references(value: Any, *, limit: int) -> list[dict[str, Any]]:
    refs = value if isinstance(value, list) else []
    return [ref for ref in (compact_storage_reference(ref) for ref in refs[:limit]) if ref]


def compact_storage_reference(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    compacted = compact_dict(
        {
            "app_id": value.get("app_id"),
            "owning_app_id": value.get("owning_app_id"),
            "entity_type": value.get("entity_type"),
            "provider": value.get("provider"),
            "stable_storage_file_id": value.get("stable_storage_file_id"),
            "file_id": value.get("file_id"),
            "entity_id": value.get("entity_id"),
            "ref_kind": value.get("ref_kind"),
            "title": bounded_text(value.get("title"), 180),
            "display_path": bounded_text(value.get("display_path"), 240),
            "connection_id": value.get("connection_id"),
            "drive_file_id": value.get("drive_file_id"),
            "source_version": value.get("source_version"),
            "indexed_source_version": value.get("indexed_source_version"),
            "deep_link": value.get("deep_link"),
            "reference_resolve_request": value.get("reference_resolve_request"),
            "preview_request": value.get("preview_request"),
            "export_request": value.get("export_request"),
            "reference_request": value.get("reference_request"),
        }
    )
    if "workspace_relative_path" in value:
        compacted["workspace_relative_path"] = str(value.get("workspace_relative_path") or "")
    return compacted


def compact_entity(value: Any, *, node_id: str) -> dict[str, Any]:
    entity = value if isinstance(value, dict) else {}
    return compact_dict(
        {
            "entity_type": entity.get("entity_type") or "node",
            "entity_id": entity.get("entity_id") or node_id,
        }
    )


def compact_locator(value: Any, *, node_id: str) -> dict[str, Any]:
    locator = value if isinstance(value, dict) else {}
    return compact_dict(
        {
            "kind": locator.get("kind") or ("memory_node" if node_id else ""),
            "value": locator.get("value") or node_id,
            "char_start": locator.get("char_start"),
            "char_end": locator.get("char_end"),
        }
    )


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def compact_dict(value: dict[str, Any]) -> dict[str, Any]:
    compacted: dict[str, Any] = {}
    for key, item in value.items():
        if item is None or item == "" or item == [] or item == {}:
            continue
        compacted[key] = item
    return compacted


def bounded_text(value: Any, max_chars: int) -> str:
    text = normalize_spaces(value)
    if max_chars <= 0 or not text:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3].rstrip() + "..."


def normalize_spaces(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def json_byte_len(value: dict[str, Any]) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))
