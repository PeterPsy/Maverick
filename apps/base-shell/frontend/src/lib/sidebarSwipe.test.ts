import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  isHorizontalIntent,
  isSidebarCloseSwipe,
} from "./sidebarSwipe";

const currentDir = dirname(fileURLToPath(import.meta.url));

describe("base shell mobile sidebar swipe", () => {
  it("keeps the existing leftward close swipe behavior", () => {
    expect(isSidebarCloseSwipe({ x: 210, y: 420 }, { x: 120, y: 424 })).toBe(true);
    expect(isSidebarCloseSwipe({ x: 210, y: 420 }, { x: 120, y: 500 })).toBe(false);
    expect(isSidebarCloseSwipe({ x: 210, y: 420 }, { x: 300, y: 424 })).toBe(false);
  });

  it("detects horizontal gesture intent before taking over scrolling", () => {
    expect(isHorizontalIntent({ x: 10, y: 420 }, { x: 28, y: 424 })).toBe(true);
    expect(isHorizontalIntent({ x: 10, y: 420 }, { x: 16, y: 450 })).toBe(false);
  });

  it("does not wire a left-edge open swipe into the base shell render path", () => {
    const appShellSource = readFileSync(resolve(currentDir, "../AppShell.tsx"), "utf8");
    const layoutStyles = readFileSync(resolve(currentDir, "../styles/layout.css"), "utf8");

    expect(appShellSource).not.toContain("useMobileSidebarOpenSwipe");
    expect(appShellSource).not.toContain("bs-mobile-sidebar-swipe-edge");
    expect(layoutStyles).not.toContain("bs-mobile-sidebar-swipe-edge");
  });
});
