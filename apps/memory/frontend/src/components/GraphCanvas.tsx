import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Maximize2, RefreshCw } from "lucide-react";
import { colors } from "../constants";
import { labelForType, truncate } from "../format";
import type { GraphEdge, GraphNode, NodeDetails, RelationshipRow } from "../types";
import { FloatingNodePanel } from "./FloatingNodePanel";

type Viewport = {
  scale: number;
  offsetX: number;
  offsetY: number;
};

type GraphCanvasProps = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedId: string | null;
  selectedNode: GraphNode | null;
  selectedDetails: NodeDetails | null;
  relationships: RelationshipRow[];
  status: string;
  setNodes: (updater: (nodes: GraphNode[]) => GraphNode[]) => void;
  onRefreshGraph: () => void;
  onSelectNode: (id: string | null) => void;
};

export function GraphCanvas({
  nodes,
  edges,
  selectedId,
  selectedNode,
  selectedDetails,
  relationships,
  status,
  setNodes,
  onRefreshGraph,
  onSelectNode,
}: GraphCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animationRef = useRef<number | null>(null);
  const dragRef = useRef<{ mode: "node" | "pan"; id?: string; lastX: number; lastY: number } | null>(null);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [viewport, setViewport] = useState<Viewport>({ scale: 1, offsetX: 0, offsetY: 0 });
  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);

  const clientToWorld = useCallback((clientX: number, clientY: number, currentViewport: Viewport) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    return {
      x: (clientX - (rect?.left || 0) - currentViewport.offsetX) / currentViewport.scale,
      y: (clientY - (rect?.top || 0) - currentViewport.offsetY) / currentViewport.scale,
    };
  }, []);

  const screenToWorld = useCallback((clientX: number, clientY: number) => {
    return clientToWorld(clientX, clientY, viewport);
  }, [clientToWorld, viewport]);

  const nodeAt = useCallback((clientX: number, clientY: number) => {
    const point = screenToWorld(clientX, clientY);
    for (let index = nodes.length - 1; index >= 0; index -= 1) {
      const node = nodes[index];
      if (Math.hypot(point.x - (node.x || 0), point.y - (node.y || 0)) <= (node.radius || 18) + 8) return node;
    }
    return null;
  }, [nodes, screenToWorld]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const rect = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(rect.width * ratio));
    canvas.height = Math.max(1, Math.floor(rect.height * ratio));
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    ctx.save();
    ctx.translate(viewport.offsetX, viewport.offsetY);
    ctx.scale(viewport.scale, viewport.scale);

    edges.forEach((edge) => {
      const source = nodeById.get(edge.source);
      const target = nodeById.get(edge.target);
      if (!source || !target || source.x === undefined || target.x === undefined || source.y === undefined || target.y === undefined) return;
      const active = selectedId && (edge.source === selectedId || edge.target === selectedId);
      ctx.beginPath();
      ctx.moveTo(source.x, source.y);
      ctx.lineTo(target.x, target.y);
      ctx.strokeStyle = active ? "rgba(255,255,255,.76)" : "rgba(132,151,160,.24)";
      ctx.lineWidth = active ? 2.8 : 0.8 + Number(edge.weight || 0.5) * 1.8;
      ctx.stroke();
    });

    nodes.forEach((node) => {
      const x = node.x || 0;
      const y = node.y || 0;
      const radius = node.radius || 18;
      const active = node.id === selectedId;
      const hovered = node.id === hoverId;
      ctx.beginPath();
      ctx.arc(x, y, radius + (active ? 10 : hovered ? 6 : 0), 0, Math.PI * 2);
      ctx.fillStyle = active ? "rgba(255,255,255,.18)" : hovered ? "rgba(255,255,255,.1)" : "rgba(255,255,255,.04)";
      ctx.fill();
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fillStyle = colors[node.type] || "#ccd6dd";
      ctx.fill();
      ctx.lineWidth = active ? 3 : 1.4;
      ctx.strokeStyle = active ? "#fff" : "#0b0f12";
      ctx.stroke();
      if (active || hovered || nodes.length < 42) {
        ctx.font = "12px Inter, system-ui, sans-serif";
        ctx.fillStyle = "#edf4f6";
        ctx.textAlign = "center";
        ctx.fillText(truncate(node.title, 30), x, y + radius + 18);
      }
    });
    ctx.restore();
  }, [edges, hoverId, nodeById, nodes, selectedId, viewport]);

  const tick = useCallback(() => {
    const rect = canvasRef.current?.getBoundingClientRect();
    const center = { x: (rect?.width || 900) / 2, y: (rect?.height || 620) / 2 };
    setNodes((current) => {
      const next = current.map((node) => ({ ...node, vx: node.vx || 0, vy: node.vy || 0 }));
      const nextById = new Map(next.map((node) => [node.id, node]));
      for (let i = 0; i < next.length; i += 1) {
        for (let j = i + 1; j < next.length; j += 1) {
          const a = next[i];
          const b = next[j];
          const dx = (b.x || 0) - (a.x || 0) || 0.01;
          const dy = (b.y || 0) - (a.y || 0) || 0.01;
          const distance = Math.max(20, Math.hypot(dx, dy));
          const force = 900 / (distance * distance);
          const fx = (dx / distance) * force;
          const fy = (dy / distance) * force;
          a.vx = (a.vx || 0) - fx;
          a.vy = (a.vy || 0) - fy;
          b.vx = (b.vx || 0) + fx;
          b.vy = (b.vy || 0) + fy;
        }
      }
      edges.forEach((edge) => {
        const a = nextById.get(edge.source);
        const b = nextById.get(edge.target);
        if (!a || !b) return;
        const dx = (b.x || 0) - (a.x || 0);
        const dy = (b.y || 0) - (a.y || 0);
        const distance = Math.max(1, Math.hypot(dx, dy));
        const desired = 120 + (1 - Number(edge.weight || 0.5)) * 75;
        const force = (distance - desired) * 0.004;
        const fx = (dx / distance) * force;
        const fy = (dy / distance) * force;
        a.vx = (a.vx || 0) + fx;
        a.vy = (a.vy || 0) + fy;
        b.vx = (b.vx || 0) - fx;
        b.vy = (b.vy || 0) - fy;
      });
      next.forEach((node) => {
        if (dragRef.current?.mode === "node" && dragRef.current.id === node.id) return;
        node.vx = ((node.vx || 0) + (center.x - (node.x || center.x)) * 0.0009) * 0.84;
        node.vy = ((node.vy || 0) + (center.y - (node.y || center.y)) * 0.0009) * 0.84;
        node.x = (node.x || center.x) + node.vx;
        node.y = (node.y || center.y) + node.vy;
      });
      return next;
    });
  }, [edges, setNodes]);

  useEffect(() => {
    const animate = () => {
      tick();
      draw();
      animationRef.current = window.requestAnimationFrame(animate);
    };
    animationRef.current = window.requestAnimationFrame(animate);
    return () => {
      if (animationRef.current !== null) window.cancelAnimationFrame(animationRef.current);
    };
  }, [draw, tick]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      setViewport((current) => {
        const before = clientToWorld(event.clientX, event.clientY, current);
        const factor = event.deltaY > 0 ? 0.92 : 1.08;
        const scale = Math.max(0.45, Math.min(2.2, current.scale * factor));
        const rect = canvas.getBoundingClientRect();
        return {
          scale,
          offsetX: event.clientX - rect.left - before.x * scale,
          offsetY: event.clientY - rect.top - before.y * scale,
        };
      });
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, [clientToWorld]);

  return (
    <main className="graph-stage">
      <div className="graph-toolbar">
        <div className="graph-toolbar__left">
          <span className="status-pill">{status}</span>
          <span className="metric-pill">{nodes.length} nodes</span>
          <span className="metric-pill">{edges.length} links</span>
          <div className="chips" aria-label="Visible node types">
            {[...new Set(nodes.map((node) => node.type))].sort().map((type) => (
              <span className="chip" key={type}><i style={{ background: colors[type] || "#ccd6dd" }} />{labelForType(type)}</span>
            ))}
          </div>
        </div>
        <div className="graph-toolbar__actions">
          <button type="button" className="icon-action" onClick={onRefreshGraph} aria-label="Refresh graph" title="Refresh graph">
            <RefreshCw size={15} aria-hidden="true" />
          </button>
          <button type="button" className="icon-action" onClick={() => setViewport({ scale: 1, offsetX: 0, offsetY: 0 })} aria-label="Fit graph" title="Fit graph">
            <Maximize2 size={15} aria-hidden="true" />
          </button>
        </div>
      </div>
      <canvas
        ref={canvasRef}
        onMouseDown={(event) => {
          const node = nodeAt(event.clientX, event.clientY);
          if (node) {
            dragRef.current = { mode: "node", id: node.id, lastX: event.clientX, lastY: event.clientY };
            onSelectNode(node.id);
          } else {
            dragRef.current = { mode: "pan", lastX: event.clientX, lastY: event.clientY };
          }
        }}
        onMouseMove={(event) => {
          const node = nodeAt(event.clientX, event.clientY);
          setHoverId(node?.id || null);
          const drag = dragRef.current;
          if (!drag) return;
          if (drag.mode === "node" && drag.id) {
            const point = screenToWorld(event.clientX, event.clientY);
            setNodes((current) => current.map((item) => item.id === drag.id ? { ...item, x: point.x, y: point.y, vx: 0, vy: 0 } : item));
          } else {
            setViewport((current) => ({ ...current, offsetX: current.offsetX + event.clientX - drag.lastX, offsetY: current.offsetY + event.clientY - drag.lastY }));
            dragRef.current = { ...drag, lastX: event.clientX, lastY: event.clientY };
          }
        }}
        onMouseUp={() => { dragRef.current = null; }}
        onMouseLeave={() => { dragRef.current = null; setHoverId(null); }}
      />
      {!nodes.length && <div className="empty-state">No memory nodes yet</div>}

      <FloatingNodePanel
        node={selectedDetails || selectedNode}
        relationships={relationships}
        onClose={() => onSelectNode(null)}
        onSelect={(id) => onSelectNode(id)}
      />
    </main>
  );
}
