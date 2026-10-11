"""Bounded evidence and source sections for the selective inspector."""

from pathlib import Path
import sqlite3

from database import row_payload
from errors import MemoryValidationError
from lint import computed_page_freshness, source_state_for_page
from context_payloads import compact_citations
from storage_reference_payloads import attach_storage_references, storage_reference_payload


def source_items(db: sqlite3.Connection, node_id: str, *, limit: int, offset: int) -> list[dict]:
    rows = db.execute('''WITH items AS (
        SELECT s.id,s.title,s.source_kind,s.external_ref_id,s.current_version_id,s.status,s.updated_at,
          s.owning_app_id,s.entity_type,s.entity_id,s.file_id,s.workspace_relative_path
        FROM node_source_links nl JOIN sources s ON s.id=nl.source_id WHERE nl.node_id=?
        UNION ALL SELECT er.id,er.title,er.ref_kind,er.id,'','reference',er.updated_at,
          er.owning_app_id,er.entity_type,er.entity_id,er.file_id,er.workspace_relative_path
        FROM external_refs er WHERE er.node_id=? AND NOT EXISTS(SELECT 1 FROM sources s WHERE s.external_ref_id=er.id))
        SELECT * FROM items ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?''', (node_id,node_id,limit,offset))
    items = [dict(row) for row in rows]
    ids = [item['external_ref_id'] for item in items if item['external_ref_id']]
    marks = ','.join('?' for _ in ids)
    refs = {row['id']:dict(row) for row in db.execute(f'''SELECT id,ref_kind,owning_app_id,entity_type,entity_id,
        file_id,workspace_relative_path,uri,metadata_json,substr(title,1,240) AS title FROM external_refs WHERE id IN ({marks})''', ids)} if ids else {}
    for item in items:
        ref = row_payload(refs.get(item['external_ref_id'])) if item['external_ref_id'] in refs else None
        item['external_ref'] = ref
        reference = storage_reference_payload(ref or {}) or storage_reference_payload(item)
        if reference:
            item['storage_reference'] = reference
    return items


def evidence_items(db: sqlite3.Connection, data_root: Path, node_id: str, *, limit: int, offset: int,
                   claim_id: str | None = None) -> tuple[list[dict], dict]:
    page = row_payload(db.execute("SELECT id,node_id,freshness,compiled_at,compile_run_id FROM wiki_pages WHERE node_id=? AND status='active'", (node_id,)).fetchone())
    state = {'state_observation':'live', 'freshness':'unknown', 'source_state':'unknown'}
    if page:
        state.update(freshness=computed_page_freshness(db,page,data_root=data_root),
                     source_state=source_state_for_page(db,page,data_root=data_root))
    aggregate = db.execute('''SELECT count(*) AS total,
        max(EXISTS(SELECT 1 FROM citations ct JOIN sources s ON s.id=ct.source_id
            WHERE ct.claim_id=cl.id AND ct.evidence_relation='contradicts'
            AND s.status='active' AND s.current_version_id=ct.source_version_id)) AS conflict,
        max(NOT EXISTS(SELECT 1 FROM citations ct JOIN sources s ON s.id=ct.source_id
            WHERE ct.claim_id=cl.id AND ct.evidence_relation='supports'
            AND s.status='active' AND s.current_version_id=ct.source_version_id)) AS missing_support
        FROM claims cl WHERE cl.node_id=? AND cl.status='active' ''',(node_id,)).fetchone()
    state['verification'] = 'conflict' if aggregate['conflict'] else 'verified' if aggregate['total'] and not aggregate['missing_support'] and state['freshness']=='fresh' else 'unverified'
    # Current passages can be fetched even before the deferred compiler creates
    # claims. These are references, never unchecked body excerpts.
    if offset == 0 and not claim_id:
        rows = list(db.execute('''SELECT sc.id AS chunk_id,sc.source_version_id,s.id AS source_id,
            s.title,sc.locator,sc.locator_kind FROM node_source_links nl
            JOIN sources s ON s.id=nl.source_id AND s.status='active'
            JOIN source_chunks sc ON sc.source_version_id=s.current_version_id
            WHERE nl.node_id=? ORDER BY s.updated_at DESC,sc.chunk_index LIMIT 4''',(node_id,)))
        state['available_source_chunks'] = [dict(row) for row in rows[:3]]
        state['source_chunks_has_more'] = len(rows)>3
    if claim_id:
        if not db.execute('SELECT 1 FROM claims WHERE id=? AND node_id=?',(claim_id,node_id)).fetchone():
            raise MemoryValidationError('claim not found for this node.')
        rows = db.execute('''SELECT ct.* FROM citations ct JOIN sources s ON s.id=ct.source_id
            WHERE ct.claim_id=? AND s.status='active' AND s.current_version_id=ct.source_version_id
            ORDER BY ct.created_at,ct.id LIMIT ? OFFSET ?''',(claim_id,limit,offset))
        return compact_citations(attach_storage_references(db,[row_payload(row) for row in rows]),limit=limit,quote_chars=600), state
    claims = [dict(row) for row in db.execute('''SELECT id,wiki_page_id,node_id,substr(claim_text,1,1000) AS claim_text,
        length(claim_text) AS claim_text_char_count,status,confidence FROM claims WHERE node_id=? AND status='active'
        ORDER BY created_at,id LIMIT ? OFFSET ?''',(node_id,limit,offset))]
    ids = [claim['id'] for claim in claims]
    marks = ','.join('?' for _ in ids)
    rows = db.execute(f'''SELECT * FROM (SELECT ct.*, row_number() OVER
        (PARTITION BY ct.claim_id,ct.evidence_relation ORDER BY ct.created_at,ct.id) AS position,
        count(*) OVER(PARTITION BY ct.claim_id,ct.evidence_relation) AS total
        FROM citations ct JOIN sources s ON s.id=ct.source_id WHERE ct.claim_id IN ({marks})
        AND s.status='active' AND s.current_version_id=ct.source_version_id) WHERE position<=3''',ids) if ids else []
    citations = attach_storage_references(db,[row_payload(row) for row in rows])
    for claim in claims:
        claim['citations_has_more'] = any(item['total']>3 for item in citations if item['claim_id']==claim['id'])
        claim['details_request'] = {'node_id':node_id,'detail':'evidence','claim_id':claim['id']}
        for key,relation in (('citations','supports'),('contradictions','contradicts'),('related_evidence','related')):
            selected = [item for item in citations if item['claim_id']==claim['id'] and item['evidence_relation']==relation]
            claim[key] = compact_citations(selected,limit=3,quote_chars=300)
        claim['verification'] = 'conflict' if claim['contradictions'] else 'verified' if claim['citations'] and state['freshness']=='fresh' else 'unverified'
    return claims,state
