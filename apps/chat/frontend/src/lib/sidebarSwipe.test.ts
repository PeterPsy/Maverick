import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { isSidebarCloseSwipe, isSidebarOpenSwipe, startsInSidebarSwipeZone } from "./sidebarSwipe";

const mobileViewport = { width: 390, height: 844 };
const currentDir = dirname(fileURLToPath(import.meta.url));

describe("mobile sidebar swipe", () => {
  it("accepts a rightward horizontal swipe that starts on the left side", () => {
    expect(isSidebarOpenSwipe({ x: 40, y: 420 }, { x: 130, y: 428 }, mobileViewport)).toBe(true);
  });

  it("ignores swipes that start away from the left side", () => {
    expect(startsInSidebarSwipeZone({ x: 260, y: 420 }, mobileViewport)).toBe(false);
    expect(isSidebarOpenSwipe({ x: 260, y: 420 }, { x: 350, y: 424 }, mobileViewport)).toBe(false);
  });

  it("ignores vertical scrolling and leftward movement", () => {
    expect(isSidebarOpenSwipe({ x: 40, y: 420 }, { x: 120, y: 510 }, mobileViewport)).toBe(false);
    expect(isSidebarOpenSwipe({ x: 120, y: 420 }, { x: 40, y: 420 }, mobileViewport)).toBe(false);
  });

  it("accepts the opposite leftward swipe for closing the sidebar from anywhere", () => {
    expect(isSidebarCloseSwipe({ x: 210, y: 420 }, { x: 120, y: 424 }, mobileViewport)).toBe(true);
    expect(isSidebarCloseSwipe({ x: 350, y: 80 }, { x: 260, y: 84 }, mobileViewport)).toBe(true);
    expect(isSidebarCloseSwipe({ x: 210, y: 420 }, { x: 300, y: 424 }, mobileViewport)).toBe(false);
  });

  it("wires the open swipe gesture into the chat app frame", () => {
    const appSource = readFileSync(resolve(currentDir, "../App.tsx"), "utf8");

    expect(appSource).toContain('import { useShellSidebarSwipe } from "./hooks/useShellSidebarSwipe";');
    expect(appSource).toContain("useShellSidebarSwipe();");
  });
});
