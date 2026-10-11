"""Paginated graph traversal without node bodies, source passages or history."""

from pathlib import Path

from database import connect, ensure_schema, normalize_limit
from errors import MemoryValidationError
from models import EDGE_KINDS
from retrieval_cards import node_cards
from retrieval_pages import byte_count, fingerprint, page_cursor, page_offset, response_budget, retrieval_revision
from search_candidates import scope_sql


def explore(data_root: Path, body: dict, *, scope: dict | None = None) -> dict:
    ensure_schema(data_root)
    seeds = body.get('node_ids')
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= 5 or any(not isinstance(value, str) or not value.strip() for value in seeds):
        raise MemoryValidationError('node_ids must contain one to five node ids.')
    seeds = list(dict.fromkeys(value.strip() for value in seeds))
    direction = body.get('direction', 'both')
    if direction not in ('incoming', 'outgoing', 'both'):
        raise MemoryValidationError('direction must be incoming, outgoing or both.')
    kinds = body.get('kinds')
    if kinds is not None and (not isinstance(kinds, list) or not kinds or any(not isinstance(kind,str) or kind not in EDGE_KINDS for kind in kinds)):
        raise MemoryValidationError('kinds must be a nonempty list of supported edge kinds.')
    kinds = sorted(set(kinds or EDGE_KINDS))
    depth = normalize_limit(body.get('depth'), default=1, minimum=1, maximum=2, field_name='depth')
    limit = normalize_limit(body.get('limit'), default=20, minimum=1, maximum=100)
    budget = response_budget(body.get('max_bytes'))
    with connect(data_root) as db:
        db.execute('BEGIN')
        snapshot = retrieval_revision(db)
        binding = fingerprint([seeds, direction, kinds, depth, scope, snapshot])
        offset = page_offset(body.get('cursor'), binding)
        rows = traversal_edges(db, seeds, direction=direction, kinds=kinds, depth=depth,
                               scope=scope, limit=limit + 1, offset=offset)
        card_ids = list(dict.fromkeys(seeds + [value for row in rows for value in (row['source'], row['target'])]))
        cards = {card['id']: card for card in node_cards(db, card_ids)}
        scope_clause, values = scope_sql(scope, alias='n')
        marks = ','.join('?' for _ in seeds)
        eligible = {row['id'] for row in db.execute(f"SELECT n.id FROM nodes n WHERE n.id IN ({marks}) AND n.status='active' {scope_clause}", (*seeds, *values))}
        cards = {node_id: card for node_id, card in cards.items() if node_id not in seeds or node_id in eligible}
        selected = rows[:limit]
        while True:
            ids = list(dict.fromkeys([node_id for node_id in seeds if node_id in eligible] + [value for row in selected for value in (row['source'], row['target'])]))
            has_more = len(rows) > len(selected)
            payload = {'node_ids': seeds, 'direction': direction, 'depth': depth, 'snapshot_id': binding,
                       'nodes': [cards[node_id] for node_id in ids], 'edges': selected,
                       'visited_node_ids': ids, 'unavailable_node_ids': [value for value in seeds if value not in eligible],
                       'has_more': has_more, 'next_cursor': page_cursor(offset + len(selected), binding) if has_more else None,
                       'omitted_for_budget': min(limit, len(rows)) - len(selected),
                       'stop_reason': 'budget' if len(selected) < min(limit, len(rows)) else 'limit' if has_more else 'end',
                       'max_bytes': budget, 'details_tool': 'memory_get_nodes'}
            if byte_count(payload) <= budget:
                return payload
            if len(selected) <= 1:
                raise MemoryValidationError('max_bytes is too small for the seeds and one connection; increase the budget.')
            selected.pop()


def traversal_edges(db, seeds: list[str], *, direction: str, kinds: list[str], depth: int,
                    scope: dict | None, limit: int, offset: int = 0) -> list[dict]:
    scope_clause, scope_values = scope_sql(scope, alias='n')
    marks, kind_marks = ','.join('?' for _ in seeds), ','.join('?' for _ in kinds)
    join = 'e.source_node_id=v.id' if direction == 'outgoing' else 'e.target_node_id=v.id' if direction == 'incoming' else '(e.source_node_id=v.id OR e.target_node_id=v.id)'
    eligible_edge = 'ds.hop < ?' if direction == 'outgoing' else 'dt.hop < ?' if direction == 'incoming' else '(ds.hop < ? OR dt.hop < ?)'
    edge_hop = 'ds.hop+1' if direction == 'outgoing' else 'dt.hop+1' if direction == 'incoming' else 'min(COALESCE(ds.hop,99),COALESCE(dt.hop,99))+1'
    depth_values = [depth, depth] if direction == 'both' else [depth]
    # UNION visits each (node,hop) once within the explicit depth bound.
    # MIN(hop) supplies shortest distances; edges retain their own identities.
    rows = db.execute(f"""WITH RECURSIVE eligible AS (
        SELECT n.id FROM nodes n WHERE n.status='active' {scope_clause}
      ), connections AS (
        SELECT e.* FROM edges e JOIN eligible s ON s.id=e.source_node_id
        JOIN eligible t ON t.id=e.target_node_id WHERE e.status='active' AND e.kind IN ({kind_marks})
      ), visits(id,hop) AS (
        SELECT id,0 FROM eligible WHERE id IN ({marks})
        UNION SELECT CASE WHEN e.source_node_id=v.id THEN e.target_node_id ELSE e.source_node_id END, v.hop+1
        FROM visits v JOIN connections e ON {join} WHERE v.hop < ?
      ), distances AS (SELECT id,min(hop) AS hop FROM visits GROUP BY id)
      SELECT e.id,e.source_node_id AS source,e.target_node_id AS target,e.kind,e.weight,e.confidence,
        substr(e.reason,1,220) AS reason,
        COALESCE(json_extract(e.metadata_json,'$.confidence_basis'),'unspecified') AS confidence_basis,
        {edge_hop} AS hop,
        e.updated_at AS revision
      FROM connections e LEFT JOIN distances ds ON ds.id=e.source_node_id
      LEFT JOIN distances dt ON dt.id=e.target_node_id WHERE {eligible_edge}
      ORDER BY hop, CASE e.kind WHEN 'contradicts' THEN 0 WHEN 'supersedes' THEN 1 ELSE 2 END,
        e.weight*e.confidence DESC,e.id LIMIT ? OFFSET ?""",
      (*scope_values, *kinds, *seeds, depth, *depth_values, limit, offset))
    return [dict(row) for row in rows]
