import { describe, expect, it } from "vitest";
import type { AppRegistryItem } from "../src/api";
import {
  dropTargetIndexFromPointerY,
  orderedDesktopRailApps,
  reorderByTargetIndex,
  sanitizePinnedOrder,
} from "../src/lib/sidebarRailReorder";

function app(app_id: string, frontend_mount = `/apps/${app_id}/`): AppRegistryItem {
  return {
    app_id,
    backend_mount: "",
    description: "",
    distribution_mode: "sealed",
    frontend_mount,
    logo: null,
    name: app_id,
    publisher: "maverick",
    source_access: "none",
    status: "enabled",
    version: "1.0.0",
    provides: [],
    requires: [],
    views: [],
  };
}

describe("sidebar rail reorder model", () => {
  it("reorders an item by final target index without mutating the source", () => {
    const items = ["chat", "agents", "skills"];

    expect(reorderByTargetIndex(items, 0, 2)).toEqual(["agents", "skills", "chat"]);
    expect(reorderByTargetIndex(items, 2, 0)).toEqual(["skills", "chat", "agents"]);
    expect(items).toEqual(["chat", "agents", "skills"]);
  });

  it("sanitizes duplicate, stale, hidden, and static app ids", () => {
    expect(sanitizePinnedOrder(["missing", "CHAT", "chat", "app-store", "agents"], ["chat", "agents", "app-store"])).toEqual([
      "chat",
      "agents",
    ]);
  });

  it("builds the desktop rail from visible pinned apps and keeps App Store static at the end", () => {
    const rail = orderedDesktopRailApps(
      [app("app-store"), app("chat"), app("agents"), app("headless", "")],
      ["app-store", "agents", "missing", "chat"],
    );

    expect(rail.map((item) => item.app_id)).toEqual(["agents", "chat", "app-store"]);
  });

  it("supports an empty pinned list while preserving the static App Store icon", () => {
    expect(orderedDesktopRailApps([app("app-store"), app("chat")], []).map((item) => item.app_id)).toEqual(["app-store"]);
  });

  it("computes an insertion target index from item midpoints", () => {
    const rects = [
      { top: 0, bottom: 40 },
      { top: 50, bottom: 90 },
      { top: 100, bottom: 140 },
    ];

    expect(dropTargetIndexFromPointerY(rects, 10)).toBe(0);
    expect(dropTargetIndexFromPointerY(rects, 60)).toBe(1);
    expect(dropTargetIndexFromPointerY(rects, 115)).toBe(2);
    expect(dropTargetIndexFromPointerY(rects, 150)).toBe(3);
  });

  it("uses drag direction so hovered items swap immediately near the final slots", () => {
    const rects = [
      { top: 50, bottom: 90 },
      { top: 100, bottom: 140 },
      { top: 150, bottom: 190 },
    ];

    expect(dropTargetIndexFromPointerY(rects, 101, "down")).toBe(2);
    expect(dropTargetIndexFromPointerY(rects, 151, "down")).toBe(3);
    expect(dropTargetIndexFromPointerY(rects, 139, "up")).toBe(1);
  });
});
