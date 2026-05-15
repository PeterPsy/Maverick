"""Deterministic compiled wiki content builders."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
import sqlite3

from sources import source_snapshot


SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")


def compiled_markdown(node: sqlite3.Row, refs: list[sqlite3.Row], relationships: list[sqlite3.Row]) -> str:
    lines = [f"# {node['title']}", ""]
    if node["summary"]:
        lines.extend(["## Summary", str(node["summary"]).strip(), ""])
    if node["body_text"]:
        lines.extend(["## Notes", str(node["body_text"]).strip(), ""])
    if refs:
        lines.append("## Sources")
        for ref in refs:
            label = ref["title"] or ref["workspace_relative_path"] or ref["entity_id"] or ref["file_id"] or ref["ref_kind"]
            lines.append(f"- {label}")
        lines.append("")
    if relationships:
        lines.append("## Relationships")
        for edge in relationships:
            reason = f" - {edge['reason']}" if edge["reason"] else ""
            lines.append(f"- {edge['kind']}: {edge['other_title']}{reason}")
        lines.append("")
    return "\n".join(lines).strip()


def claim_texts(node: sqlite3.Row) -> list[str]:
    text = " ".join(str(part or "").strip() for part in (node["summary"], node["body_text"]) if str(part or "").strip())
    candidates = [item.strip() for item in SENTENCE_PATTERN.split(text) if item.strip()]
    if not candidates and node["title"]:
        candidates = [str(node["title"]).strip()]
    return [candidate[:500] for candidate in candidates[:8]]


def compile_input_hash(
    node: sqlite3.Row,
    refs: list[sqlite3.Row],
    relationships: list[sqlite3.Row],
    *,
    data_root: Path | None = None,
) -> str:
    parts = [
        node["id"],
        node["title"],
        node["summary"],
        node["body_text"],
        node["updated_at"],
        *[ref["updated_at"] + ref["id"] + source_snapshot(ref, data_root)["hash"] for ref in refs],
        *[edge["updated_at"] + edge["id"] + edge["kind"] + edge["other_title"] for edge in relationships],
    ]
    return sha256("\n".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()
