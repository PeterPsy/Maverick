import { colors } from "../constants";
import { truncate } from "../format";
import type { Viewport, ViewportRect } from "../lib/graphViewport";
import type { GraphEdge, GraphNode } from "../types";
import { drawNodeIcon } from "./nodeCanvasIcons";

type DrawableNode = Pick<GraphNode, "id" | "title" | "type"> & {
  radius: number;
  x: number;
  y: number;
};

type DrawGraphOptions<TNode extends DrawableNode> = {
  activeId: string | null;
  edges: GraphEdge[];
  hoveredId: string | null;
  nodeById: Map<string, TNode>;
  nodes: TNode[];
  ratio: number;
  rect: ViewportRect;
  viewport: Viewport;
};

export function drawGraphCanvas<TNode extends DrawableNode>(
  ctx: CanvasRenderingContext2D,
  { activeId, edges, hoveredId, nodeById, nodes, ratio, rect, viewport }: DrawGraphOptions<TNode>,
) {
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  ctx.save();
  ctx.translate(viewport.offsetX, viewport.offsetY);
  ctx.scale(viewport.scale, viewport.scale);

  edges.forEach((edge) => {
    const source = nodeById.get(edge.source);
    const target = nodeById.get(edge.target);
    if (!source || !target) return;
    const active = activeId && (edge.source === activeId || edge.target === activeId);
    ctx.beginPath();
    ctx.moveTo(source.x, source.y);
    ctx.lineTo(target.x, target.y);
    ctx.strokeStyle = active ? "rgba(255,255,255,.76)" : "rgba(132,151,160,.24)";
    ctx.lineWidth = active ? 2.8 : 0.8 + Number(edge.weight || 0.5) * 1.8;
    ctx.stroke();
  });

  nodes.forEach((node) => {
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
    if (active || hovered || nodes.length < 42) {
      ctx.font = "12px Inter, system-ui, sans-serif";
      ctx.fillStyle = "#edf4f6";
      ctx.textAlign = "center";
      ctx.fillText(truncate(node.title, 30), node.x, node.y + node.radius + 18);
    }
  });
  ctx.restore();
}
