import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d";
import { useGraphVisibility } from "../hooks/useGraphVisibility";
import { ambientForce, reconcileForceData, type MemoryForceCard, type MemoryForceData, type MemoryForceEdge, type MemoryForceLink } from "../lib/forceGraphData";
import type { GraphEdge, GraphNode } from "../types";
import { createNodePainter, graphHighlight, highlightedLink, linkColor, paintNodeHitArea } from "./graphPaint";

export type GraphControls = { fit: () => void; zoom: (factor: number) => void };
export type ForceGraphSceneProps = {
  nodes: GraphNode[]; edges: GraphEdge[]; selectedId: string | null; edgeId: string | null;
  motion: boolean | null; onSelect: (id: string | null) => void; onEdge: (edge: GraphEdge | null) => void;
  onReady: (controls: GraphControls | null) => void;
};

export default function ForceGraphScene({ nodes, edges, selectedId, edgeId, motion, onSelect, onEdge, onReady }: ForceGraphSceneProps) {
  const container = useRef<HTMLDivElement>(null);
  const engine = useRef<ForceGraphMethods<MemoryForceCard, MemoryForceEdge> | undefined>(undefined);
  const previous = useRef<MemoryForceData>({ nodes: [], links: [] });
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const { visible, reducedMotion } = useGraphVisibility(container);
  const moving = motion ?? !reducedMotion;
  const fitted = useRef(false);
  const focused = useRef<string | null>(null);
  const data = useMemo(() => {
    const retained = new Set(previous.current.nodes.map((node) => node.id));
    if (!nodes.some((node) => retained.has(node.id))) { fitted.current = false; focused.current = null; }
    previous.current = reconcileForceData(previous.current, nodes, edges);
    return previous.current;
  }, [nodes, edges]);
  const state = useMemo(() => graphHighlight(data, selectedId, hoveredId, edgeId), [data, selectedId, hoveredId, edgeId]);
  const painter = useMemo(createNodePainter, []);
  const duration = reducedMotion && motion !== true ? 0 : 650;

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setSize({ width: Math.round(entry.contentRect.width), height: Math.round(entry.contentRect.height) }));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const fit = useCallback(() => {
    const graph = engine.current;
    if (!graph || !data.nodes.length) return;
    const box = graph.getGraphBbox();
    if (!box) return;
    const padding = size.width < 760 ? 60 : 100;
    const zoom = Math.min(1.45, (size.width - 2 * padding) / Math.max(1, box.x[1] - box.x[0]), (size.height - 2 * padding) / Math.max(1, box.y[1] - box.y[0]));
    graph.centerAt((box.x[0] + box.x[1]) / 2, (box.y[0] + box.y[1]) / 2, duration);
    graph.zoom(Math.max(.25, zoom), duration);
  }, [data, size, duration]);

  useEffect(() => {
    const graph = engine.current;
    if (!graph || !size.width || !size.height) return;
    graph.d3Force("charge")?.strength(-450).distanceMax(450);
    graph.d3Force("link")?.distance(145).strength(.28);
    graph.d3Force("ambient", ambientForce());
    onReady({ fit, zoom: (factor) => graph.zoom(Math.max(.25, Math.min(3, graph.zoom() * factor)), duration) });
    return () => onReady(null);
  }, [data, size, fit, duration, onReady]);

  useEffect(() => {
    if (visible) engine.current?.resumeAnimation(); else engine.current?.pauseAnimation();
    return () => { engine.current?.pauseAnimation(); };
  }, [visible, size.width > 0]);

  useEffect(() => {
    if (moving) engine.current?.d3ReheatSimulation();
  }, [moving, size.width > 0]);

  useEffect(() => {
    if (!data.nodes.length) { fitted.current = false; focused.current = null; return; }
    if (!engine.current || !size.width) return;
    if (!fitted.current && !selectedId) {
      const timer = window.setTimeout(() => {
        fit();
        if (size.width < 760) {
          const degrees = new Map<string, number>();
          data.links.forEach((link) => [link.edge.source, link.edge.target].forEach((id) => degrees.set(id, (degrees.get(id) || 0) + 1)));
          const seed = data.nodes.reduce((best, node) => (degrees.get(node.id) || 0) > (degrees.get(best.id) || 0) ? node : best);
          engine.current?.centerAt(seed.x || 0, seed.y || 0, duration);
          engine.current?.zoom(.85, duration);
        }
        fitted.current = true;
      }, moving ? 900 : 0);
      return () => window.clearTimeout(timer);
    }
  }, [data, size, fit, selectedId, moving, duration]);

  useEffect(() => {
    if (!selectedId) { focused.current = null; return; }
    const graph = engine.current, node = data.nodes.find((item) => item.id === selectedId);
    const focusKey = `${selectedId}:${size.width}:${size.height}`;
    if (!graph || !node || !size.width || focused.current === focusKey) return;
    focused.current = focusKey;
    fitted.current = true;
    const zoom = Math.max(.9, Math.min(1.5, graph.zoom()));
    // Leave room for the desktop inspector or the mobile bottom sheet.
    const offsetX = size.width >= 760 ? Math.min(230, size.width * .23) : 0;
    const offsetY = size.width < 760 ? -size.height * .27 : 0;
    graph.centerAt((node.x || 0) - offsetX / zoom, (node.y || 0) - offsetY / zoom, duration);
    graph.zoom(zoom, duration);
  }, [selectedId, data, size, duration]);

  const paint = useCallback((node: MemoryForceData["nodes"][number], ctx: CanvasRenderingContext2D, scale: number) => painter(node, ctx, scale, state), [painter, state]);
  const color = useCallback((link: MemoryForceLink) => linkColor(link, state), [state]);
  const particles = useCallback((link: MemoryForceLink) => moving && highlightedLink(link, state) ? 2 : 0, [moving, state]);
  return <div ref={container} className="memory-graph-engine" aria-hidden="true">
    {size.width > 0 && size.height > 0 && <ForceGraph2D<MemoryForceCard, MemoryForceEdge>
      ref={engine} width={size.width} height={size.height} graphData={data} backgroundColor="transparent"
      nodeRelSize={18} nodeVal={1} nodeLabel="" nodeCanvasObject={paint} nodePointerAreaPaint={paintNodeHitArea}
      linkLabel="" linkColor={color} linkCurvature="curvature" linkWidth={(link) => highlightedLink(link, state) ? 1.8 : 1}
      linkLineDash={(link) => link.edge.kind === "contradicts" ? [5, 4] : null}
      linkDirectionalArrowLength={5} linkDirectionalArrowRelPos={1} linkDirectionalArrowColor={color}
      linkDirectionalParticles={particles} linkDirectionalParticleWidth={2.2} linkDirectionalParticleSpeed={.0035} linkDirectionalParticleColor={color}
      minZoom={.25} maxZoom={3} autoPauseRedraw d3AlphaDecay={.022} d3VelocityDecay={.32} d3AlphaMin={0}
      cooldownTicks={moving && data.nodes.length ? Infinity : 0} cooldownTime={moving && data.nodes.length ? Infinity : 0} warmupTicks={reducedMotion && !moving ? 120 : 0}
      onNodeClick={(node) => { onEdge(null); onSelect(node.id); }}
      onNodeHover={(node) => setHoveredId(node?.id || null)}
      onNodeDragEnd={() => engine.current?.d3ReheatSimulation()}
      onLinkClick={(link) => onEdge(link.edge)} onBackgroundClick={() => { onEdge(null); onSelect(null); }}
      linkHoverPrecision={7} />}
  </div>;
}
