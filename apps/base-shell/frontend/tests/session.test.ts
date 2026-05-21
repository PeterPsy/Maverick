import { afterEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_SIDEBAR_DETAILS_WIDTH_PX,
  MAX_SIDEBAR_DETAILS_WIDTH_PX,
  MIN_SIDEBAR_DETAILS_WIDTH_PX,
  clampSidebarDetailsWidth,
  readShellSession,
  resolveInitialSidebarOpen,
  writeShellSession,
} from "../src/session";

describe("base-shell session", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("falls back to the shell defaults when storage is unavailable", () => {
    vi.stubGlobal("window", undefined);

    expect(readShellSession()).toEqual({
      activeAppId: "chat",
      isSidebarOpen: false,
      sidebarDetailsWidthPx: DEFAULT_SIDEBAR_DETAILS_WIDTH_PX,
      sidebarMode: "rail",
    });
  });

  it("sanitizes persisted local shell state", () => {
    vi.stubGlobal("window", {
      localStorage: {
        getItem: vi.fn(() =>
          JSON.stringify({
            activeAppId: " docs ",
            isSidebarOpen: false,
            sidebarDetailsWidthPx: 420.4,
            sidebarMode: "fixed",
          }),
        ),
        setItem: vi.fn(),
      },
    });

    expect(readShellSession()).toEqual({
      activeAppId: "docs",
      isSidebarOpen: false,
      sidebarDetailsWidthPx: 420,
      sidebarMode: "fixed",
    });
  });

  it("clamps persisted sidebar width to the desktop contract", () => {
    expect(clampSidebarDetailsWidth(120, 1200)).toBe(MIN_SIDEBAR_DETAILS_WIDTH_PX);
    expect(clampSidebarDetailsWidth(800, 1200)).toBe(MAX_SIDEBAR_DETAILS_WIDTH_PX);
    expect(clampSidebarDetailsWidth(560, 980)).toBe(440);
  });

  it("writes local shell state without backend coupling", () => {
    const setItem = vi.fn();
    vi.stubGlobal("window", {
      localStorage: {
        getItem: vi.fn(),
        setItem,
      },
    });

    writeShellSession({
      activeAppId: "chat",
      isSidebarOpen: false,
      sidebarDetailsWidthPx: DEFAULT_SIDEBAR_DETAILS_WIDTH_PX,
      sidebarMode: "rail",
    });

    expect(setItem).toHaveBeenCalledWith(
      "maverick:base-shell:session",
      JSON.stringify({
        activeAppId: "chat",
        isSidebarOpen: false,
        sidebarDetailsWidthPx: DEFAULT_SIDEBAR_DETAILS_WIDTH_PX,
        sidebarMode: "rail",
      }),
    );
  });

  it("starts with the sidebar closed on mobile even when the local session was open or fixed", () => {
    expect(
      resolveInitialSidebarOpen(
        {
          activeAppId: "memory",
          isSidebarOpen: true,
          sidebarDetailsWidthPx: DEFAULT_SIDEBAR_DETAILS_WIDTH_PX,
          sidebarMode: "rail",
        },
        { isInitialChatLaunch: false, isMobileLayout: true },
      ),
    ).toBe(false);
    expect(
      resolveInitialSidebarOpen(
        {
          activeAppId: "memory",
          isSidebarOpen: false,
          sidebarDetailsWidthPx: DEFAULT_SIDEBAR_DETAILS_WIDTH_PX,
          sidebarMode: "fixed",
        },
        { isInitialChatLaunch: false, isMobileLayout: true },
      ),
    ).toBe(false);
  });

  it("keeps desktop fixed sidebars open at startup", () => {
    expect(
      resolveInitialSidebarOpen(
        {
          activeAppId: "memory",
          isSidebarOpen: false,
          sidebarDetailsWidthPx: DEFAULT_SIDEBAR_DETAILS_WIDTH_PX,
          sidebarMode: "fixed",
        },
        { isInitialChatLaunch: false, isMobileLayout: false },
      ),
    ).toBe(true);
  });
});
