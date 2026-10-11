import type { GraphEdge, GraphNode } from "../types";

export type Subgraph = { nodes: GraphNode[]; edges: GraphEdge[] };

export function mergeSubgraph(base: Subgraph, focus: Subgraph | null, limit = 40): Subgraph {
  const cards = new Map(base.nodes.map((node) => [node.id, node]));
  for (const node of focus?.nodes || []) cards.set(node.id, node);
  const ids = [...new Set([...(focus?.nodes || []).map((node) => node.id), ...base.nodes.map((node) => node.id)])].slice(0, limit);
  const visible = new Set(ids);
  const edges = new Map([...base.edges, ...(focus?.edges || [])].map((edge) => [edge.id, edge]));
  return { nodes: ids.map((id) => cards.get(id)!), edges: [...edges.values()].filter((edge) => visible.has(edge.source) && visible.has(edge.target)) };
}

export function contextIdsFromParams(params: Record<string, unknown>): string[] {
  try {
    const value = JSON.parse(String(params.context_node_ids || "[]"));
    return Array.isArray(value) ? [...new Set(value.filter((id): id is string => typeof id === "string" && !!id && id.length <= 256))].slice(0, 40) : [];
  } catch { return []; }
}
