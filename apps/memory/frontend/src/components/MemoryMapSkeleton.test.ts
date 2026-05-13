import { describe, expect, it } from "vitest";
import { memoryMapSkeletonLinks, memoryMapSkeletonNodes } from "./MemoryMapSkeleton";

describe("memory map skeleton", () => {
  it("keeps every decorative link connected to a placeholder node", () => {
    const nodeIds = new Set(memoryMapSkeletonNodes.map((node) => node.id));

    expect(memoryMapSkeletonNodes.length).toBeGreaterThan(4);
    memoryMapSkeletonLinks.forEach((link) => {
      expect(nodeIds.has(link.source)).toBe(true);
      expect(nodeIds.has(link.target)).toBe(true);
    });
  });

  it("keeps placeholder nodes inside the board viewport", () => {
    memoryMapSkeletonNodes.forEach((node) => {
      expect(node.x).toBeGreaterThanOrEqual(0);
      expect(node.x).toBeLessThanOrEqual(100);
      expect(node.y).toBeGreaterThanOrEqual(0);
      expect(node.y).toBeLessThanOrEqual(100);
      expect(node.size).toBeGreaterThan(0);
    });
  });
});
