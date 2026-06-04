"""FTS index helpers for Memory source chunks."""

from __future__ import annotations

from pathlib import Path
import re
import sqlite3

from content_store import read_body
from errors import MemoryValidationError


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


def source_chunk_fts_query(query: str) -> str:
    tokens = TOKEN_PATTERN.findall(query)
    if not tokens:
        return ""
    return " OR ".join(f"{token}*" for token in tokens[:12])


def upsert_source_chunk_fts(db: sqlite3.Connection, *, chunk_id: str, body_text: str) -> None:
    row = db.execute(
        """
        SELECT
          sc.id AS chunk_id,
          sc.source_version_id,
          sv.source_id,
          sv.source_document_id,
          s.title,
          s.file_id,
          s.workspace_relative_path,
          s.entity_id
        FROM source_chunks sc
        JOIN source_versions sv ON sv.id = sc.source_version_id
        JOIN sources s ON s.id = sv.source_id
        WHERE sc.id = ?
        """,
        (chunk_id,),
    ).fetchone()
    if row is None:
        return
    db.execute("DELETE FROM source_chunk_fts WHERE chunk_id = ?", (chunk_id,))
    db.execute(
        """
        INSERT INTO source_chunk_fts(
          chunk_id, source_version_id, source_id, source_document_id, title,
          body_text, file_id, workspace_relative_path, entity_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["chunk_id"],
            row["source_version_id"],
            row["source_id"],
            row["source_document_id"] or "",
            row["title"] or "",
            body_text,
            row["file_id"] or "",
            row["workspace_relative_path"] or "",
            row["entity_id"] or "",
        ),
    )


def delete_source_chunk_fts_for_version(db: sqlite3.Connection, source_version_id: str) -> None:
    db.execute("DELETE FROM source_chunk_fts WHERE source_version_id = ?", (source_version_id,))


def rebuild_source_chunk_fts(db: sqlite3.Connection, *, data_root: Path) -> None:
    db.execute("DELETE FROM source_chunk_fts")
    rows = list(
        db.execute(
            """
            SELECT id, body_path, body_sha256
            FROM source_chunks
            WHERE body_path != ''
            ORDER BY created_at, chunk_index
            """
        )
    )
    for row in rows:
        try:
            body = read_body(data_root, relative_path=str(row["body_path"] or ""), expected_sha256=str(row["body_sha256"] or ""))
        except MemoryValidationError:
            continue
        upsert_source_chunk_fts(db, chunk_id=str(row["id"]), body_text=body)


def source_chunk_fts_needs_rebuild(db: sqlite3.Connection) -> bool:
    table = db.execute("SELECT 1 FROM sqlite_master WHERE name = 'source_chunk_fts' LIMIT 1").fetchone()
    if table is None:
        return True
    chunk_count = db.execute("SELECT COUNT(*) AS count FROM source_chunks WHERE body_path != ''").fetchone()["count"]
    indexed_count = db.execute("SELECT COUNT(*) AS count FROM source_chunk_fts").fetchone()["count"]
    return indexed_count < chunk_count
