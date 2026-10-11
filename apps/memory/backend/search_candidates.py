"""Rank all direct retrieval channels before applying the result limit."""

import json
import re
from datetime import date

from errors import MemoryValidationError
import sqlite3

TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
QUERY_STOPWORDS = {"il", "lo", "la", "i", "gli", "le", "un", "una", "di", "del", "della", "a", "da", "in", "e", "è", "che", "quale", "chi", "come", "the", "a", "an", "of", "is", "and", "what", "who"}


def query_terms(query: str) -> list[str]:
    terms = list(dict.fromkeys(TOKEN_PATTERN.findall(query.casefold())))[:12]
    return [term for term in terms if term not in QUERY_STOPWORDS] or terms


def query_expression(query: str, *, complete: bool = True) -> str:
    return (" AND " if complete else " OR ").join('"' + term + '"' for term in query_terms(query))


def scope_sql(scope: dict | None, *, alias: str = "nodes") -> tuple[str, list]:
    scope = scope or {}
    clauses, values = [], []
    if scope.get('_node_ids'):
        ids = scope['_node_ids']
        clauses.append(f"AND {alias}.id IN ({','.join('?' for _ in ids)})")
        values.extend(ids)
    for key in ("project_id", "person_id"):
        if scope.get(key):
            field = f"COALESCE(json_extract({alias}.metadata_json, '$.{key}'), '')"
            clauses.append(f"AND ({field} = ?" + (f" OR {field} = ''" if scope.get("include_unscoped") else "") + ")")
            values.append(str(scope[key]))
    as_of = str(scope.get("as_of") or date.today().isoformat())
    try:
        date.fromisoformat(as_of)
    except ValueError:
        raise MemoryValidationError("as_of must be an ISO date (YYYY-MM-DD).") from None
    if not scope.get("include_expired"):
        for key, operator in (("valid_from", "<="), ("valid_until", ">=")):
            field = f"COALESCE(json_extract({alias}.metadata_json, '$.{key}'), '')"
            clauses.append(f"AND ({field} = '' OR substr({field},1,10) {operator} ?)")
            values.append(as_of)
    return " ".join(clauses), values


def candidate_node_scope(scope: dict | None, node_ids: list[str]) -> dict:
    return {**(scope or {}), '_node_ids': node_ids}


def ranked_candidates(db: sqlite3.Connection, query: str, *, limit: int, scope: dict | None = None,
                      offset: int = 0, channels: list[str] | None = None) -> list[dict]:
    terms = query_terms(query)
    if not terms:
        return []
    scope_clause, scope_values = scope_sql(scope, alias="n")
    unions, values = [], []
    selected_channels = channels or ["node", "wiki_page", "claim", "source_chunk", "identity"]
    def coverage(title, summary, excerpt):
        tokens = set(TOKEN_PATTERN.findall(' '.join((title or '',summary or '',excerpt or '')).casefold()))
        return sum(term in tokens for term in terms)/len(terms)
    db.create_function('memory_coverage',3,coverage,deterministic=True)
    for complete in (True, False):
        expression = query_expression(query, complete=complete)
        for channel in selected_channels:
            if channel == "identity":
                continue
            table = "memory_fts" if channel == "node" else "source_chunk_fts" if channel == "source_chunk" else "compiled_fts"
            if channel == "source_chunk":
                joins = """JOIN source_chunks sc ON sc.id=source_chunk_fts.chunk_id
                    JOIN source_versions sv ON sv.id=sc.source_version_id
                    JOIN sources s ON s.id=sv.source_id AND s.current_version_id=sv.id
                    JOIN node_source_links nl ON nl.source_id=s.id JOIN nodes n ON n.id=nl.node_id"""
                filters = "AND s.status='active' AND sc.body_path != ''"
            else:
                joins = f"JOIN nodes n ON n.id={table}.node_id"
                filters = ""
                if channel != "node":
                    joins += " JOIN wiki_pages wp ON wp.node_id=n.id"
                    filters = "AND wp.status='active' AND wp.freshness='fresh'"
            search = "claim_text : (" + expression + ")" if channel == "claim" else expression
            # Complete matches precede partial matches; the SQL score is a rank,
            # never a probability. Aggregate all channels before paging.
            excerpt_column = 5 if channel == 'source_chunk' else 4 if channel == 'claim' else 3
            base = '0.75' if complete else f"0.75*memory_coverage(n.title,n.summary,snippet({table},{excerpt_column},'','','…',64))"
            bonus = 0.1 if channel == "source_chunk" else 0
            weights = ',0,5,3,1,0.5' if channel == 'node' else ',0,5,3,1,2' if channel != 'source_chunk' else ',0,0,0,0,4,1,0.5,0.5,0.5'
            unions.append(f"""SELECT n.id, '{channel}' AS channel,
                min(1.0,{base}+{bonus}+0.1*min(1,abs(bm25({table}{weights}))*100)+0.05*n.importance) AS score FROM {table} {joins}
                WHERE {table} MATCH ? AND n.status='active' {filters} {scope_clause}""")
            values.extend([search, *scope_values])
    if "identity" in selected_channels:
        unions.append(f"""SELECT n.id, 'identity' AS channel, 1.0 AS score FROM nodes n
            WHERE n.status='active' {scope_clause} AND (
              lower(n.id)=lower(?) OR lower(COALESCE(json_extract(n.metadata_json,'$.person_id'),''))=lower(?)
              OR lower(COALESCE(json_extract(n.metadata_json,'$.project_id'),''))=lower(?)
              OR EXISTS(SELECT 1 FROM json_each(CASE WHEN json_type(n.metadata_json,'$.aliases')='array'
                THEN json_extract(n.metadata_json,'$.aliases') ELSE '[]' END) WHERE lower(value)=lower(?))
              OR EXISTS(SELECT 1 FROM external_refs er WHERE er.node_id=n.id AND lower(er.entity_id)=lower(?)
                AND NOT EXISTS(SELECT 1 FROM sources s WHERE s.external_ref_id=er.id AND s.status!='active')))""")
        values.extend([*scope_values, *([query.strip()] * 5)])
    sql = " UNION ALL ".join(unions)
    rows = db.execute(f"""WITH matches AS MATERIALIZED ({sql}), ranked AS (
        SELECT id,max(score) AS relevance,json_group_array(DISTINCT channel) AS channels FROM matches GROUP BY id)
        SELECT ranked.*,n.importance,n.updated_at FROM ranked JOIN nodes n ON n.id=ranked.id
        ORDER BY relevance DESC,n.importance DESC,n.updated_at DESC,n.id DESC LIMIT ? OFFSET ?""", (*values, limit, offset))
    return [{"id": row["id"], "relevance": round(row["relevance"],3), "importance": row["importance"],
             "updated_at": row["updated_at"], "match_sources": json.loads(row["channels"])} for row in rows]
