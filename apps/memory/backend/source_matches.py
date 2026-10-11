"""Fair, progressive verification of current source matches for selected nodes."""

from pathlib import Path
import sqlite3
from typing import Any

from content_store import read_body
from database import row_payload
from errors import MemoryValidationError
from search_candidates import query_expression, query_terms
from source_retrieval import citations_for_chunk, chunk_freshness, chunk_summary

SOURCE_MATCH_PAGE_SIZE = 8
SOURCE_MATCH_LIMIT = 3


def source_chunk_matches_by_node(
    db: sqlite3.Connection, data_root: Path, query: str, *, node_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    expression = query_expression(query, complete=False)
    if not expression or not node_ids:
        return {}
    pending = list(dict.fromkeys(node_ids))
    matches: dict[str, list[dict[str, Any]]] = {}
    body_cache: dict[str, str] = {}
    invalid_chunks: set[str] = set()
    offset = 0
    while pending:
        counts = dict.fromkeys(pending, 0)
        for row in _candidate_rows(db, expression, pending, offset=offset):
            node_id, chunk_id = row['node_id'], row['chunk_id']
            counts[node_id] += 1
            if len(matches.get(node_id, [])) >= SOURCE_MATCH_LIMIT or chunk_id in invalid_chunks:
                continue
            payload = row_payload(row) or {}
            try:
                if chunk_id not in body_cache:
                    body_cache[chunk_id] = read_body(data_root, relative_path=payload['body_path'],
                                                    expected_sha256=payload['body_sha256'])
                body = body_cache[chunk_id]
            except MemoryValidationError:
                invalid_chunks.add(chunk_id)
                continue
            if source_chunk_match_matches_query(payload, body, query):
                matches.setdefault(node_id, []).append(_match_payload(db, payload, body, query))
        # Only an exhausted per-node stream proves the absence of valid matches.
        # A verified sample is sufficient; only undecided streams advance.
        pending = [node_id for node_id in pending if counts[node_id] == SOURCE_MATCH_PAGE_SIZE
                   and not matches.get(node_id)]
        offset += SOURCE_MATCH_PAGE_SIZE
    return matches


def _candidate_rows(db: sqlite3.Connection, expression: str, node_ids: list[str], *, offset: int):
    marks = ','.join('?' for _ in node_ids)
    return db.execute(f"""WITH matches AS MATERIALIZED (
        SELECT n.id AS node_id, sc.id AS chunk_id, sc.source_version_id, sc.chunk_index,
          sc.body_path, sc.body_sha256, sc.char_start, sc.char_end, sc.locator,
          sc.locator_kind, sc.metadata_json, sv.source_document_id, sv.extraction_status,
          sv.hash_kind, sv.observed_at, s.id AS source_id, s.title AS source_title,
          s.file_id, s.workspace_relative_path, s.entity_id, bm25(source_chunk_fts) AS rank
        FROM source_chunk_fts JOIN source_chunks sc ON sc.id=source_chunk_fts.chunk_id
        JOIN source_versions sv ON sv.id=sc.source_version_id
        JOIN sources s ON s.id=sv.source_id
        JOIN node_source_links nl ON nl.source_id=s.id JOIN nodes n ON n.id=nl.node_id
        WHERE n.status='active' AND sc.body_path!='' AND s.status='active'
          AND s.current_version_id=sv.id AND source_chunk_fts MATCH ? AND n.id IN ({marks})
      ), ranked AS (
        SELECT *, row_number() OVER(PARTITION BY node_id
          ORDER BY rank,observed_at DESC,chunk_index,chunk_id) AS position FROM matches
      ) SELECT * FROM ranked WHERE position>? AND position<=?
        ORDER BY node_id,position""", (expression, *node_ids, offset, offset + SOURCE_MATCH_PAGE_SIZE))


def _match_payload(db: sqlite3.Connection, chunk: dict, body: str, query: str) -> dict:
    return {
        'kind': 'source_chunk', 'source_id': chunk['source_id'],
        'source_document_id': chunk['source_document_id'] or '',
        'source_version_id': chunk['source_version_id'], 'chunk_id': chunk['chunk_id'],
        'title': chunk['source_title'] or chunk['source_id'], 'summary': chunk_summary(body, query),
        'freshness': chunk_freshness(db, chunk), 'hash': chunk['body_sha256'] or '',
        'locator': {'kind': chunk['locator_kind'] or '', 'value': chunk['locator'] or '',
                    'char_start': chunk['char_start'], 'char_end': chunk['char_end']},
        'source': {'file_id': chunk['file_id'] or '',
                   'workspace_relative_path': chunk['workspace_relative_path'] or '',
                   'entity_id': chunk['entity_id'] or '', 'hash_kind': chunk['hash_kind'] or '',
                   'extraction_status': chunk['extraction_status'] or ''},
        'citations': citations_for_chunk(db, chunk['chunk_id'], limit=4),
    }


def source_chunk_match_matches_query(payload: dict[str, Any], chunk_body: str, query: str) -> bool:
    normalized = query.strip().casefold()
    if not normalized:
        return False
    haystacks = (chunk_body, str(payload.get('source_title') or ''), str(payload.get('file_id') or ''),
                 str(payload.get('entity_id') or ''), str(payload.get('workspace_relative_path') or ''))
    haystack = ' '.join(value for value in haystacks if value).casefold()
    if normalized in haystack:
        return True
    tokens = query_terms(query)
    return bool(tokens) and sum(token in haystack for token in tokens) / len(tokens) >= .5
