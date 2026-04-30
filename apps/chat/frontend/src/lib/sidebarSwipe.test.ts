import { describe, expect, it } from "vitest";
import { isSidebarCloseSwipe, isSidebarOpenSwipe, startsInSidebarSwipeZone } from "./sidebarSwipe";

const mobileViewport = { width: 390, height: 844 };

describe("mobile sidebar swipe", () => {
  it("accepts a rightward horizontal swipe that starts near the viewport center", () => {
    expect(isSidebarOpenSwipe({ x: 180, y: 420 }, { x: 270, y: 428 }, mobileViewport)).toBe(true);
  });

  it("ignores swipes that start at the viewport edge", () => {
    expect(startsInSidebarSwipeZone({ x: 20, y: 420 }, mobileViewport)).toBe(false);
    expect(isSidebarOpenSwipe({ x: 20, y: 420 }, { x: 140, y: 424 }, mobileViewport)).toBe(false);
  });

  it("ignores vertical scrolling and leftward movement", () => {
    expect(isSidebarOpenSwipe({ x: 180, y: 420 }, { x: 260, y: 510 }, mobileViewport)).toBe(false);
    expect(isSidebarOpenSwipe({ x: 180, y: 420 }, { x: 90, y: 420 }, mobileViewport)).toBe(false);
  });

  it("accepts the opposite leftward swipe for closing the sidebar from anywhere", () => {
    expect(isSidebarCloseSwipe({ x: 210, y: 420 }, { x: 120, y: 424 }, mobileViewport)).toBe(true);
    expect(isSidebarCloseSwipe({ x: 350, y: 80 }, { x: 260, y: 84 }, mobileViewport)).toBe(true);
    expect(isSidebarCloseSwipe({ x: 210, y: 420 }, { x: 300, y: 424 }, mobileViewport)).toBe(false);
  });
});
