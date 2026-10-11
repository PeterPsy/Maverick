import { describe, expect, it } from "vitest";
import { contextIdsFromParams, mergeSubgraph } from "./graphSubgraph";

describe("Memory subgraph navigation", () => {
  it("places a deep-linked node and its neighborhood in the bounded graph and preserves parallel edge ids", () => {
    const result = mergeSubgraph({ nodes: Array.from({ length: 40 }, (_, index) => ({ id: String(index), title: String(index), type: "fact" })), edges: [] },
      { nodes: [{ id: "chat", title: "From Chat", type: "fact" }, { id: "neighbor", title: "Dependency", type: "fact" }],
        edges: [{ id: "first", source: "chat", target: "neighbor", kind: "depends_on" }, { id: "second", source: "chat", target: "neighbor", kind: "contradicts" }] });
    expect(result.nodes).toHaveLength(40);
    expect(result.nodes.slice(0, 2).map((node) => node.id)).toEqual(["chat", "neighbor"]);
    expect(result.edges.map((edge) => edge.id)).toEqual(["first", "second"]);
  });
  it("bounds conversation-local references and rejects malformed navigation", () => {
    expect(contextIdsFromParams({ context_node_ids: '["one","one","two",3]' })).toEqual(["one", "two"]);
    expect(contextIdsFromParams({ context_node_ids: "invalid" })).toEqual([]);
    expect(contextIdsFromParams({ context_node_ids: JSON.stringify(Array.from({ length: 100 }, (_, index) => String(index))) })).toHaveLength(40);
  });
});
