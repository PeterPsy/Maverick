"""Rank all direct retrieval channels before applying the result limit."""

import re
import sqlite3

TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
QUERY_STOPWORDS = {"il", "lo", "la", "i", "gli", "le", "un", "una", "di", "del", "della", "a", "da", "in", "e", "è", "che", "quale", "chi", "come", "the", "a", "an", "of", "is", "and", "what", "who"}


def query_terms(query: str) -> list[str]:
    terms = list(dict.fromkeys(TOKEN_PATTERN.findall(query.casefold())))[:12]
    return [term for term in terms if term not in QUERY_STOPWORDS] or terms


def query_expression(query: str, *, complete: bool = True) -> str:
    return (" AND " if complete else " OR ").join('"' + term + '"' for term in query_terms(query))


def scope_sql(scope: dict | None, *, alias: str = "nodes") -> tuple[str, list[str]]:
    clauses, values = [], []
    for key in ("project_id", "person_id"):
        if scope and scope.get(key):
            clauses.append(f"AND COALESCE(json_extract({alias}.metadata_json, '$.{key}'), '') = ?")
            values.append(str(scope[key]))
    return " ".join(clauses), values


def ranked_candidates(db: sqlite3.Connection, query: str, *, limit: int, scope: dict | None = None) -> list[dict]:
    terms = query_terms(query)
    if not terms:
        return []
    candidate_limit = max(100, min(500, limit * 10))
    scope_clause, scope_values = scope_sql(scope, alias="n")
    candidates: dict[str, dict] = {}
    for complete in (True, False):
        expression = query_expression(query, complete=complete)
        rows = list(db.execute(f"""SELECT n.id, n.title, n.summary, n.importance, n.confidence, n.updated_at,
            n.metadata_json, bm25(memory_fts, 0, 5, 3, 1, 0.5) AS rank,
            snippet(memory_fts, 3, '', '', '…', 64) AS excerpt, 'node' AS channel
            FROM memory_fts JOIN nodes n ON n.id = memory_fts.node_id
            WHERE memory_fts MATCH ? AND n.status = 'active' {scope_clause}
            ORDER BY rank LIMIT ?""", (expression, *scope_values, candidate_limit)))
        rows += list(db.execute(f"""SELECT n.id, n.title, n.summary, n.importance, n.confidence, n.updated_at,
            n.metadata_json, bm25(compiled_fts, 0, 5, 3, 1, 2) AS rank,
            snippet(compiled_fts, 3, '', '', '…', 64) AS excerpt, 'wiki_page' AS channel
            FROM compiled_fts JOIN nodes n ON n.id = compiled_fts.node_id
            JOIN wiki_pages wp ON wp.node_id = n.id
            WHERE compiled_fts MATCH ? AND n.status = 'active' AND wp.status = 'active' AND wp.freshness = 'fresh'
            {scope_clause} ORDER BY rank LIMIT ?""", (expression, *scope_values, candidate_limit)))
        rows += list(db.execute(f"""SELECT n.id, n.title, n.summary, n.importance, n.confidence, n.updated_at,
            n.metadata_json, bm25(compiled_fts, 0, 5, 3, 1, 2) AS rank,
            snippet(compiled_fts, 4, '', '', '…', 64) AS excerpt, 'claim' AS channel
            FROM compiled_fts JOIN nodes n ON n.id = compiled_fts.node_id JOIN wiki_pages wp ON wp.node_id = n.id
            WHERE compiled_fts MATCH ? AND n.status = 'active' AND wp.status = 'active' AND wp.freshness = 'fresh'
            {scope_clause} ORDER BY rank LIMIT ?""", ("claim_text : (" + expression + ")", *scope_values, candidate_limit)))
        rows += list(db.execute(f"""SELECT n.id, n.title, n.summary, n.importance, n.confidence, n.updated_at,
            n.metadata_json, bm25(source_chunk_fts, 0, 0, 0, 0, 4, 1, 0.5, 0.5, 0.5) AS rank,
            snippet(source_chunk_fts, 5, '', '', '…', 64) AS excerpt, 'source_chunk' AS channel,
            sc.id AS chunk_id, s.id AS source_id, sv.id AS source_version_id
            FROM source_chunk_fts JOIN source_chunks sc ON sc.id = source_chunk_fts.chunk_id
            JOIN source_versions sv ON sv.id = sc.source_version_id
            JOIN sources s ON s.id = sv.source_id AND s.current_version_id = sv.id
            JOIN node_source_links nl ON nl.source_id = s.id JOIN nodes n ON n.id = nl.node_id
            WHERE source_chunk_fts MATCH ? AND s.status = 'active' AND n.status = 'active'
            {scope_clause} ORDER BY rank LIMIT ?""", (expression, *scope_values, candidate_limit)))
        for row in rows:
            item = dict(row)
            text = " ".join((item["title"], item["summary"], item["excerpt"])).casefold()
            coverage = 1.0 if complete else sum(term in TOKEN_PATTERN.findall(text) for term in terms) / len(terms)
            # Relevance is a ranking score, explicitly not a probability.
            score = .75 * coverage + .1 * min(1, abs(item["rank"]) * 100) + .05 * item["importance"]
            if item["channel"] == "source_chunk":
                score += .1
            item.update(relevance=round(min(1., score), 3), match_sources=[item["channel"]])
            old = candidates.get(item["id"])
            if old:
                channels = list(dict.fromkeys(old["match_sources"] + item["match_sources"]))
                if old["relevance"] >= item["relevance"]:
                    old["match_sources"] = channels
                    continue
                item["match_sources"] = channels
            candidates[item["id"]] = item
        if len(candidates) >= limit:
            break
    return sorted(candidates.values(), key=lambda item: (item["relevance"], item["importance"], item["updated_at"], item["id"]), reverse=True)
