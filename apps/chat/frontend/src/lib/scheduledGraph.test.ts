import { describe, expect, it } from "vitest";
import { canConnectBlocks, layoutScheduledGraph } from "./scheduledGraph";
import type { ScheduledGraph } from "../api/scheduledChats";

const graph: ScheduledGraph = { nodes: ["a", "b", "c"].map(id => ({ id, title: id, instructions: id, skill_ids: [], position: { x: 0, y: 0 } })), edges: [{ id: "a-b", source: "a", target: "b" }] };

describe("scheduled graph editing", () => {
  it("rejects cyclic, duplicate and virtual-node connections", () => {
    expect(canConnectBlocks(graph, "b", "a")).toBe(false);
    expect(canConnectBlocks(graph, "a", "b")).toBe(false);
    expect(canConnectBlocks(graph, "a", "a")).toBe(false);
    expect(canConnectBlocks(graph, "__schedule", "a")).toBe(false);
    expect(canConnectBlocks(graph, "c", "b")).toBe(true);
  });
  it("positions prerequisites before dependents and separates parallel roots", () => {
    const result = layoutScheduledGraph(graph);
    expect(result.nodes[0].position.x).toBeLessThan(result.nodes[1].position.x);
    expect(result.nodes[0].position.y).not.toBe(result.nodes[2].position.y);
    expect(graph.nodes[0].position).toEqual({ x: 0, y: 0 });
  });
});
