import { useCallback, useEffect, useRef } from "react";
import {
  screenToWorld,
  zoomViewportAtPoint,
  type Viewport,
  type ViewportRect,
} from "../lib/graphViewport";
import type { GraphEdge, GraphNode, NodeDetails, RelationshipRow } from "../types";
import { FloatingNodePanel } from "./FloatingNodePanel";
import { drawGraphCanvas } from "./graphCanvasDrawing";
import { applyRepulsion } from "./graphCanvasPhysics";
import { MemoryMapSkeleton } from "./MemoryMapSkeleton";
import { useGraphCanvasGestures, type GraphCanvasDragState } from "./useGraphCanvasGestures";

type CanvasNode = GraphNode & {
  radius: number;
  vx: number;
  vy: number;
  x: number;
  y: number;
};

type GraphCanvasProps = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedId: string | null;
  selectedNode: GraphNode | null;
  selectedDetails: NodeDetails | null;
  loading: boolean;
  relationships: RelationshipRow[];
  onSelectNode: (id: string | null) => void;
};

const DEFAULT_VIEWPORT: Viewport = { scale: 1, offsetX: 0, offsetY: 0 };
const SETTLED_SPEED = 0.035;

export function GraphCanvas({
  nodes,
  edges,
  selectedId,
  selectedNode,
  selectedDetails,
  loading,
  relationships,
  onSelectNode,
}: GraphCanvasProps) {
  const animationRef = useRef<number | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const dragRef = useRef<GraphCanvasDragState | null>(null);
  const edgesRef = useRef<GraphEdge[]>(edges);
  const hoverIdRef = useRef<string | null>(null);
  const nodeByIdRef = useRef<Map<string, CanvasNode>>(new Map());
  const nodesRef = useRef<CanvasNode[]>([]);
  const rectRef = useRef<ViewportRect>({ height: 620, left: 0, top: 0, width: 900 });
  const runningRef = useRef(false);
  const selectedIdRef = useRef<string | null>(selectedId);
  const viewportRef = useRef<Viewport>({ ...DEFAULT_VIEWPORT });

  const updateCanvasRect = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    rectRef.current = { height: rect.height, left: rect.left, top: rect.top, width: rect.width };
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.floor(rect.width * ratio));
    const height = Math.max(1, Math.floor(rect.height * ratio));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
  }, []);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    drawGraphCanvas(ctx, {
      activeId: selectedIdRef.current,
      edges: edgesRef.current,
      hoveredId: hoverIdRef.current,
      nodeById: nodeByIdRef.current,
      nodes: nodesRef.current,
      ratio: window.devicePixelRatio || 1,
      rect: rectRef.current,
      viewport: viewportRef.current,
    });
  }, []);

  const tick = useCallback(() => {
    const nodes = nodesRef.current;
    if (nodes.length === 0) return 0;
    const rect = rectRef.current;
    const viewport = viewportRef.current;
    const center = {
      x: (rect.width / 2 - viewport.offsetX) / viewport.scale,
      y: (rect.height / 2 - viewport.offsetY) / viewport.scale,
    };
    const draggedNodeId = dragRef.current?.mode === "node" ? dragRef.current.id : "";
    let maxSpeed = 0;

    applyRepulsion(nodes);

    edgesRef.current.forEach((edge) => {
      const a = nodeByIdRef.current.get(edge.source);
      const b = nodeByIdRef.current.get(edge.target);
      if (!a || !b) return;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const desired = 120 + (1 - Number(edge.weight || 0.5)) * 75;
      const force = (distance - desired) * 0.004;
      const fx = (dx / distance) * force;
      const fy = (dy / distance) * force;
      a.vx += fx;
      a.vy += fy;
      b.vx -= fx;
      b.vy -= fy;
    });

    nodes.forEach((node) => {
      if (draggedNodeId === node.id) {
        node.vx = 0;
        node.vy = 0;
        return;
      }
      node.vx = (node.vx + (center.x - node.x) * 0.0009) * 0.84;
      node.vy = (node.vy + (center.y - node.y) * 0.0009) * 0.84;
      node.x += node.vx;
      node.y += node.vy;
      maxSpeed = Math.max(maxSpeed, Math.hypot(node.vx, node.vy));
    });

    return maxSpeed;
  }, []);

  const requestFrame = useCallback(() => {
    if (runningRef.current) return;
    runningRef.current = true;
    const animate = () => {
      const speed = tick();
      draw();
      if (speed > SETTLED_SPEED || dragRef.current?.mode === "node") {
        animationRef.current = window.requestAnimationFrame(animate);
        return;
      }
      runningRef.current = false;
      animationRef.current = null;
    };
    animationRef.current = window.requestAnimationFrame(animate);
  }, [draw, tick]);

  const clientToWorld = useCallback((clientX: number, clientY: number, currentViewport = viewportRef.current) => {
    return screenToWorld({ clientX, clientY }, rectRef.current, currentViewport);
  }, []);

  const nodeAt = useCallback((clientX: number, clientY: number) => {
    const point = clientToWorld(clientX, clientY);
    const canvasNodes = nodesRef.current;
    for (let index = canvasNodes.length - 1; index >= 0; index -= 1) {
      const node = canvasNodes[index];
      if (Math.hypot(point.x - node.x, point.y - node.y) <= node.radius + 8) return node;
    }
    return null;
  }, [clientToWorld]);

  const setViewport = useCallback((updater: (current: Viewport) => Viewport) => {
    viewportRef.current = updater(viewportRef.current);
    requestFrame();
  }, [requestFrame]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    updateCanvasRect();
    requestFrame();
    if (typeof ResizeObserver === "undefined") {
      const onResize = () => {
        updateCanvasRect();
        requestFrame();
      };
      window.addEventListener("resize", onResize);
      return () => window.removeEventListener("resize", onResize);
    }
    const observer = new ResizeObserver(() => {
      updateCanvasRect();
      requestFrame();
    });
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [requestFrame, updateCanvasRect]);

  useEffect(() => {
    const rect = rectRef.current;
    const center = { x: rect.width / 2, y: rect.height / 2 };
    const previousById = nodeByIdRef.current;
    const incoming = nodes.map((node, index): CanvasNode => {
      const previous = previousById.get(node.id);
      const angle = (index / Math.max(1, nodes.length)) * Math.PI * 2;
      const layoutRadius = 110 + Math.min(280, nodes.length * 10);
      return {
        ...node,
        radius: 13 + Math.min(13, Number(node.importance || 0.5) * 15),
        vx: previous?.vx ?? 0,
        vy: previous?.vy ?? 0,
        x: previous?.x ?? center.x + Math.cos(angle) * layoutRadius,
        y: previous?.y ?? center.y + Math.sin(angle) * layoutRadius,
      };
    });
    nodesRef.current = incoming;
    nodeByIdRef.current = new Map(incoming.map((node) => [node.id, node]));
    requestFrame();
  }, [nodes, requestFrame]);

  useEffect(() => {
    edgesRef.current = edges;
    requestFrame();
  }, [edges, requestFrame]);

  useEffect(() => {
    selectedIdRef.current = selectedId;
    requestFrame();
  }, [requestFrame, selectedId]);

  useEffect(() => {
    return () => {
      if (animationRef.current !== null) window.cancelAnimationFrame(animationRef.current);
    };
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      updateCanvasRect();
      setViewport((current) => {
        const factor = event.deltaY > 0 ? 0.92 : 1.08;
        return zoomViewportAtPoint(current, rectRef.current, { clientX: event.clientX, clientY: event.clientY }, factor);
      });
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, [setViewport, updateCanvasRect]);

  const showSkeletonMap = nodes.length === 0;
  const gestures = useGraphCanvasGestures({
    clientToWorld,
    dragRef,
    hoverIdRef,
    nodeAt,
    nodeByIdRef,
    onSelectNode,
    rectRef,
    requestFrame,
    setViewport,
    updateCanvasRect,
    viewportRef,
  });

  return (
    <main className={`graph-stage${showSkeletonMap ? " graph-stage--empty" : ""}`} aria-busy={loading}>
      <canvas
        ref={canvasRef}
        onPointerCancel={gestures.handlePointerCancel}
        onPointerDown={gestures.handlePointerDown}
        onPointerLeave={gestures.handlePointerLeave}
        onPointerMove={gestures.handlePointerMove}
        onPointerUp={gestures.handlePointerUp}
      />
      {showSkeletonMap ? (
        <>
          <MemoryMapSkeleton loading={loading} />
          <span className="graph-stage__sr-only">{loading ? "Loading memory graph" : "No memory nodes yet"}</span>
        </>
      ) : null}

      <FloatingNodePanel
        node={selectedDetails || selectedNode}
        relationships={relationships}
        onClose={() => onSelectNode(null)}
        onSelect={(id) => onSelectNode(id)}
      />
    </main>
  );
}
