import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  isHorizontalIntent,
  isSidebarCloseSwipe,
  isSidebarOpenSwipe,
  sidebarOpenSwipeEdgeWidth,
  startsInSidebarOpenSwipeZone,
} from "./sidebarSwipe";

const mobileViewport = { width: 390, height: 844 };
const currentDir = dirname(fileURLToPath(import.meta.url));

describe("base shell mobile sidebar swipe", () => {
  it("uses a narrow left edge zone for opening the mobile sidebar", () => {
    expect(sidebarOpenSwipeEdgeWidth(mobileViewport)).toBeCloseTo(62.4);
    expect(startsInSidebarOpenSwipeZone({ x: 8, y: 420 }, mobileViewport)).toBe(true);
    expect(startsInSidebarOpenSwipeZone({ x: 80, y: 420 }, mobileViewport)).toBe(false);
  });

  it("accepts a rightward swipe from the left edge", () => {
    expect(isSidebarOpenSwipe({ x: 10, y: 420 }, { x: 92, y: 428 }, mobileViewport)).toBe(true);
  });

  it("ignores vertical scrolling, short movement, and non-edge starts", () => {
    expect(isSidebarOpenSwipe({ x: 10, y: 420 }, { x: 92, y: 500 }, mobileViewport)).toBe(false);
    expect(isSidebarOpenSwipe({ x: 10, y: 420 }, { x: 70, y: 420 }, mobileViewport)).toBe(false);
    expect(isSidebarOpenSwipe({ x: 120, y: 420 }, { x: 210, y: 424 }, mobileViewport)).toBe(false);
  });

  it("keeps the existing leftward close swipe behavior", () => {
    expect(isSidebarCloseSwipe({ x: 210, y: 420 }, { x: 120, y: 424 })).toBe(true);
    expect(isSidebarCloseSwipe({ x: 210, y: 420 }, { x: 120, y: 500 })).toBe(false);
    expect(isSidebarCloseSwipe({ x: 210, y: 420 }, { x: 300, y: 424 })).toBe(false);
  });

  it("detects horizontal gesture intent before taking over scrolling", () => {
    expect(isHorizontalIntent({ x: 10, y: 420 }, { x: 28, y: 424 })).toBe(true);
    expect(isHorizontalIntent({ x: 10, y: 420 }, { x: 16, y: 450 })).toBe(false);
  });

  it("wires the open gesture into the base shell render path", () => {
    const appShellSource = readFileSync(resolve(currentDir, "../AppShell.tsx"), "utf8");

    expect(appShellSource).toContain('import { useMobileSidebarOpenSwipe } from "./hooks/useMobileSidebarOpenSwipe";');
    expect(appShellSource).toContain("useMobileSidebarOpenSwipe({");
    expect(appShellSource).toContain('className="bs-mobile-sidebar-swipe-edge"');
  });
});
