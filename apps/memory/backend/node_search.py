"""Paged node candidate selection and lightweight search results."""

from pathlib import Path

from database import connect, ensure_schema, normalize_limit
from retrieval_cards import node_cards
from retrieval_pages import bounded_page, byte_count, fingerprint, page_offset, response_budget, retrieval_revision
from search_candidates import ranked_candidates, scope_sql


def search_candidates_page(db, query: str, *, limit: int, scope: dict | None = None,
                           offset: int = 0, node_ids: list[str] | None = None) -> list[dict]:
    if query.strip():
        if node_ids:
            # Restrict before paging, including when there are >500 text matches.
            from search_candidates import candidate_node_scope
            return ranked_candidates(db, query, limit=limit+1, scope=candidate_node_scope(scope, node_ids), offset=offset)
        return ranked_candidates(db, query, limit=limit+1, scope=scope, offset=offset)
    clause, values = scope_sql(scope, alias='n')
    return [{**dict(row), 'match_sources':['node'], 'relevance':row['importance']} for row in db.execute(
        f"SELECT n.id,n.importance FROM nodes n WHERE n.status='active' {clause} ORDER BY n.importance DESC,n.updated_at DESC,n.id DESC LIMIT ? OFFSET ?", (*values,limit+1,offset))]


def search_page(data_root: Path, body: dict, *, scope: dict | None = None) -> dict:
    ensure_schema(data_root)
    query = str(body.get('query') or '').strip()
    limit = normalize_limit(body.get('limit'), default=10, minimum=1, maximum=50)
    budget = response_budget(body.get('max_bytes'))
    detail = body.get('detail','card')
    from errors import MemoryValidationError
    if detail not in ('card','evidence'):
        raise MemoryValidationError('Search detail must be card or evidence.')
    with connect(data_root) as db:
        db.execute('BEGIN')
        binding = fingerprint([query,scope,detail,retrieval_revision(db)])
        offset = page_offset(body.get('cursor'),binding)
        candidates = search_candidates_page(db, query, limit=limit, scope=scope, offset=offset)
        cards = {card['id']:card for card in node_cards(db,[item['id'] for item in candidates])}
        items = []
        for candidate in candidates:
            card = cards[candidate['id']]
            card.update(relevance=candidate['relevance'],match_sources=candidate['match_sources'],reason=selection_reason(candidate,scope))
            items.append(card)
        if detail == 'evidence':
            from context_payloads import agent_compact_memory_item, MEMORY_CONTEXT_COMPACTION_LEVELS
            from retrieval_projections import compact_projections
            from retrieval import memory_node_result, source_chunk_matches_by_node
            projections = compact_projections(db,[item['id'] for item in items],data_root=data_root)
            matches = source_chunk_matches_by_node(db,data_root,query,node_ids=[item['id'] for item in items],limit=limit+1)
            evidence_items = []
            for item in items:
                evidence = memory_node_result(db,data_root,{**item,'source_chunk_matches':matches.get(item['id'],[])},
                    compact=True,projection=projections[item['id']],relevance=item['relevance'],reason=item['reason'],match_sources=item['match_sources'])
                for options in MEMORY_CONTEXT_COMPACTION_LEVELS:
                    compact = {**item, **agent_compact_memory_item(evidence, options=options)}
                    if byte_count(compact) <= budget-500:
                        break
                evidence_items.append(compact)
            items = evidence_items
        return bounded_page(items,key='results',base={'query':query[:420],'snapshot_id':binding,'detail':detail},
                            limit=limit,offset=offset,binding=binding,max_bytes=budget)


def selection_reason(candidate: dict, scope: dict | None) -> str:
    if 'identity' in candidate['match_sources']:
        return 'Matches a stable identity or alias'
    if scope and scope.get('project_id'):
        return 'Matches the selected project and query'
    if scope and scope.get('person_id'):
        return 'Matches the selected person and query'
    if 'source_chunk' in candidate['match_sources']:
        return 'Matches a current source passage'
    return 'Matches the query' if candidate['match_sources'] != ['node'] else 'Matches the node text'
