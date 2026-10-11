"""Claim extraction and verified supporting or conflicting passages."""

from hashlib import sha256
from pathlib import Path
import sqlite3
from typing import Any

from citation_matching import citation_quote, contradiction_quote, related_quote
from content_store import read_body
from database import json_text, new_id, row_payload
from evidence_propositions import complete_chunk_bodies
from wiki_content import claim_texts


def replace_claims(
    db: sqlite3.Connection,
    *,
    data_root: Path,
    page_id: str,
    node: sqlite3.Row,
    sources: list[dict[str, Any]],
    timestamp: str,
) -> None:
    old_claim_ids = [row["id"] for row in db.execute("SELECT id FROM claims WHERE wiki_page_id = ?", (page_id,))]
    if old_claim_ids:
        placeholders = ",".join("?" for _item in old_claim_ids)
        db.execute(f"DELETE FROM citations WHERE claim_id IN ({placeholders})", tuple(old_claim_ids))
        db.execute(f"DELETE FROM lint_findings WHERE claim_id IN ({placeholders})", tuple(old_claim_ids))
    db.execute("DELETE FROM claims WHERE wiki_page_id = ?", (page_id,))
    candidates = citation_sources(db, sources, data_root=data_root)
    for claim_text in claim_texts(node):
        claim = {
            "id": new_id("claim"),
            "wiki_page_id": page_id,
            "node_id": node["id"],
            "claim_text": claim_text,
            "confidence": float(node["confidence"]),
            "created_at": timestamp,
            "updated_at": timestamp,
            "metadata_json": json_text({"source": "node_content"}),
        }
        db.execute(
            """
            INSERT INTO claims(id, wiki_page_id, node_id, claim_text, confidence, created_at, updated_at, metadata_json)
            VALUES (:id, :wiki_page_id, :node_id, :claim_text, :confidence, :created_at, :updated_at, :metadata_json)
            """,
            claim,
        )
        for source, version, chunk, chunk_body, complete_body in candidates:
            quote = citation_quote(claim_text, complete_body)
            relation = "supports"
            if not quote:
                quote = contradiction_quote(claim_text, complete_body)
                relation = "contradicts"
            if not quote:
                quote = related_quote(claim_text, chunk_body)
                relation = "related"
            if not quote:
                continue
            char_start, char_end = quote_range(chunk_body, quote)
            metadata = dict(source.get("metadata") or {})
            version_metadata = dict(version.get("metadata") or {})
            metadata["source_version"] = version_metadata.get("source_version") or metadata.get("source_version") or version["version_hash"]
            db.execute(
                """
                INSERT INTO citations(
                  id, claim_id, source_id, source_version_id, source_chunk_id, external_ref_id,
                  locator, locator_kind, char_start, char_end, quote_sha256, quote, created_at, metadata_json, evidence_relation
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("cite"),
                    claim["id"],
                    source["id"],
                    version["id"],
                    chunk["id"],
                    source.get("external_ref_id"),
                    citation_locator(source, version, chunk),
                    chunk.get("locator_kind") or "preview_text",
                    char_start,
                    char_end,
                    sha256(quote.encode("utf-8")).hexdigest(),
                    quote,
                    timestamp,
                    json_text(metadata),
                    relation,
                ),
            )


def citation_sources(
    db: sqlite3.Connection,
    sources: list[dict[str, Any]],
    *,
    data_root: Path,
) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, str]]:
    claim_sources: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, str]] = []
    for source in sources:
        version_id = str(source.get("source_version_id") or "")
        if not version_id:
            continue
        version_row = db.execute("SELECT * FROM source_versions WHERE id = ?", (version_id,)).fetchone()
        version = row_payload(version_row) or {}
        chunk_rows = db.execute(
            "SELECT * FROM source_chunks WHERE source_version_id = ? ORDER BY chunk_index",
            (version_id,),
        )
        version_chunks = []
        for chunk_row in chunk_rows:
            chunk = row_payload(chunk_row) or {}
            if not chunk:
                continue
            chunk_body = read_body(data_root, relative_path=str(chunk.get("body_path") or ""), expected_sha256=str(chunk.get("body_sha256") or ""))
            if not chunk_body.strip():
                continue
            version_chunks.append((chunk, chunk_body))
        complete_bodies = complete_chunk_bodies([body for _chunk, body in version_chunks])
        for (chunk, chunk_body), complete_body in zip(version_chunks, complete_bodies):
            claim_sources.append((source, version, chunk, chunk_body, complete_body))
    return claim_sources


def citation_locator(source: dict[str, Any], version: dict[str, Any], chunk: dict[str, Any] | None = None) -> str:
    metadata = dict(source.get("metadata") or {})
    return str(
        (chunk or {}).get("locator")
        or metadata.get("display_path")
        or version.get("extracted_ref")
        or source.get("workspace_relative_path")
        or source.get("entity_id")
        or source.get("uri")
        or ""
    )


def quote_range(body: str, quote: str) -> tuple[int, int]:
    if not quote:
        return (0, 0)
    start = body.find(quote)
    if start != -1:
        return (start, start + len(quote))
    collapsed_quote = " ".join(quote.split()).strip()
    if not collapsed_quote:
        return (0, 0)
    collapsed_body, original_offsets = collapsed_text_with_offsets(body)
    collapsed_start = collapsed_body.find(collapsed_quote)
    if collapsed_start == -1:
        return (0, 0)
    collapsed_end = collapsed_start + len(collapsed_quote) - 1
    return (original_offsets[collapsed_start], original_offsets[collapsed_end] + 1)


def collapsed_text_with_offsets(body: str) -> tuple[str, list[int]]:
    characters: list[str] = []
    offsets: list[int] = []
    in_whitespace = False
    for index, character in enumerate(body):
        if character.isspace():
            if not in_whitespace:
                characters.append(" ")
                offsets.append(index)
                in_whitespace = True
            continue
        characters.append(character)
        offsets.append(index)
        in_whitespace = False
    if characters and characters[0] == " ":
        characters.pop(0)
        offsets.pop(0)
    if characters and characters[-1] == " ":
        characters.pop()
        offsets.pop()
    return ("".join(characters), offsets)
