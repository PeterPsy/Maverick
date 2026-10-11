import { useState } from "react";
import { callMemory } from "../memoryApi";
import type { NodeDetails } from "../types";

export function MemoryManagement({ node, onSelect, onClose }: { node: NodeDetails; onSelect: (id: string) => void; onClose: () => void }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(node.title);
  const [body, setBody] = useState(node.body_text || node.summary || "");
  const [personId, setPersonId] = useState(String(node.metadata?.person_id || ""));
  const [projectId, setProjectId] = useState(String(node.metadata?.project_id || ""));
  const [validFrom, setValidFrom] = useState(String(node.metadata?.valid_from || ""));
  const [validUntil, setValidUntil] = useState(String(node.metadata?.valid_until || ""));
  const [mergeQuery, setMergeQuery] = useState("");
  const [targets, setTargets] = useState(node.duplicate_candidates || []);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const excluded = node.status === "excluded";

  async function perform(action: string, values: Record<string, unknown> = {}) {
    setBusy(true);
    try {
      const result = await callMemory<{ node?: NodeDetails }>({ action, node_id: node.id, expected_updated_at: node.updated_at, ...values });
      setError(""); setEditing(false);
      if (action === "delete_node") onClose();
      else onSelect(result.node?.id || node.id);
    } catch (problem) { setError(problem instanceof Error ? problem.message : "Unable to change memory."); }
    finally { setBusy(false); }
  }

  async function findTargets() {
    setBusy(true);
    try {
      const result = await callMemory<{ results: NodeDetails[] }>({ action: "search", query: mergeQuery, limit: 5 });
      setTargets(result.results.filter((target) => target.id !== node.id));
      setError("");
    } catch (problem) { setError(problem instanceof Error ? problem.message : "Unable to find merge targets."); }
    finally { setBusy(false); }
  }

  return <section className="memory-management">
    <h3>Manage memory</h3>
    {error && <p role="alert">{error}</p>}
    <div className="memory-actions">
      <button type="button" disabled={busy || excluded} onClick={() => setEditing(!editing)}>Correct fact</button>
      <button type="button" disabled={busy || excluded} onClick={() => void perform("compile")}>Verify evidence</button>
      <button type="button" disabled={busy} onClick={() => void perform("exclude_node", { excluded: node.status !== "excluded" })}>{node.status === "excluded" ? "Include in retrieval" : "Exclude from retrieval"}</button>
    </div>
    {excluded && <p className="muted">Include this memory in retrieval to correct, verify or merge it.</p>}
    {editing && !excluded && <form onSubmit={(event) => { event.preventDefault(); void perform("update_node", { title, body, summary: body.slice(0, 320), metadata: { person_id: personId, project_id: projectId, valid_from: validFrom, valid_until: validUntil, confirmation: "user_corrected", confidence_basis: "user_confirmed" } }); }}>
      <label>Title<input value={title} onChange={(event) => setTitle(event.target.value)} required /></label>
      <label>Fact<textarea value={body} onChange={(event) => setBody(event.target.value)} required rows={5} /></label>
      <label>Person<input value={personId} onChange={(event) => setPersonId(event.target.value)} /></label>
      <label>Project<input value={projectId} onChange={(event) => setProjectId(event.target.value)} /></label>
      <label>Valid from<input type="date" value={validFrom} onChange={(event) => setValidFrom(event.target.value)} /></label>
      <label>Valid until<input type="date" value={validUntil} onChange={(event) => setValidUntil(event.target.value)} /></label>
      <button type="submit" disabled={busy}>Save correction</button>
    </form>}
    <details>
      <summary>Merge into another memory</summary>
      <p className="muted">The target keeps its fact. Evidence and relationships are transferred; both histories are retained.</p>
      <form onSubmit={(event) => { event.preventDefault(); void findTargets(); }}><label>Find target<input disabled={excluded} value={mergeQuery} onChange={(event) => setMergeQuery(event.target.value)} required /></label><button type="submit" disabled={busy || excluded}>Find</button></form>
      {targets.map((target) => <button type="button" disabled={busy || excluded} key={target.id} onClick={() => void perform("merge_nodes", { target_node_id: target.id, target_updated_at: target.updated_at })}>Merge into {target.title}</button>)}
    </details>
    <details>
      <summary>Remove a source</summary>
      {(node.sources || []).map((source) => <button type="button" disabled={busy} key={source.id} onClick={() => void perform("remove_source", { source_id: source.id })}>Remove {source.title || source.id}</button>)}
      <p className="muted">Removed sources remain available in the audit history.</p>
    </details>
    <button type="button" disabled={busy} onClick={() => confirmDelete ? void perform("delete_node", { reason: "user_removed" }) : setConfirmDelete(true)}>{confirmDelete ? "Confirm removal" : "Remove memory"}</button>
  </section>;
}
