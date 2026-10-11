import { useState } from "react";
import { callMemory } from "../memoryApi";
import { formatDate } from "../format";
import type { MemoryCitation, NodeDetails } from "../types";

type SourceInspection = {
  versions: Array<{ id: string; observed_at: string; is_latest: boolean; version_hash: string }>;
  pagination?: { next_version_offset: number | null };
};

export function MemoryEvidence({ node }: { node: NodeDetails }) {
  const [passages, setPassages] = useState<Record<string, string>>({});
  const [histories, setHistories] = useState<Record<string, SourceInspection>>({});
  const [error, setError] = useState("");
  const [loading, setLoading] = useState("");

  async function openPassage(citation: MemoryCitation) {
    if (!citation.source_chunk_id || loading) return;
    setLoading(citation.id);
    try {
      const result = await callMemory<{ chunks: Array<{ body: string }> }>({ action: "fetch_chunks", chunk_ids: [citation.source_chunk_id] });
      setPassages((current) => ({ ...current, [citation.id]: result.chunks[0]?.body || "Passage unavailable." }));
      setError("");
    } catch (problem) { setError(problem instanceof Error ? problem.message : "Unable to read evidence."); }
    finally { setLoading(""); }
  }

  async function openHistory(sourceId: string, offset = 0) {
    setLoading(sourceId);
    try {
      const result = await callMemory<SourceInspection>({ action: "inspect_source", source_id: sourceId, version_offset: offset, version_limit: 10, chunk_limit: 1 });
      setHistories((current) => ({ ...current, [sourceId]: result }));
      setError("");
    } catch (problem) { setError(problem instanceof Error ? problem.message : "Unable to inspect source versions."); }
    finally { setLoading(""); }
  }

  function evidence(citation: MemoryCitation, relation: "supports" | "contradicts" | "related" = "supports") {
    const deepLink = citation.storage_reference?.deep_link;
    return <details key={citation.id} className={relation === "contradicts" ? "lint-card lint-card--error" : "reference-card"}>
      <summary>{relation === "contradicts" ? "Contradicting passage" : relation === "related" ? "Relevant passage · needs review" : "Supporting passage"}</summary>
      <blockquote>{citation.quote}</blockquote>
      <small>Version {citation.source_version_id}</small>
      {deepLink?.startsWith("/app/") && <a href={deepLink} target="_top">Open source in Storage</a>}
      {citation.source_chunk_id && <button type="button" disabled={!!loading} onClick={() => void openPassage(citation)}>{loading === citation.id ? "Loading…" : "Read full passage"}</button>}
      {passages[citation.id] && <p className="body-copy">{passages[citation.id]}</p>}
    </details>;
  }

  return <section>
    <h3>Evidence</h3>
    {error && <p role="alert">{error}</p>}
    <div className="claim-list">{(node.claims || []).map((claim) => <div className="claim-card" key={claim.id}>
      <strong>{claim.claim_text}</strong><small>{claim.verification || "unverified"}</small>
      {(claim.citations || []).map((citation) => evidence(citation))}
      {(claim.contradictions || []).map((citation) => evidence(citation, "contradicts"))}
      {(claim.related_evidence || []).map((citation) => evidence(citation, "related"))}
    </div>)}</div>
    <div className="reference-list">{(node.sources || []).map((source) => <details className="reference-card" key={source.id}>
      <summary>{source.title || source.id}</summary>
      <button type="button" disabled={!!loading} onClick={() => void openHistory(source.id)}>Inspect source versions</button>
      {(histories[source.id]?.versions || []).map((version) => <p key={version.id}><strong>{version.is_latest ? "Current" : "Previous"}</strong> · {formatDate(version.observed_at)}<code>{version.version_hash}</code></p>)}
      {histories[source.id]?.pagination?.next_version_offset != null && <button type="button" disabled={!!loading} onClick={() => void openHistory(source.id, histories[source.id].pagination!.next_version_offset!)}>More versions</button>}
    </details>)}</div>
    {!node.claims?.length && !node.sources?.length && <p className="muted">No source evidence attached.</p>}
  </section>;
}
