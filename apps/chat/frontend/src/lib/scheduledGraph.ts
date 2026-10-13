import type { ScheduledGraph } from "../api/scheduledChats";

export function canConnectBlocks(graph: ScheduledGraph, source: string | null, target: string | null): boolean {
  if (!source || !target || source === target || !graph.nodes.some(node => node.id === source)
    || !graph.nodes.some(node => node.id === target) || graph.edges.length >= 256
    || graph.edges.some(edge => edge.source === source && edge.target === target)) return false;
  const visited = new Set<string>();
  const pending = [target];
  while (pending.length) {
    const id = pending.pop()!;
    if (id === source) return false;
    if (visited.has(id)) continue;
    visited.add(id);
    pending.push(...graph.edges.filter(edge => edge.source === id).map(edge => edge.target));
  }
  return true;
}

export function layoutScheduledGraph(graph: ScheduledGraph): ScheduledGraph {
  const ranks = new Map<string, number>();
  const remaining = new Set(graph.nodes.map(node => node.id));
  while (remaining.size) {
    let progressed = false;
    for (const id of remaining) {
      const parents = graph.edges.filter(edge => edge.target === id).map(edge => edge.source);
      if (parents.some(parent => !ranks.has(parent))) continue;
      ranks.set(id, parents.length ? Math.max(...parents.map(parent => ranks.get(parent)!)) + 1 : 0);
      remaining.delete(id); progressed = true;
    }
    if (!progressed) break;
  }
  const rows = new Map<number, number>();
  return { ...graph, nodes: graph.nodes.map(node => {
    const rank = ranks.get(node.id) || 0;
    const row = rows.get(rank) || 0; rows.set(rank, row + 1);
    return { ...node, position: { x: 100 + rank * 340, y: 150 + row * 190 } };
  }) };
}
