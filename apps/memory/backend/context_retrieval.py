"""Budgeted context with explicit continuation and reserved critical relations."""

from pathlib import Path

from context_payloads import agent_compact_context_payload
from database import connect, ensure_schema, normalize_limit, record_event
from exploration import traversal_edges
from node_search import search_candidates_page, selection_reason
from retrieval import memory_node_result
from retrieval_cards import node_cards
from retrieval_pages import fingerprint, page_cursor, page_offset, response_budget, retrieval_revision
from retrieval_projections import compact_projections
from source_candidate_validation import validated_source_candidates


def context_payload(data_root: Path, query: str, *, limit: int = 8, record_access_event: bool = False,
                    scope: dict | None = None, cursor: object = None, max_bytes: object = None) -> dict:
    ensure_schema(data_root)
    limit = normalize_limit(limit,default=8,minimum=1,maximum=50)
    budget = response_budget(max_bytes)
    with connect(data_root) as db:
        db.execute('BEGIN')
        binding = fingerprint([query,scope,retrieval_revision(db),'context'])
        offset = page_offset(cursor,binding)
        candidates = search_candidates_page(db,query,limit=limit,scope=scope,offset=offset)
        indexed_direct = candidates[:limit]
        direct, matches = validated_source_candidates(db,data_root,query,indexed_direct,limit=limit)
        direct_ids = [candidate['id'] for candidate in direct]
        critical_groups = [traversal_edges(db,direct_ids,direction='both',kinds=[kind],depth=1,scope=scope,limit=3)
                           for kind in ('contradicts','supersedes')] if direct_ids else []
        # Reserve one of each kind before taking a second of either kind.
        critical_candidates = [group[index] for index in range(3) for group in critical_groups if len(group)>index]
        critical = critical_candidates[:2]
        reserved_ids = list(dict.fromkeys(value for edge in critical for value in (edge['source'],edge['target']) if value not in direct_ids))[:2]
        related = []
        if len(direct)<limit and direct_ids:
            related = traversal_edges(db,direct_ids,direction='both',kinds=['supports','about','depends_on','derived_from','related_to'],depth=1,scope=scope,limit=20)
        related_ids = list(dict.fromkeys(value for edge in related if edge['weight']>=.5 and edge['confidence']>=.5
                         for value in (edge['source'],edge['target']) if value not in direct_ids+reserved_ids))[:max(0,limit-len(direct)-len(reserved_ids))]
        # Two critical neighbors are allowed beyond the textual result limit.
        # They go first so byte compaction cannot discard them behind text hits.
        ids = reserved_ids+direct_ids+related_ids
        cards = node_cards(db,ids)
        projections = compact_projections(db,ids,data_root=data_root)
        by_id = {candidate['id']:candidate for candidate in direct}
        marks = ','.join('?' for _ in ids)
        bodies = {row['id']:row['body'] for row in db.execute(f'SELECT id,substr(body_text,1,520) AS body FROM nodes WHERE id IN ({marks})',ids)} if ids else {}
        items = []
        for card in cards:
            card['body_text'] = bodies.get(card['id'],'')
            candidate = by_id.get(card['id'])
            if candidate:
                reason, channels, relevance = selection_reason(candidate,scope),candidate['match_sources'],candidate['relevance']
            else:
                edge = next(edge for edge in critical+related if card['id'] in (edge['source'],edge['target']))
                reason, channels, relevance = f"{edge['kind']} connection of a selected node: {edge['reason']}",['critical_relation' if card['id'] in reserved_ids else 'related_node'],edge['weight']*edge['confidence']
            card['source_chunk_matches'] = matches.get(card['id'],[])
            item = memory_node_result(db,data_root,card,compact=True,projection=projections[card['id']],reason=reason,match_sources=channels,relevance=relevance)
            item.update(revision=card['revision'],compilation_state=card['compilation_state'],details_available=card['details_available'])
            items.append(item)
        search_more = len(candidates)>limit
        payload = agent_compact_context_payload(query,items,requested_limit=limit,max_bytes=budget,
            retrieval_metadata={'retrieval_has_more':search_more,'search_next_cursor':page_cursor(offset+len(indexed_direct),binding) if search_more else None,
                                'total_candidate_count':len(direct) if not search_more and offset == 0 else None,
                                'candidate_count_is_exact':not search_more and offset == 0,'snapshot_id':binding,
                                'critical_edges':critical,'critical_has_more':len(critical_candidates)>2,
                                'retrieved_candidate_count':len(items),'scope':scope or {},
                                'view':{'node_ids':ids,'snapshot_id':binding}})
        # Budget omissions are recoverable by cards, independently of search.
        payload['view']['node_ids'] = [item['node_id'] for item in payload['items']]
        if record_access_event:
            record_event(db,event_type='retrieval_context_generated',payload={'query':query,'item_count':len(payload['items'])})
            db.commit()
        return payload
