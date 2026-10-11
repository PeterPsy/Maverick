import { describe, expect, it, vi } from "vitest";
import { ambientForce, reconcileForceData, type MemoryForceNode } from "./forceGraphData";

const cards = [{ id: "a", type: "fact", title: "First" }, { id: "b", type: "decision", title: "Second" }];
const edges = [
  { id: "one", source: "a", target: "b", kind: "supports" },
  { id: "two", source: "a", target: "b", kind: "contradicts" },
  { id: "three", source: "b", target: "a", kind: "supersedes" },
];

describe("force graph retrieval boundary", () => {
  it("preserves surviving simulation objects and positions without mutating retrieval cards", () => {
    const first = reconcileForceData({ nodes: [], links: [] }, cards, edges);
    first.nodes[0].x = 123; first.nodes[0].vx = 2;
    first.links[0].source = first.nodes[0];
    const next = reconcileForceData(first, [{ ...cards[0], title: "Updated" }, cards[1]], edges);
    expect(next.nodes[0]).toBe(first.nodes[0]);
    expect(next.nodes[0]).toMatchObject({ x: 123, vx: 2, card: { title: "Updated" } });
    expect(cards[0]).toEqual({ id: "a", type: "fact", title: "First" });
    expect(edges[0].source).toBe("a");
    expect(first.links[0].source).toBe(first.nodes[0]);
  });

  it("keeps parallel and reverse relationships in separate physical curves", () => {
    const { links } = reconcileForceData({ nodes: [], links: [] }, cards, edges);
    expect(links).toHaveLength(3);
    const physicalCurves = links.map((link) => link.curvature * (link.edge.source < link.edge.target ? 1 : -1));
    expect(new Set(physicalCurves).size).toBe(3);
    const reordered = reconcileForceData({ nodes: [], links: [] }, cards, [...edges].reverse());
    expect(Object.fromEntries(links.map((link) => [link.id, link.curvature])))
      .toEqual(Object.fromEntries(reordered.links.map((link) => [link.id, link.curvature])));
  });

  it("retains distinct loops, removes dangling links and deduplicates only by edge identity", () => {
    const { links } = reconcileForceData({ nodes: [], links: [] }, cards, [
      ...edges, edges[0], { id: "missing", source: "a", target: "absent", kind: "supports" },
      { id: "loop1", source: "a", target: "a", kind: "related_to" },
      { id: "loop2", source: "a", target: "a", kind: "contradicts" },
    ]);
    expect(links.map((link) => link.id)).toEqual(["one", "two", "three", "loop1", "loop2"]);
    expect(links[3].curvature).not.toBe(links[4].curvature);
  });

  it("replaces stale card metadata while keeping a dragged node fixed", () => {
    const data = reconcileForceData({ nodes: [], links: [] }, [{ ...cards[0], body_text: "Old body" }], []);
    data.nodes[0].fx = 80; data.nodes[0].fy = 40;
    const next = reconcileForceData(data, [cards[0]], []);
    expect(next.nodes[0].card.body_text).toBeUndefined();
    expect(next.nodes[0]).toMatchObject({ fx: 80, fy: 40 });
  });

  it("bounds ambient drift around settled anchors and leaves fixed nodes alone", () => {
    vi.spyOn(performance, "now").mockReturnValue(4000);
    const node: MemoryForceNode = { id: "a", card: cards[0], x: 0, y: 0, vx: 0, vy: 0 };
    const fixed: MemoryForceNode = { id: "b", card: cards[1], x: 0, y: 0, fx: 0, fy: 0, vx: 0, vy: 0 };
    const force = ambientForce(); force.initialize([node, fixed]);
    force(.5); expect(node.vx).toBe(0);
    for (let tick = 0; tick < 300; tick++) {
      force(0);
      node.vx! *= .68; node.vy! *= .68; node.x! += node.vx!; node.y! += node.vy!;
    }
    expect(Math.abs(node.x!)).toBeLessThanOrEqual(4.1);
    expect(Math.abs(node.y!)).toBeLessThanOrEqual(4.1);
    expect(fixed.vx).toBe(0); expect(fixed.vy).toBe(0);
    vi.restoreAllMocks();
  });
});
