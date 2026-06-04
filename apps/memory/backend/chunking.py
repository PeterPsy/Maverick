"""Deterministic source body chunking for Memory."""

from __future__ import annotations

from dataclasses import dataclass

from content_store import canonical_body


MAX_CHUNK_CHARS = 1800
MIN_CHUNK_CHARS = 900


@dataclass(frozen=True)
class SourceChunkDraft:
    chunk_index: int
    body: str
    char_start: int
    char_end: int


def chunk_source_body(body_markdown: str, *, max_chars: int = MAX_CHUNK_CHARS) -> list[SourceChunkDraft]:
    body = canonical_body(body_markdown)
    if not body:
        return []
    if len(body) <= max_chars:
        return [SourceChunkDraft(chunk_index=0, body=body, char_start=0, char_end=len(body))]

    chunks: list[SourceChunkDraft] = []
    start = 0
    while start < len(body):
        end = min(len(body), start + max_chars)
        if end < len(body):
            split_at = _best_split(body, start, end)
            if split_at > start:
                end = split_at
        chunk_body = body[start:end]
        if chunk_body.strip():
            chunks.append(
                SourceChunkDraft(
                    chunk_index=len(chunks),
                    body=chunk_body,
                    char_start=start,
                    char_end=end,
                )
            )
        start = end
        while start < len(body) and body[start] in " \t\n":
            start += 1
    return chunks


def _best_split(body: str, start: int, end: int) -> int:
    minimum = min(end, start + MIN_CHUNK_CHARS)
    candidates = [
        body.rfind("\n\n", minimum, end),
        body.rfind(". ", minimum, end),
        body.rfind("? ", minimum, end),
        body.rfind("! ", minimum, end),
        body.rfind("\n", minimum, end),
        body.rfind(" ", minimum, end),
    ]
    split_at = max(candidates)
    if split_at <= start:
        return end
    if body[split_at : split_at + 2] in {". ", "? ", "! "}:
        return split_at + 2
    return split_at
