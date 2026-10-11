import { colors } from "../constants";
import { type MemoryForceData, type MemoryForceLink, type MemoryForceNode } from "../lib/forceGraphData";
import { iconDataUrlForType } from "./nodeIcons";

export type GraphHighlight = { selectedId: string | null; hoveredId: string | null; edgeId: string | null; neighbors: Set<string> };

export function graphHighlight(data: MemoryForceData, selectedId: string | null, hoveredId: string | null, edgeId: string | null): GraphHighlight {
  const focus = hoveredId || selectedId;
  const neighbors = new Set<string>();
  if (focus) {
    neighbors.add(focus);
    data.links.forEach((link) => {
      if (link.edge.source === focus || link.edge.target === focus) {
        neighbors.add(link.edge.source); neighbors.add(link.edge.target);
      }
    });
  }
  const selectedEdge = data.links.find((link) => link.id === edgeId);
  if (selectedEdge) { neighbors.add(selectedEdge.edge.source); neighbors.add(selectedEdge.edge.target); }
  return { selectedId, hoveredId, edgeId, neighbors };
}

export function highlightedLink(link: MemoryForceLink, state: GraphHighlight) {
  const focus = state.hoveredId || state.selectedId;
  return link.id === state.edgeId || !!focus && (link.edge.source === focus || link.edge.target === focus);
}

export function linkColor(link: MemoryForceLink, state: GraphHighlight) {
  const color = link.edge.kind === "contradicts" ? "#ff8da1" : link.edge.kind === "supersedes" ? "#ffce73"
    : colors[typeof link.source === "object" ? link.source.card.type : "fact"] || "#67d5ff";
  return `${color}${highlightedLink(link, state) ? "d9" : state.neighbors.size ? "24" : "55"}`;
}

export function createNodePainter() {
  const icons = new Map<string, HTMLImageElement>();
  return (node: MemoryForceNode, ctx: CanvasRenderingContext2D, scale: number, state: GraphHighlight) => {
    const x = node.x || 0, y = node.y || 0;
    const active = node.id === state.selectedId || node.id === state.hoveredId;
    const near = state.neighbors.has(node.id);
    const color = colors[node.card.type] || "#ccd6dd";
    const radius = 18;
    ctx.save();
    ctx.globalAlpha = state.neighbors.size && !near ? .35 : 1;
    const glow = ctx.createRadialGradient(x, y, radius * .4, x, y, radius * (active ? 3.5 : 2.2));
    glow.addColorStop(0, `${color}${active ? "40" : "16"}`); glow.addColorStop(1, `${color}00`);
    ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(x, y, radius * (active ? 3.5 : 2.2), 0, Math.PI * 2); ctx.fill();
    const surface = ctx.createLinearGradient(x - radius, y - radius, x + radius, y + radius);
    surface.addColorStop(0, "#232b32"); surface.addColorStop(1, "#0c1116");
    ctx.fillStyle = surface; ctx.strokeStyle = `${color}${active || near ? "ff" : "a0"}`;
    ctx.lineWidth = (active ? 2 : 1.2) / Math.max(.7, scale);
    ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    if (active) {
      ctx.strokeStyle = `${color}55`; ctx.lineWidth = 1 / scale;
      ctx.beginPath(); ctx.arc(x, y, radius + 5 / scale, 0, Math.PI * 2); ctx.stroke();
    }
    let icon = icons.get(node.card.type);
    if (!icon) { icon = new Image(); icon.src = iconDataUrlForType(node.card.type, color); icons.set(node.card.type, icon); }
    if (icon.complete && icon.naturalWidth) ctx.drawImage(icon, x - 9, y - 9, 18, 18);
    else { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fill(); }
    if (scale >= .55 || active || near) {
      const fontSize = Math.min(17, 11 / Math.sqrt(Math.max(.35, scale)));
      ctx.font = `${active ? 600 : 450} ${fontSize}px "Avenir Next", "Segoe UI", sans-serif`;
      const title = node.card.title.length > 38 ? `${node.card.title.slice(0, 36)}…` : node.card.title;
      const width = ctx.measureText(title).width + 16;
      const labelY = y + radius + 8;
      ctx.fillStyle = "#0c1116d9";
      ctx.beginPath(); ctx.roundRect(x - width / 2, labelY, width, fontSize + 12, 7); ctx.fill();
      ctx.fillStyle = active ? "#ffffff" : "#d4dbe2"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(title, x, labelY + (fontSize + 12) / 2);
    }
    ctx.restore();
  };
}

export function paintNodeHitArea(node: MemoryForceNode, color: string, ctx: CanvasRenderingContext2D) {
  ctx.fillStyle = color; ctx.beginPath(); ctx.arc(node.x || 0, node.y || 0, 24, 0, Math.PI * 2); ctx.fill();
}
