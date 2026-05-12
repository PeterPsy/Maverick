import { describe, expect, it } from "vitest";
import { nodeIdFromParams, shouldOpenCreateNode } from "./memoryNavigationParams";

describe("memory navigation params", () => {
  it("resolves node ids from direct params and app pages", () => {
    expect(nodeIdFromParams({ node_id: "node-a" })).toBe("node-a");
    expect(nodeIdFromParams({ entity_id: "node-b" })).toBe("node-b");
    expect(nodeIdFromParams({ app_page: "nodes/node%20c" })).toBe("node c");
  });

  it("detects create-node requests", () => {
    expect(shouldOpenCreateNode({ new_node: true })).toBe(true);
    expect(shouldOpenCreateNode({ new_node: "true" })).toBe(true);
    expect(shouldOpenCreateNode({ create_node: "true" })).toBe(true);
    expect(shouldOpenCreateNode({ new_node: false })).toBe(false);
  });
});
