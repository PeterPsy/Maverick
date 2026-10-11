import { useState } from "react";
import { ArrowLeft, X } from "lucide-react";
import { MemoryEvidence } from "./MemoryEvidence";
import { MemoryManagement } from "./MemoryManagement";
import { useNodeSections, type NodeSection } from "../hooks/useNodeSections";
import { confidenceLabel, formatDate, labelForType } from "../format";
import type { GraphNode, NodeDetails, RelationshipRow } from "../types";

type FloatingNodePanelProps = {
  node: GraphNode | NodeDetails | null;
  relationships: RelationshipRow[];
  connectionsMore?: boolean;
  connectionsLoading?: boolean;
  onMoreConnections?: () => void;
  onClose: () => void;
  onSelect: (id: string) => void;
  onBack?: () => void;
};

export function FloatingNodePanel(props: FloatingNodePanelProps) {
  if (!props.node) return null;
  return <NodePanel key={`${props.node.id}:${props.node.updated_at}`} {...props} node={props.node as NodeDetails} />;
}

function NodePanel({ node, relationships, connectionsMore, connectionsLoading, onMoreConnections, onClose, onSelect, onBack }: FloatingNodePanelProps & { node: NodeDetails }) {
  const [section, setSection] = useState<NodeSection>("content");
  const { details, busy, error, cursors, load, contentComplete } = useNodeSections(node, section);
  const labels: Record<NodeSection, string> = { content: "Content", connections: "Connections", sources: "Sources", history: "History" };
  return <article className="node-panel" aria-label="Memory details" aria-busy={busy}>
    <div className="panel-heading">
      <div><span className="eyebrow">{labelForType(node.type)}</span><h2>{node.title}</h2></div>
      <div className="memory-actions">
        {onBack && <button type="button" className="icon-button" onClick={onBack} aria-label="Back to previous memory"><ArrowLeft size={16} /></button>}
        <button type="button" className="icon-button" onClick={onClose} aria-label="Close node panel"><X size={16} /></button>
      </div>
    </div>
    {node.reason && <p className="muted">{node.reason}</p>}
    <div className="metrics">
      <span><strong>{confidenceLabel(node.confidence)}</strong><small>confidence</small></span>
      <span><strong>{details.verification || "unverified"}</strong><small>evidence</small></span>
      <span><strong>{node.status || "active"}</strong><small>status</small></span>
    </div>
    <div className="compiled-card__meta">
      <span>Compilation: {details.compilation_state || "unknown"}</span><span>Source: {details.source_state || "unknown"}</span>
      <span>{String(node.metadata?.confidence_basis || "unspecified").replace(/_/g, " ")}</span>
    </div>
    <nav className="node-panel-tabs" aria-label="Memory sections">
      {(Object.keys(labels) as NodeSection[]).map((value) => <button type="button" key={value} aria-current={section === value ? "page" : undefined} onClick={() => setSection(value)}>{labels[value]}</button>)}
    </nav>
    {error && <p role="alert">{error}<button type="button" onClick={() => void load(section === "sources" ? "evidence" : section)}>Retry</button></p>}
    {busy && <p className="muted" role="status">Loading section…</p>}
    {section === "content" && <>
      <section aria-label="Content">
        {node.summary && <p className="summary">{node.summary}</p>}
        <p className="body-copy">{details.body_text || (!busy ? "No content." : "")}</p>
        {cursors.content && <button type="button" disabled={busy} onClick={() => void load("content", true)}>More content</button>}
      </section>
      <MemoryManagement key={`manage:${contentComplete}`} node={details} contentComplete={contentComplete} onSelect={onSelect} onClose={onClose} />
    </>}
    {section === "connections" && <section>
      <h3>Connections</h3>
      <div className="relationship-list">{relationships.map((edge) => <button type="button" key={edge.id} onClick={() => onSelect(edge.otherId)}>
        <span>{edge.direction} / {edge.kind}</span><strong>{edge.other?.title || edge.otherId}</strong>{edge.reason && <small>{edge.reason}</small>}
      </button>)}</div>
      {!relationships.length && <p className="muted">No direct connections.</p>}
      {connectionsMore && <button type="button" disabled={connectionsLoading} onClick={onMoreConnections}>{connectionsLoading ? "Loading…" : "More connections"}</button>}
    </section>}
    {section === "sources" && <>
      <MemoryEvidence node={details} />
      {cursors.evidence && <button type="button" disabled={busy} onClick={() => void load("evidence", true)}>More evidence</button>}
      {cursors.sources && <button type="button" disabled={busy} onClick={() => void load("sources", true)}>More sources</button>}
      <div className="reference-list">{(details.external_refs || details.sources?.flatMap((source) => source.external_ref ? [source.external_ref] : []) || []).map((ref) => <div className="reference-card" key={ref.id}>
        <strong>{ref.title || ref.workspace_relative_path || ref.entity_id || ref.id}</strong><span>{ref.ref_kind} {ref.owning_app_id}</span>
      </div>)}</div>
    </>}
    {section === "history" && <section>
      <h3>Revision history</h3>
      {(details.revisions || []).map((revision) => <div className="reference-card" key={revision.id}>
        <strong>{formatDate(revision.revision)} · {revision.reason.replace(/_/g, " ")}</strong>
        <RevisionContent nodeId={node.id} revisionId={revision.id} />
      </div>)}
      {!details.revisions?.length && !busy && <p className="muted">No revisions.</p>}
      {cursors.history && <button type="button" disabled={busy} onClick={() => void load("history", true)}>More revisions</button>}
      <dl className="detail-list"><div><dt>Updated</dt><dd>{formatDate(node.updated_at)}</dd></div><div><dt>Node id</dt><dd>{node.id}</dd></div></dl>
    </section>}
  </article>;
}

function RevisionContent({ nodeId, revisionId }: { nodeId: string; revisionId: string }) {
  const [text, setText] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [opened, setOpened] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function read() {
    setBusy(true);
    try {
      const { callMemory } = await import("../memoryApi");
      const result = await callMemory<{ text: string; next_cursor: string | null }>({ action: "inspect", node_id: nodeId, detail: "content", revision_id: revisionId, ...(cursor ? { cursor } : {}) });
      setText((current) => current + result.text); setCursor(result.next_cursor); setOpened(true); setError("");
    } catch (problem) { setError(problem instanceof Error ? problem.message : "Unable to read revision."); }
    finally { setBusy(false); }
  }
  return <>{(!opened || cursor) && <button type="button" disabled={busy} onClick={() => void read()}>{opened ? "More revision content" : "Read revision"}</button>}{error && <p role="alert">{error}</p>}{text && <p className="body-copy">{text}</p>}</>;
}
