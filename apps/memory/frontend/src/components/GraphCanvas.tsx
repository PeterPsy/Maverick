import { useCallback, useEffect, useRef } from "react";
import { colors } from "../constants";
import { truncate } from "../format";
import type { GraphEdge, GraphNode, NodeDetails, RelationshipRow } from "../types";
import { FloatingNodePanel } from "./FloatingNodePanel";
import { MemoryMapSkeleton } from "./MemoryMapSkeleton";
import { drawNodeIcon } from "./nodeCanvasIcons";

type Viewport = {
  scale: number;
  offsetX: number;
  offsetY: number;
};

type CanvasRect = {
  height: number;
  left: number;
  top: number;
  width: number;
};

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
const EXACT_REPULSION_NODE_LIMIT = 180;
const GRID_CELL_SIZE = 180;
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
  const dragRef = useRef<{ mode: "node" | "pan"; id?: string; lastX: number; lastY: number } | null>(null);
  const edgesRef = useRef<GraphEdge[]>(edges);
  const hoverIdRef = useRef<string | null>(null);
  const nodeByIdRef = useRef<Map<string, CanvasNode>>(new Map());
  const nodesRef = useRef<CanvasNode[]>([]);
  const rectRef = useRef<CanvasRect>({ height: 620, left: 0, top: 0, width: 900 });
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
    const rect = rectRef.current;
    const ratio = window.devicePixelRatio || 1;
    const viewport = viewportRef.current;
    const canvasNodes = nodesRef.current;
    const canvasNodeById = nodeByIdRef.current;
    const hoveredId = hoverIdRef.current;
    const activeId = selectedIdRef.current;

    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    ctx.save();
    ctx.translate(viewport.offsetX, viewport.offsetY);
    ctx.scale(viewport.scale, viewport.scale);

    edgesRef.current.forEach((edge) => {
      const source = canvasNodeById.get(edge.source);
      const target = canvasNodeById.get(edge.target);
      if (!source || !target) return;
      const active = activeId && (edge.source === activeId || edge.target === activeId);
      ctx.beginPath();
      ctx.moveTo(source.x, source.y);
      ctx.lineTo(target.x, target.y);
      ctx.strokeStyle = active ? "rgba(255,255,255,.76)" : "rgba(132,151,160,.24)";
      ctx.lineWidth = active ? 2.8 : 0.8 + Number(edge.weight || 0.5) * 1.8;
      ctx.stroke();
    });

    canvasNodes.forEach((node) => {
      const color = colors[node.type] || "#ccd6dd";
      const active = node.id === activeId;
      const hovered = node.id === hoveredId;
      if (active || hovered) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius + (active ? 8 : 5), 0, Math.PI * 2);
        ctx.strokeStyle = active ? "rgba(255,255,255,.78)" : "rgba(255,255,255,.28)";
        ctx.lineWidth = active ? 2.2 : 1.4;
        ctx.stroke();
      }
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
      ctx.fillStyle = active ? "rgba(20,23,25,.98)" : "rgba(12,15,17,.92)";
      ctx.fill();
      ctx.lineWidth = active ? 3.2 : 2.2;
      ctx.strokeStyle = color;
      ctx.stroke();
      drawNodeIcon(ctx, node.type, node.x, node.y, node.radius, color);
      if (active || hovered || canvasNodes.length < 42) {
        ctx.font = "12px Inter, system-ui, sans-serif";
        ctx.fillStyle = "#edf4f6";
        ctx.textAlign = "center";
        ctx.fillText(truncate(node.title, 30), node.x, node.y + node.radius + 18);
      }
    });
    ctx.restore();
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
    const rect = rectRef.current;
    return {
      x: (clientX - rect.left - currentViewport.offsetX) / currentViewport.scale,
      y: (clientY - rect.top - currentViewport.offsetY) / currentViewport.scale,
    };
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
        const before = clientToWorld(event.clientX, event.clientY, current);
        const factor = event.deltaY > 0 ? 0.92 : 1.08;
        const scale = Math.max(0.45, Math.min(2.2, current.scale * factor));
        const rect = rectRef.current;
        return {
          scale,
          offsetX: event.clientX - rect.left - before.x * scale,
          offsetY: event.clientY - rect.top - before.y * scale,
        };
      });
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, [clientToWorld, setViewport, updateCanvasRect]);

  const showSkeletonMap = nodes.length === 0;

  return (
    <main className={`graph-stage${showSkeletonMap ? " graph-stage--empty" : ""}`} aria-busy={loading}>
      <canvas
        ref={canvasRef}
        onMouseDown={(event) => {
          updateCanvasRect();
          const node = nodeAt(event.clientX, event.clientY);
          if (node) {
            dragRef.current = { mode: "node", id: node.id, lastX: event.clientX, lastY: event.clientY };
            onSelectNode(node.id);
          } else {
            dragRef.current = { mode: "pan", lastX: event.clientX, lastY: event.clientY };
          }
          requestFrame();
        }}
        onMouseMove={(event) => {
          updateCanvasRect();
          const node = nodeAt(event.clientX, event.clientY);
          const nextHoverId = node?.id || null;
          if (hoverIdRef.current !== nextHoverId) {
            hoverIdRef.current = nextHoverId;
            requestFrame();
          }
          const drag = dragRef.current;
          if (!drag) return;
          if (drag.mode === "node" && drag.id) {
            const draggedNode = nodeByIdRef.current.get(drag.id);
            if (!draggedNode) return;
            const point = clientToWorld(event.clientX, event.clientY);
            draggedNode.x = point.x;
            draggedNode.y = point.y;
            draggedNode.vx = 0;
            draggedNode.vy = 0;
            requestFrame();
            return;
          }
          setViewport((current) => ({
            ...current,
            offsetX: current.offsetX + event.clientX - drag.lastX,
            offsetY: current.offsetY + event.clientY - drag.lastY,
          }));
          dragRef.current = { ...drag, lastX: event.clientX, lastY: event.clientY };
        }}
        onMouseUp={() => {
          dragRef.current = null;
          requestFrame();
        }}
        onMouseLeave={() => {
          dragRef.current = null;
          hoverIdRef.current = null;
          requestFrame();
        }}
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

function applyRepulsion(nodes: CanvasNode[]) {
  if (nodes.length <= EXACT_REPULSION_NODE_LIMIT) {
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        applyRepulsionPair(nodes[i], nodes[j]);
      }
    }
    return;
  }
  applyGridRepulsion(nodes);
}

function applyGridRepulsion(nodes: CanvasNode[]) {
  const grid = new Map<string, CanvasNode[]>();
  const indexById = new Map(nodes.map((node, index) => [node.id, index]));
  nodes.forEach((node) => {
    const key = gridKey(node.x, node.y);
    const cell = grid.get(key);
    if (cell) {
      cell.push(node);
    } else {
      grid.set(key, [node]);
    }
  });

  nodes.forEach((node, index) => {
    const cellX = Math.floor(node.x / GRID_CELL_SIZE);
    const cellY = Math.floor(node.y / GRID_CELL_SIZE);
    for (let x = cellX - 1; x <= cellX + 1; x += 1) {
      for (let y = cellY - 1; y <= cellY + 1; y += 1) {
        const cell = grid.get(`${x}:${y}`);
        if (!cell) continue;
        cell.forEach((other) => {
          if ((indexById.get(other.id) ?? -1) <= index) return;
          applyRepulsionPair(node, other);
        });
      }
    }
  });
}

function applyRepulsionPair(a: CanvasNode, b: CanvasNode) {
  const dx = b.x - a.x || 0.01;
  const dy = b.y - a.y || 0.01;
  const distance = Math.max(20, Math.hypot(dx, dy));
  const force = 900 / (distance * distance);
  const fx = (dx / distance) * force;
  const fy = (dy / distance) * force;
  a.vx -= fx;
  a.vy -= fy;
  b.vx += fx;
  b.vy += fy;
}

function gridKey(x: number, y: number) {
  return `${Math.floor(x / GRID_CELL_SIZE)}:${Math.floor(y / GRID_CELL_SIZE)}`;
}
