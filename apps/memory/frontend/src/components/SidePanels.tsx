import { nodeTypes } from "../constants";
import { labelForType, truncate } from "../format";
import type { GraphNode, ViewFilter } from "../types";

type Draft = {
  title: string;
  body: string;
  type: string;
};

type LeftPanelProps = {
  status: string;
  query: string;
  viewFilter: ViewFilter;
  nodeCount: number;
  edgeCount: number;
  draft: Draft;
  onQueryChange: (query: string) => void;
  onSearch: () => void;
  onClearCustomView: () => void;
  onRefreshGraph: () => void;
  onDraftChange: (draft: Draft) => void;
  onRemember: () => void;
};

export function LeftPanel({
  status,
  query,
  viewFilter,
  nodeCount,
  edgeCount,
  draft,
  onQueryChange,
  onSearch,
  onClearCustomView,
  onRefreshGraph,
  onDraftChange,
  onRemember,
}: LeftPanelProps) {
  return (
    <aside className="left-panel">
      <header className="brand">
        <div>
          <h1>Memory</h1>
          <p>Workspace knowledge graph</p>
        </div>
        <span className="status">{status}</span>
      </header>

      <div className="search-row">
        <input value={query} onChange={(event) => onQueryChange(event.target.value)} onKeyDown={(event) => event.key === "Enter" && onSearch()} placeholder="Search memory" />
        <button type="button" onClick={onSearch}>Search</button>
      </div>

      {viewFilter.mode === "custom" && (
        <div className="custom-view">
          <strong>{viewFilter.title || "Custom Memory view"}</strong>
          <p>Showing {viewFilter.refs.length} curated node{viewFilter.refs.length === 1 ? "" : "s"}.</p>
          <button type="button" className="secondary" onClick={onClearCustomView}>Back to full graph</button>
        </div>
      )}

      <section className="panel-section">
        <h2>Graph</h2>
        <div className="stat-grid">
          <span>{nodeCount}<small>nodes</small></span>
          <span>{edgeCount}<small>links</small></span>
        </div>
        <button type="button" className="secondary" onClick={onRefreshGraph}>Refresh graph</button>
      </section>

      <section className="panel-section">
        <h2>Remember</h2>
        <input value={draft.title} onChange={(event) => onDraftChange({ ...draft, title: event.target.value })} placeholder="Title" />
        <select value={draft.type} onChange={(event) => onDraftChange({ ...draft, type: event.target.value })}>
          {nodeTypes.map((type) => <option key={type} value={type}>{labelForType(type)}</option>)}
        </select>
        <textarea value={draft.body} onChange={(event) => onDraftChange({ ...draft, body: event.target.value })} placeholder="Durable note, fact, decision, or context" />
        <button type="button" onClick={onRemember} disabled={!draft.title.trim()}>Remember</button>
      </section>
    </aside>
  );
}

type RightPanelProps = {
  nodes: GraphNode[];
  selectedId: string | null;
  contextText: string;
  onSelectNode: (id: string) => void;
  onPreviewContext: () => void;
};

export function RightPanel({ nodes, selectedId, contextText, onSelectNode, onPreviewContext }: RightPanelProps) {
  return (
    <aside className="right-panel">
      <section className="panel-section">
        <h2>Matches</h2>
        <div className="node-list">
          {nodes.slice(0, 24).map((node) => (
            <button type="button" key={node.id} className={`node-card ${node.id === selectedId ? "active" : ""}`} onClick={() => onSelectNode(node.id)}>
              <strong>{node.title}</strong>
              <span>{labelForType(node.type)}</span>
              <p>{truncate(node.summary || node.body_text, 120)}</p>
            </button>
          ))}
        </div>
      </section>
      <section className="panel-section">
        <h2>Context preview</h2>
        <button type="button" onClick={onPreviewContext}>Preview agent context</button>
        <pre className="context-preview">{contextText}</pre>
      </section>
    </aside>
  );
}
