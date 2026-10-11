import { useCallback, useEffect, useRef, useState, type ComponentType } from "react";
import { ArrowDownRight, List, Maximize, Pause, Play, Plus, Minus, X } from "lucide-react";
import type { GraphEdge, GraphNode, NodeDetails, RelationshipRow } from "../types";
import { useReducedMotion } from "../hooks/useGraphVisibility";
import type { ForceGraphSceneProps, GraphControls } from "./ForceGraphScene";
import { FloatingNodePanel } from "./FloatingNodePanel";
import { MemoryMapSkeleton } from "./MemoryMapSkeleton";
import { NodeTypeIcon } from "./nodeIcons";

type GraphCanvasProps = {
  nodes: GraphNode[]; edges: GraphEdge[];
  selectedId: string | null; selectedNode: GraphNode | null; selectedDetails: NodeDetails | null;
  loading: boolean; relationships: RelationshipRow[];
  connectionsMore?: boolean; connectionsLoading?: boolean;
  onMoreConnections?: () => void; onBack?: () => void;
  onSelectNode: (id: string | null) => void;
};

export function GraphCanvas(props: GraphCanvasProps) {
  const nodeList = useRef<HTMLDetailsElement>(null);
  const [Scene, setScene] = useState<ComponentType<ForceGraphSceneProps> | null>(null);
  const [controls, setControls] = useState<GraphControls | null>(null);
  const [motion, setMotion] = useState<boolean | null>(null);
  const reducedMotion = useReducedMotion();
  const moving = motion ?? !reducedMotion;
  const [error, setError] = useState("");
  const [edgeId, setEdgeId] = useState<string | null>(null);
  const selectedEdge = props.edges.find((edge) => edge.id === edgeId) || null;
  const onReady = useCallback((next: GraphControls | null) => setControls(next), []);
  const onEdge = useCallback((edge: GraphEdge | null) => setEdgeId(edge?.id || null), []);

  useEffect(() => {
    let cancelled = false;
    void import("./ForceGraphScene").then((module) => {
      if (!cancelled) setScene(() => module.default);
    }).catch(() => { if (!cancelled) setError("Unable to load the map. You can still open memories from the list."); });
    return () => { cancelled = true; };
  }, []);

  function selectFromList(id: string) {
    setEdgeId(null); props.onSelectNode(id);
    if (nodeList.current) { nodeList.current.open = false; nodeList.current.querySelector("summary")?.focus(); }
  }

  return <section className="graph-stage" aria-label="Memory graph" aria-busy={props.loading}>
    {Scene && <Scene nodes={props.nodes} edges={props.edges} selectedId={props.selectedId} edgeId={edgeId}
      motion={motion} onSelect={props.onSelectNode} onEdge={onEdge} onReady={onReady} />}
    {error && <p className="graph-error" role="alert">{error}</p>}
    {(!props.nodes.length || !Scene) && <MemoryMapSkeleton loading={props.loading || !Scene} />}
    <div className="graph-navigation">
      <div className="graph-tools" aria-label="Map controls">
        <button type="button" title="Fit graph" aria-label="Fit graph" disabled={!controls} onClick={() => controls?.fit()}><Maximize size={17} /></button>
        <button type="button" title="Zoom in" aria-label="Zoom in" disabled={!controls} onClick={() => controls?.zoom(1.3)}><Plus size={17} /></button>
        <button type="button" title="Zoom out" aria-label="Zoom out" disabled={!controls} onClick={() => controls?.zoom(1 / 1.3)}><Minus size={17} /></button>
        <span className="graph-tools-divider" />
        <button type="button" title={moving ? "Pause motion" : "Resume motion"} aria-label={moving ? "Pause motion" : "Resume motion"}
          aria-pressed={moving} onClick={() => setMotion(!moving)}>{moving ? <Pause size={16} /> : <Play size={16} />}</button>
      </div>
      <details ref={nodeList} className="graph-memory-list"><summary><List size={15} /><span>Memories</span><span className="graph-count">{props.nodes.length}</span></summary>
        <div className="graph-node-list">{props.nodes.map((node) => <button type="button" key={node.id}
          aria-current={node.id === props.selectedId ? "page" : undefined} onClick={() => selectFromList(node.id)}>
          <NodeTypeIcon type={node.type} size={16} /><span>{node.title}</span></button>)}</div>
        {!props.nodes.length && <p className="muted">No matching memories.</p>}
      </details>
    </div>
    <div className="graph-caption" aria-hidden="true"><span className="graph-caption-dot" /><span>{props.nodes.length} memories · {props.edges.length} connections</span><span className="graph-gesture-hint">Drag to explore · Scroll to zoom</span></div>
    {selectedEdge && <aside className="graph-edge-panel" aria-label="Selected connection">
      <div className="graph-edge-heading"><span><ArrowDownRight size={16} />{selectedEdge.kind.replaceAll("_", " ")}</span>
        <button type="button" className="icon-button" aria-label="Close connection" onClick={() => setEdgeId(null)}><X size={15} /></button></div>
      <p className="graph-edge-route">{props.nodes.find((node) => node.id === selectedEdge.source)?.title} → {props.nodes.find((node) => node.id === selectedEdge.target)?.title}</p>
      <p>{selectedEdge.reason || "No reason recorded."}</p>
      <div className="memory-actions"><button type="button" onClick={() => props.onSelectNode(selectedEdge.source)}>Open origin</button>
        <button type="button" onClick={() => props.onSelectNode(selectedEdge.target)}>Follow connection</button></div>
    </aside>}
    <FloatingNodePanel node={props.selectedDetails || props.selectedNode} relationships={props.relationships}
      connectionsMore={props.connectionsMore} connectionsLoading={props.connectionsLoading} onMoreConnections={props.onMoreConnections}
      onBack={props.onBack} onClose={() => props.onSelectNode(null)} onSelect={(id) => props.onSelectNode(id)} />
  </section>;
}
