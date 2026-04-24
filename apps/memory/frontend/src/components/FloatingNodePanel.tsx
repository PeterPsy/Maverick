import { confidenceLabel, formatDate, labelForType } from "../format";
import type { GraphNode, NodeDetails, RelationshipRow } from "../types";

type FloatingNodePanelProps = {
  node: GraphNode | NodeDetails | null;
  relationships: RelationshipRow[];
  onClose: () => void;
  onSelect: (id: string) => void;
};

export function FloatingNodePanel({ node, relationships, onClose, onSelect }: FloatingNodePanelProps) {
  if (!node) return null;
  const details = node as NodeDetails;

  return (
    <article className="node-panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">{labelForType(node.type)}</span>
          <h2>{node.title}</h2>
        </div>
        <button type="button" className="icon-button" onClick={onClose} aria-label="Close node panel">
          x
        </button>
      </div>

      <div className="metrics">
        <span><strong>{confidenceLabel(node.confidence)}</strong><small>confidence</small></span>
        <span><strong>{Math.round(Number(node.importance || 0.5) * 100)}%</strong><small>importance</small></span>
        <span><strong>{details.status || "active"}</strong><small>status</small></span>
      </div>

      {(node.summary || node.body_text) && (
        <section>
          <h3>Readable content</h3>
          {node.summary && <p className="summary">{node.summary}</p>}
          {node.body_text && <p className="body-copy">{node.body_text}</p>}
        </section>
      )}

      <section>
        <h3>Timeline</h3>
        <dl className="detail-list">
          <div><dt>Created</dt><dd>{formatDate(node.created_at)}</dd></div>
          <div><dt>Updated</dt><dd>{formatDate(node.updated_at)}</dd></div>
          <div><dt>Node id</dt><dd>{node.id}</dd></div>
        </dl>
      </section>

      <section>
        <h3>Evidence and references</h3>
        <div className="reference-list">
          {(details.external_refs || []).map((ref) => (
            <div className="reference-card" key={ref.id}>
              <strong>{ref.title || ref.workspace_relative_path || ref.entity_id || ref.file_id || ref.ref_kind}</strong>
              <span>{ref.ref_kind} {ref.owning_app_id ? `from ${ref.owning_app_id}` : ""}</span>
              {ref.workspace_relative_path && <code>{ref.workspace_relative_path}</code>}
              {ref.entity_type && <code>{ref.entity_type}:{ref.entity_id}</code>}
            </div>
          ))}
          {!(details.external_refs || []).length && <p className="muted">No external references attached.</p>}
        </div>
      </section>

      <section>
        <h3>Relationships</h3>
        <div className="relationship-list">
          {relationships.map((edge) => (
            <button type="button" key={edge.id || `${edge.source}-${edge.target}-${edge.kind}`} onClick={() => onSelect(edge.otherId)}>
              <span>{edge.direction} / {edge.kind}</span>
              <strong>{edge.other?.title || edge.otherId}</strong>
              {edge.reason && <small>{edge.reason}</small>}
            </button>
          ))}
          {!relationships.length && <p className="muted">No direct relationships in the current graph.</p>}
        </div>
      </section>
    </article>
  );
}
