"""Small node cards shared by search, graph, batch reads and exploration."""

import sqlite3

from database import row_payload
from retrieval_pages import fingerprint

CARD_FIELDS = """n.id, n.type, substr(n.title,1,240) AS title,
    substr(CASE WHEN n.summary != '' THEN n.summary ELSE n.body_text END,1,360) AS summary,
    length(n.body_text) AS body_text_char_count, n.status, n.importance, n.confidence,
    n.created_at, n.updated_at,
    json_object('knowledge_type', json_extract(n.metadata_json,'$.knowledge_type'),
      'confidence_basis', json_extract(n.metadata_json,'$.confidence_basis'),
      'confirmation', json_extract(n.metadata_json,'$.confirmation'),
      'chat_evidence', json(CASE WHEN json_type(n.metadata_json,'$.chat_evidence')='array' THEN
        (SELECT json_group_array(json_object(
          'session_id',substr(json_extract(value,'$.session_id'),1,256),
          'turn_id',substr(json_extract(value,'$.turn_id'),1,256),
          'role',substr(json_extract(value,'$.role'),1,40)))
          FROM (SELECT value FROM json_each(n.metadata_json,'$.chat_evidence') WHERE type='object' LIMIT 3))
        ELSE 'null' END),
      'person_id', json_extract(n.metadata_json,'$.person_id'),
      'project_id', json_extract(n.metadata_json,'$.project_id'),
      'valid_from', json_extract(n.metadata_json,'$.valid_from'),
      'valid_until', json_extract(n.metadata_json,'$.valid_until')) AS metadata_json"""


def node_cards(db: sqlite3.Connection, node_ids: list[str]) -> list[dict]:
    if not node_ids:
        return []
    marks = ','.join('?' for _ in node_ids)
    nodes = {row['id']: row_payload(row) for row in db.execute(f"SELECT {CARD_FIELDS} FROM nodes n WHERE n.id IN ({marks})", node_ids)}
    states = {row['node_id']: dict(row) for row in db.execute(f"""SELECT node_id, freshness,
        compiled_at, length(body_markdown) AS compiled_char_count FROM wiki_pages
        WHERE node_id IN ({marks}) AND status = 'active'""", node_ids)}
    jobs = {row['node_id']: dict(row) for row in db.execute(f"""SELECT node_id,max(updated_at) AS updated_at,
        CASE WHEN max(status='running') THEN 'running' WHEN max(status='ready') THEN 'pending' ELSE 'failed' END AS status
        FROM ingest_jobs WHERE node_id IN ({marks}) AND job_type='compile_node'
        AND status IN ('ready','running','failed') GROUP BY node_id""", node_ids)}
    evidence = {row['node_id']: dict(row) for row in db.execute(f"""SELECT cl.node_id,
        count(DISTINCT cl.id) AS claim_count,
        count(DISTINCT CASE WHEN ct.evidence_relation='supports' THEN ct.id END) AS support_count,
        count(DISTINCT CASE WHEN ct.evidence_relation='contradicts' THEN ct.id END) AS contradiction_count,
        count(DISTINCT CASE WHEN ct.evidence_relation='supports' THEN cl.id END) AS supported_claim_count
        FROM claims cl LEFT JOIN citations ct ON ct.claim_id=cl.id AND EXISTS
        (SELECT 1 FROM sources s WHERE s.id=ct.source_id AND s.status='active' AND s.current_version_id=ct.source_version_id)
        WHERE cl.node_id IN ({marks}) AND cl.status='active' GROUP BY cl.node_id""", node_ids)}
    source_states = {row['node_id']: dict(row) for row in db.execute(f"""SELECT nl.node_id,
        count(*) AS source_count, max(s.updated_at) AS updated_at,
        max(COALESCE(json_extract(s.metadata_json,'$.stale'),0)
          OR COALESCE(json_extract(s.metadata_json,'$.source_stale'),0)) AS stale_source
        FROM node_source_links nl JOIN sources s ON s.id=nl.source_id AND s.status='active'
        WHERE nl.node_id IN ({marks}) GROUP BY nl.node_id""", node_ids)}
    cards = []
    for node_id in node_ids:
        if node_id not in nodes:
            continue
        node = nodes[node_id]
        page = states.get(node_id, {})
        indicators = evidence.get(node_id, {})
        sources = source_states.get(node_id, {})
        fresh = page.get('freshness', 'unknown')
        if sources.get('stale_source'):
            fresh = 'stale'
        verification = 'unverified'
        if fresh == 'fresh':
            verification = 'conflict' if indicators.get('contradiction_count') else 'verified' if indicators.get('claim_count') and indicators['claim_count'] == indicators['supported_claim_count'] else 'unverified'
        job = jobs.get(node_id, {})
        compilation = job.get('status') if job.get('status') in ('pending','running') or job.get('updated_at','')>page.get('compiled_at','') else fresh
        node.update(node_id=node_id, revision=node['updated_at'],
                    state_revision=fingerprint([node['updated_at'],page,job,indicators,sources]), freshness=fresh,
                    verification=verification, compilation_state=compilation or fresh,
                    source_state='stale' if sources.get('stale_source') else 'current' if sources else 'unknown',
                    evidence={key: indicators.get(key, 0) for key in ('claim_count','support_count','contradiction_count')},
                    details_available=['content','evidence','sources','history'],
                    state_observation='indexed',
                    source_count=sources.get('source_count', 0))
        node['metadata'] = {key: value for key, value in node.get('metadata', {}).items() if value is not None}
        cards.append(node)
    return cards
