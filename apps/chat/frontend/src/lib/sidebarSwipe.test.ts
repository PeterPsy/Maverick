import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { isHorizontalIntent, isSidebarCloseSwipe } from "./sidebarSwipe";

const currentDir = dirname(fileURLToPath(import.meta.url));

describe("mobile sidebar swipe", () => {
  it("accepts a leftward swipe for closing the sidebar from anywhere", () => {
    expect(isSidebarCloseSwipe({ x: 210, y: 420 }, { x: 120, y: 424 })).toBe(true);
    expect(isSidebarCloseSwipe({ x: 350, y: 80 }, { x: 260, y: 84 })).toBe(true);
    expect(isSidebarCloseSwipe({ x: 210, y: 420 }, { x: 300, y: 424 })).toBe(false);
  });

  it("detects horizontal gesture intent before taking over scrolling", () => {
    expect(isHorizontalIntent({ x: 10, y: 420 }, { x: 28, y: 424 })).toBe(true);
    expect(isHorizontalIntent({ x: 10, y: 420 }, { x: 16, y: 450 })).toBe(false);
  });

  it("does not wire an open swipe gesture into the chat app frame", () => {
    const appSource = readFileSync(resolve(currentDir, "../App.tsx"), "utf8");
    const closeSwipeSource = readFileSync(resolve(currentDir, "../hooks/useShellSidebarCloseSwipe.ts"), "utf8");

    expect(appSource).not.toContain("useShellSidebarSwipe");
    expect(closeSwipeSource).not.toContain("maverick.shell.sidebar.open");
  });
});
