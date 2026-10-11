"""Read helpers for compiled Memory wiki data."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from database import connect, ensure_schema, normalize_limit, row_payload
from lint import computed_page_freshness, lint_findings_for_node, source_state_for_page
from storage_reference_payloads import storage_reference_for_citation, storage_references_for_node


def wiki_query(data_root: Path, query: str, *, limit: int = 10, scope: dict | None = None,
               cursor: object = None, max_bytes: object = None) -> dict[str, Any]:
    from retrieval_pages import bounded_page, fingerprint, page_offset, response_budget, retrieval_revision
    from search_candidates import ranked_candidates
    from retrieval_projections import compact_projections
    ensure_schema(data_root)
    limit = normalize_limit(limit,default=10,minimum=1,maximum=50)
    with connect(data_root) as db:
        db.execute('BEGIN')
        binding = fingerprint([query,scope,retrieval_revision(db),'wiki'])
        offset = page_offset(cursor,binding)
        candidates = ranked_candidates(db,query,limit=limit+1,scope=scope,offset=offset,channels=['wiki_page','claim'])
        ids = [candidate['id'] for candidate in candidates]
        projections = compact_projections(db,ids,data_root=data_root)
        marks = ','.join('?' for _ in ids)
        pages = {row['node_id']:dict(row) for row in db.execute(f"""SELECT wp.id,wp.node_id,substr(wp.title,1,240) AS title,
            substr(wp.summary,1,360) AS summary,wp.compiled_at,n.type AS node_type
            FROM wiki_pages wp JOIN nodes n ON n.id=wp.node_id WHERE wp.node_id IN ({marks}) AND wp.status='active'""",ids)} if ids else {}
        results = []
        for candidate in candidates:
            page = pages[candidate['id']]
            projection = projections[page['node_id']]
            results.append({**page,'kind':'wiki_page','wiki_page_id':page['id'],
                'freshness':projection['compiled'].get('freshness','unknown'),'compiled':projection['compiled'],
                'storage_references':projection['storage_references'],'match_sources':candidate['match_sources'],
                'relevance':candidate['relevance'],'reason':'Matches compiled wiki or claims'})
        return bounded_page(results,key='results',base={'query':query[:420],'snapshot_id':binding},
            limit=limit,offset=offset,binding=binding,max_bytes=response_budget(max_bytes))


def compiled_payload_for_node(
    db: sqlite3.Connection,
    node_id: str,
    *,
    data_root: Path | None = None,
    include_removed_refs: bool = False,
) -> dict[str, Any]:
    page = row_payload(db.execute("SELECT * FROM wiki_pages WHERE node_id = ? AND status = 'active'", (node_id,)).fetchone())
    sources = [row_payload(row) or {} for row in db.execute("""SELECT s.* FROM node_source_links nl
        JOIN sources s ON s.id = nl.source_id WHERE nl.node_id = ? AND s.status = 'active' ORDER BY s.updated_at DESC""", (node_id,))]
    if page is None:
        return {"compiled_page": None, "claims": [], "citations": [], "sources": sources,
                "lint_findings": lint_findings_for_node(db, node_id)}
    page["freshness"] = computed_page_freshness(db, page, data_root=data_root)
    claims = _claims_with_citations(db, page["id"])
    page["verification"] = "conflict" if any(claim.get("contradictions") for claim in claims) else "verified" if claims and all(claim["citations"] for claim in claims) else "unverified"
    page["compilation_state"] = page["freshness"]
    page["source_state"] = source_state_for_page(db, page, data_root=data_root)
    citations = [citation for claim in claims for citation in claim.get("citations", [])]
    return {
        "compiled_page": page,
        "claims": claims,
        "citations": citations,
        "sources": sources,
        "storage_references": storage_references_for_node(db, node_id, include_removed=include_removed_refs),
        "lint_findings": lint_findings_for_node(db, node_id),
    }


def compact_compiled_payload(
    db: sqlite3.Connection,
    node_id: str,
    *,
    data_root: Path | None = None,
    bounded: bool = False,
) -> dict[str, Any] | None:
    if bounded:
        return bounded_compiled_payload(db, node_id, data_root=data_root)
    payload = compiled_payload_for_node(db, node_id, data_root=data_root)
    page = payload.get("compiled_page")
    if not page:
        return None
    return {
        "wiki_page_id": page["id"],
        "summary": page["summary"],
        "body_markdown": page["body_markdown"],
        "freshness": page["freshness"],
        "compiled_at": page["compiled_at"],
        "verification": page.get("verification", "unverified"),
        "compilation_state": page["compilation_state"],
        "source_state": page["source_state"],
        "claims": payload["claims"],
        "citations": payload["citations"],
        "storage_references": payload["storage_references"],
        "lint_findings": payload["lint_findings"],
    }


def _claims_with_citations(db: sqlite3.Connection, page_id: str) -> list[dict[str, Any]]:
    claims = []
    for row in db.execute("SELECT * FROM claims WHERE wiki_page_id = ? AND status = 'active' ORDER BY created_at", (page_id,)):
        claim = row_payload(row) or {}
        claim["citations"] = _citations_for_claim(db, claim["id"])
        claim["contradictions"] = _citations_for_claim(db, claim["id"], relation="contradicts")
        claim["related_evidence"] = _citations_for_claim(db, claim["id"], relation="related")
        claim["verification"] = "conflict" if claim["contradictions"] else "verified" if claim["citations"] else "unverified"
        claims.append(claim)
    return claims


def _citations_for_claim(db: sqlite3.Connection, claim_id: str, *, relation: str = "supports") -> list[dict[str, Any]]:
    citations = []
    for row in db.execute("SELECT ct.* FROM citations ct JOIN sources s ON s.id = ct.source_id WHERE ct.claim_id = ? AND ct.evidence_relation = ? AND s.status = 'active' AND s.current_version_id = ct.source_version_id ORDER BY ct.created_at", (claim_id, relation)):
        citation = row_payload(row) or {}
        metadata = citation.get("metadata") if isinstance(citation.get("metadata"), dict) else {}
        citation["source_version"] = str(metadata.get("source_version") or "")
        storage_reference = storage_reference_for_citation(db, citation)
        if storage_reference:
            citation["storage_reference"] = storage_reference
        citations.append(citation)
    return citations


def bounded_compiled_payload(db: sqlite3.Connection, node_id: str, *, data_root: Path | None) -> dict[str, Any] | None:
    if data_root is None:
        return None
    from retrieval_projections import compact_projections
    return compact_projections(db, [node_id], data_root=data_root).get(node_id, {}).get("compiled") or None
