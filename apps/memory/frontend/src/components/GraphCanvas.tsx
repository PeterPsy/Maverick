import { useEffect, useRef, useState } from "react";
import type { Core } from "cytoscape";
import { colors } from "../constants";
import type { GraphEdge, GraphNode, NodeDetails, RelationshipRow } from "../types";
import { FloatingNodePanel } from "./FloatingNodePanel";
import { MemoryMapSkeleton } from "./MemoryMapSkeleton";
import { iconDataUrlForType } from "./nodeIcons";

type GraphCanvasProps = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedId: string | null;
  selectedNode: GraphNode | null;
  selectedDetails: NodeDetails | null;
  loading: boolean;
  relationships: RelationshipRow[];
  connectionsMore?: boolean;
  connectionsLoading?: boolean;
  onMoreConnections?: () => void;
  onBack?: () => void;
  onSelectNode: (id: string | null) => void;
};

export function GraphCanvas(props: GraphCanvasProps) {
  const container = useRef<HTMLDivElement>(null);
  const nodeList = useRef<HTMLDetailsElement>(null);
  const engine = useRef<Core | null>(null);
  const selectRef = useRef(props.onSelectNode);
  const positions = useRef(new Map<string, { x: number; y: number }>());
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);
  selectRef.current = props.onSelectNode;

  useEffect(() => {
    let cancelled = false;
    let observer: ResizeObserver | undefined;
    void import("cytoscape").then(({ default: cytoscape }) => {
      if (cancelled || !container.current) return;
      const cy = cytoscape({ container: container.current, elements: [], minZoom: .2, maxZoom: 3,
        style: [
          { selector: "node", style: { label: "data(title)", "background-color": "#171717", "border-color": "data(color)",
            "border-width": 2, width: 38, height: 38, color: "#ececec", "font-size": 11, "text-valign": "bottom",
            "text-margin-y": 7, "text-max-width": "140px", "text-wrap": "ellipsis",
            "background-image": "data(icon)", "background-width": "55%", "background-height": "55%", "background-fit": "contain" } },
          { selector: "edge", style: { "curve-style": "bezier", "target-arrow-shape": "triangle", "line-color": "#727b85",
            "target-arrow-color": "#727b85", width: 1.5, opacity: .6, "control-point-step-size": 45 } },
          { selector: "edge[kind = 'contradicts']", style: { "line-color": "#ffb3bf", "target-arrow-color": "#ffb3bf", "line-style": "dashed" } },
          { selector: "edge[kind = 'supersedes']", style: { "line-color": "#ffce73", "target-arrow-color": "#ffce73" } },
          { selector: ".active", style: { "border-width": 4, "border-color": "#ffffff" } },
          { selector: "edge:selected", style: { label: "data(kind)", color: "#ececec", "font-size": 11, width: 3, opacity: 1,
            "text-background-color": "#171717", "text-background-opacity": 1, "text-background-padding": "4px" } },
        ], layout: { name: "preset" },
      });
      engine.current = cy;
      cy.on("tap", "node", (event) => selectRef.current(event.target.id()));
      cy.on("tap", "edge", (event) => setSelectedEdge(event.target.data()));
      cy.on("tap", (event) => { if (event.target === cy) setSelectedEdge(null); });
      cy.on("dragfree", "node", (event) => positions.current.set(event.target.id(), event.target.position()));
      observer = new ResizeObserver(() => cy.resize()); observer.observe(container.current);
      setReady(true);
    }).catch((problem) => { if (!cancelled) setError(problem instanceof Error ? problem.message : "Unable to load graph."); });
    return () => { cancelled = true; observer?.disconnect(); engine.current?.destroy(); engine.current = null; };
  }, []);

  useEffect(() => {
    const cy = engine.current;
    if (!cy || !ready) return;
    const ids = new Set([...props.nodes.map((node) => node.id), ...props.edges.map((edge) => edge.id || "")]);
    const first = cy.nodes().length === 0;
    const knownIds = new Set(cy.nodes().map((node) => node.id()));
    let addedNodes = false;
    cy.nodes().forEach((node) => { positions.current.set(node.id(), node.position()); });
    cy.batch(() => {
      cy.elements().filter((item) => !ids.has(item.id())).remove();
      props.nodes.forEach((node, index) => {
        const color = colors[node.type] || "#ccd6dd";
        const data = { id: node.id, title: node.title, color, icon: iconDataUrlForType(node.type, color) };
        const existing = cy.getElementById(node.id);
        if (existing.length) existing.data(data);
        else {
          addedNodes = true;
          const angle = index / Math.max(1, props.nodes.length) * Math.PI * 2;
          const connection = props.edges.find((edge) => edge.source === node.id || edge.target === node.id);
          const otherId = connection?.source === node.id ? connection.target : connection?.source;
          const anchor = otherId ? cy.getElementById(otherId).position() : undefined;
          cy.add({ group: "nodes", data, position: positions.current.get(node.id) || { x: (anchor?.x || 300) + 180 * Math.cos(angle), y: (anchor?.y || 300) + 180 * Math.sin(angle) } });
        }
      });
      props.edges.forEach((edge) => {
        if (!edge.id || !cy.getElementById(edge.source).length || !cy.getElementById(edge.target).length) return;
        const existing = cy.getElementById(edge.id);
        if (existing.length) existing.data(edge);
        else cy.add({ group: "edges", data: edge });
      });
    });
    if (first && props.nodes.length) {
      cy.layout({ name: "cose", animate: false, randomize: false, fit: true, padding: 80,
        nodeDimensionsIncludeLabels: true, nodeRepulsion: () => 20000, componentSpacing: 100, idealEdgeLength: () => 150 }).run();
      if (cy.zoom() > 1.2) { cy.zoom(1.2); cy.center(); }
    } else if (addedNodes) {
      const established = cy.nodes().filter((node) => knownIds.has(node.id()));
      established.lock();
      try {
        cy.layout({ name: "cose", animate: false, randomize: false, fit: false, numIter: 300,
          nodeDimensionsIncludeLabels: true, nodeRepulsion: () => 20000, idealEdgeLength: () => 150 }).run();
      } finally { established.unlock(); }
    }
    setSelectedEdge((current) => current ? props.edges.find((edge) => edge.id === current.id) || null : null);
  }, [ready, props.nodes, props.edges]);

  useEffect(() => {
    const cy = engine.current;
    if (!cy || !ready) return;
    cy.nodes().removeClass("active");
    if (props.selectedId) {
      const node = cy.getElementById(props.selectedId);
      node.addClass("active");
      if (node.length) {
        if (cy.zoom() < .8) cy.zoom(.8);
        cy.center(node);
        if ((container.current?.clientWidth || 0) < 760) cy.panBy({ x: 0, y: -(container.current?.clientHeight || 0) * .28 });
      }
    }
  }, [ready, props.selectedId, props.nodes]);

  return <section className="graph-stage" aria-label="Memory graph" aria-busy={props.loading}>
    <div ref={container} className="memory-graph-engine" aria-hidden="true" />
    {error && <p role="alert">{error}</p>}
    {!props.nodes.length && <MemoryMapSkeleton loading={props.loading || !ready} />}
    <div className="graph-navigation">
      <button type="button" disabled={!ready} onClick={() => { const cy = engine.current; cy?.fit(undefined, 70); if (cy && cy.zoom() > 1.2) { cy.zoom(1.2); cy.center(); } }}>Fit graph</button>
      <details ref={nodeList}><summary>Visible memories ({props.nodes.length})</summary>
        <div className="graph-node-list">{props.nodes.map((node) => <button type="button" key={node.id} aria-current={node.id === props.selectedId ? "page" : undefined} onClick={() => { props.onSelectNode(node.id); if (nodeList.current) { nodeList.current.open = false; nodeList.current.querySelector("summary")?.focus(); } }}>{node.title}</button>)}</div>
        {!props.nodes.length && <p className="muted">No matching memories.</p>}
      </details>
    </div>
    {selectedEdge && <aside className="graph-edge-panel" aria-label="Selected connection">
      <strong>{selectedEdge.kind}</strong><p>{selectedEdge.reason || "No reason recorded."}</p>
      <button type="button" onClick={() => props.onSelectNode(selectedEdge.source)}>Open origin</button>
      <button type="button" onClick={() => props.onSelectNode(selectedEdge.target)}>Follow connection</button>
      <button type="button" onClick={() => setSelectedEdge(null)}>Close connection</button>
    </aside>}
    <FloatingNodePanel node={props.selectedDetails || props.selectedNode} relationships={props.relationships}
      connectionsMore={props.connectionsMore} connectionsLoading={props.connectionsLoading} onMoreConnections={props.onMoreConnections}
      onBack={props.onBack} onClose={() => props.onSelectNode(null)} onSelect={(id) => props.onSelectNode(id)} />
  </section>;
}
