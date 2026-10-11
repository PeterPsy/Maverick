import type { GraphData, LinkObject, NodeObject } from "react-force-graph-2d";
import type { GraphEdge, GraphNode } from "../types";

export type MemoryForceCard = { id: string; card: GraphNode };
export type MemoryForceEdge = { id: string; edge: GraphEdge; curvature: number };
export type MemoryForceNode = NodeObject<MemoryForceCard>;
export type MemoryForceLink = LinkObject<MemoryForceCard, MemoryForceEdge>;
export type MemoryForceData = GraphData<MemoryForceCard, MemoryForceEdge>;

// The engine mutates coordinates and replaces link endpoints with node objects.
// Keep those mutations away from retrieval cards and reuse surviving node objects.
export function reconcileForceData(previous: MemoryForceData, cards: GraphNode[], edges: GraphEdge[]): MemoryForceData {
  const known = new Map(previous.nodes.map((node) => [node.id, node]));
  const nodes = cards.map((card, index) => {
    const current = known.get(card.id);
    if (current) {
      current.card = { ...card };
      return current;
    }
    const angle = index * Math.PI * (3 - Math.sqrt(5));
    const radius = 55 + Math.sqrt(index) * 42;
    const connection = edges.find((edge) => edge.source === card.id || edge.target === card.id);
    const neighbor = known.get(connection?.source === card.id ? connection.target : connection?.source || "");
    return { id: card.id, card: { ...card }, x: (neighbor?.x || 0) + Math.cos(angle) * radius, y: (neighbor?.y || 0) + Math.sin(angle) * radius };
  });
  const ids = new Set(nodes.map((node) => node.id));
  const seen = new Set<string>();
  const links: MemoryForceLink[] = [];
  edges.forEach((edge, index) => {
    const id = edge.id || `edge:${index}:${edge.source}:${edge.target}:${edge.kind}`;
    if (!ids.has(edge.source) || !ids.has(edge.target) || seen.has(id)) return;
    seen.add(id);
    links.push({ id, edge: { ...edge }, source: edge.source, target: edge.target, curvature: 0 });
  });
  const pairs = new Map<string, MemoryForceLink[]>();
  for (const link of links) {
    const key = JSON.stringify([link.edge.source, link.edge.target].sort());
    const group = pairs.get(key) || [];
    group.push(link);
    pairs.set(key, group);
  }
  for (const group of pairs.values()) {
    group.sort((a, b) => a.id.localeCompare(b.id));
    group.forEach((link, index) => {
      const { source, target } = link.edge;
      link.curvature = source === target ? .65 + index * .22
        : (index - (group.length - 1) / 2) * .28 * (source < target ? 1 : -1);
    });
  }
  return { nodes, links };
}

// Once layout settles, each node drifts only a few graph units around its anchor.
// The library runs this force without any React state updates per frame.
export function ambientForce() {
  let nodes: MemoryForceNode[] = [];
  const anchors = new Map<string, { x: number; y: number; phase: number }>();
  const force = (alpha: number) => {
    if (alpha > .04) {
      anchors.clear();
      nodes.forEach((node) => {
        node.vx = (node.vx || 0) - (node.x || 0) * .018 * alpha;
        node.vy = (node.vy || 0) - (node.y || 0) * .018 * alpha;
      });
      return;
    }
    const time = performance.now() / 2200;
    nodes.forEach((node, index) => {
      if (node.fx != null || node.fy != null) { anchors.delete(node.id); return; }
      let anchor = anchors.get(node.id);
      if (!anchor) { anchor = { x: node.x || 0, y: node.y || 0, phase: index * 2.4 }; anchors.set(node.id, anchor); }
      node.vx = (node.vx || 0) + (anchor.x + Math.sin(time + anchor.phase) * 4 - (node.x || 0)) * .018;
      node.vy = (node.vy || 0) + (anchor.y + Math.cos(time * .8 + anchor.phase) * 4 - (node.y || 0)) * .018;
    });
  };
  force.initialize = (current: MemoryForceNode[]) => { nodes = current; anchors.clear(); };
  return force;
}
