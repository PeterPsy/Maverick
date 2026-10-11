"""Bounded SQL projections shared by all selected context nodes."""

import sqlite3
from pathlib import Path

from database import row_payload
from lint import computed_page_freshness, source_state_for_page
from storage_reference_payloads import storage_reference_payload


def compact_projections(db: sqlite3.Connection, node_ids: list[str], *, data_root: Path) -> dict[str, dict]:
    if not node_ids:
        return {}
    marks = ",".join("?" for _ in node_ids)
    result = {node_id: {"provenance": [], "storage_references": [], "compiled": {}} for node_id in node_ids}
    refs = [row_payload(row) or {} for row in db.execute(
        f"SELECT * FROM external_refs WHERE node_id IN ({marks}) ORDER BY created_at", node_ids)]
    ref_by_id = {ref["id"]: ref for ref in refs}
    for ref in refs:
        projection = result[ref["node_id"]]
        if len(projection["provenance"]) < 3:
            # Preview bodies are not needed in an agent provenance projection.
            metadata = ref.get("metadata") or {}
            projection["provenance"].append({**ref, "metadata": {key: metadata.get(key) for key in (
                "provider", "connection_id", "drive_file_id", "source_version", "display_path")}})
        reference = storage_reference_payload(ref)
        if reference and len(projection["storage_references"]) < 3:
            projection["storage_references"].append(reference)
    for row in db.execute(f"""SELECT id, node_id, substr(summary,1,320) AS summary,
        freshness, compiled_at, length(body_markdown) AS body_markdown_char_count
        FROM wiki_pages WHERE node_id IN ({marks}) AND status = 'active'""", node_ids):
        page = row_payload(row) or {}
        freshness = computed_page_freshness(db, page, data_root=data_root)
        result[page["node_id"]]["compiled"] = {"wiki_page_id": page["id"], "summary": page["summary"],
            "compiled_at": page["compiled_at"], "freshness": freshness, "compilation_state": freshness,
            "source_state": source_state_for_page(db, page, data_root=data_root), "verification": "unverified",
            "body_markdown_char_count": page["body_markdown_char_count"], "claims": [], "citations": [],
            "lint_findings": [], "storage_references": result[page["node_id"]]["storage_references"]}
    claims_by_id = {}
    for row in db.execute(f"""SELECT * FROM (SELECT id, node_id, status, confidence,
        EXISTS(SELECT 1 FROM citations ct JOIN sources s ON s.id = ct.source_id WHERE ct.claim_id = claims.id
            AND ct.evidence_relation = 'contradicts' AND s.status = 'active' AND s.current_version_id = ct.source_version_id) AS has_conflict,
        substr(claim_text,1,260) AS claim_text, row_number() OVER(PARTITION BY node_id ORDER BY created_at) AS position
        FROM claims WHERE node_id IN ({marks}) AND status = 'active') WHERE position <= 3""", node_ids):
        claim = dict(row)
        claim.update(citations=[], verification="conflict" if claim.pop("has_conflict") else "unverified")
        claims_by_id[claim["id"]] = claim
        compiled = result[claim["node_id"]]["compiled"]
        if compiled:
            compiled["claims"].append(claim)
    sources = {row["id"]: row_payload(row) or {} for row in db.execute(f"""SELECT DISTINCT s.*
        FROM sources s JOIN node_source_links nl ON nl.source_id = s.id WHERE nl.node_id IN ({marks})""", node_ids)}
    for row in db.execute(f"""SELECT * FROM (SELECT ct.id, ct.claim_id, cl.node_id, ct.source_id,
        ct.source_version_id, ct.source_chunk_id, ct.external_ref_id, ct.locator, ct.locator_kind,
        ct.char_start, ct.char_end, ct.quote_sha256, substr(ct.quote,1,220) AS quote, ct.metadata_json,
        row_number() OVER(PARTITION BY cl.node_id ORDER BY ct.created_at) AS position
        FROM citations ct JOIN claims cl ON cl.id = ct.claim_id JOIN sources s ON s.id = ct.source_id
        WHERE cl.node_id IN ({marks}) AND cl.status = 'active' AND ct.evidence_relation = 'supports'
          AND s.status = 'active' AND s.current_version_id = ct.source_version_id) WHERE position <= 3""", node_ids):
        citation = row_payload(row) or {}
        citation["evidence_relation"] = "supports"
        citation["source_version"] = citation.get("metadata", {}).get("source_version", "")
        reference = storage_reference_payload(ref_by_id.get(citation["external_ref_id"]) or sources.get(citation["source_id"]) or {})
        if reference:
            citation["storage_reference"] = reference
        compiled = result[citation["node_id"]]["compiled"]
        if compiled:
            compiled["citations"].append(citation)
        claim = claims_by_id.get(citation["claim_id"])
        if claim:
            claim["citations"].append(citation)
            if claim["verification"] != "conflict":
                claim["verification"] = "verified"
    # Aggregate all claims, even those omitted from the compact projection.
    for row in db.execute(f"""SELECT cl.node_id,
        max(EXISTS(SELECT 1 FROM citations ct JOIN sources s ON s.id = ct.source_id WHERE ct.claim_id = cl.id
            AND ct.evidence_relation = 'contradicts' AND s.status = 'active' AND s.current_version_id = ct.source_version_id)) AS conflict,
        max(NOT EXISTS(SELECT 1 FROM citations ct JOIN sources s ON s.id = ct.source_id
          WHERE ct.claim_id = cl.id AND ct.evidence_relation = 'supports' AND s.status = 'active' AND s.current_version_id = ct.source_version_id)) AS unverified
        FROM claims cl WHERE cl.node_id IN ({marks}) AND cl.status = 'active' GROUP BY cl.node_id""", node_ids):
        compiled = result[row["node_id"]]["compiled"]
        if compiled:
            compiled["verification"] = "conflict" if row["conflict"] else "unverified" if row["unverified"] else "verified"
    for row in db.execute(f"""SELECT * FROM (SELECT id, node_id, finding_type, severity, message,
        row_number() OVER(PARTITION BY node_id ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END) AS position
        FROM lint_findings WHERE node_id IN ({marks}) AND status = 'active') WHERE position <= 2""", node_ids):
        compiled = result[row["node_id"]]["compiled"]
        if compiled:
            compiled["lint_findings"].append(dict(row))
    for projection in result.values():
        compiled = projection["compiled"]
        if compiled and compiled["freshness"] != "fresh":
            compiled.update(summary="", claims=[], citations=[], verification="unverified")
    return result
