import { afterEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_FLOATING_CHAT_WIDTH_PX,
  DEFAULT_SIDEBAR_DETAILS_WIDTH_PX,
  MAX_SIDEBAR_DETAILS_WIDTH_PX,
  MIN_SIDEBAR_DETAILS_WIDTH_PX,
  clampFloatingChatWidth,
  clampSidebarDetailsWidth,
  readShellSession,
  resolveInitialSidebarOpen,
  writeShellSession,
} from "../src/session";
import type { ShellSession } from "../src/session";

function shellSession(overrides: Partial<ShellSession> = {}): ShellSession {
  return {
    activeAppId: "chat",
    floatingChatMode: "overlay",
    floatingChatNavigationScope: null,
    floatingChatThreadId: null,
    floatingChatWidthPx: DEFAULT_FLOATING_CHAT_WIDTH_PX,
    isSidebarOpen: false,
    sidebarDetailsWidthPx: DEFAULT_SIDEBAR_DETAILS_WIDTH_PX,
    sidebarMode: "rail",
    themeMode: "dark",
    ...overrides,
  };
}

describe("base-shell session", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("falls back to the shell defaults when storage is unavailable", () => {
    vi.stubGlobal("window", undefined);

    expect(readShellSession()).toEqual({
      activeAppId: "chat",
      floatingChatMode: "overlay",
      floatingChatNavigationScope: null,
      floatingChatThreadId: null,
      floatingChatWidthPx: DEFAULT_FLOATING_CHAT_WIDTH_PX,
      isSidebarOpen: false,
      sidebarDetailsWidthPx: DEFAULT_SIDEBAR_DETAILS_WIDTH_PX,
      sidebarMode: "rail",
      themeMode: "dark",
    });
  });

  it("sanitizes persisted local shell state", () => {
    vi.stubGlobal("window", {
      localStorage: {
        getItem: vi.fn(() =>
          JSON.stringify({
            activeAppId: " docs ",
            floatingChatMode: "fixed-right",
            floatingChatNavigationScope: " window-1 ",
            floatingChatThreadId: " thread-1 ",
            floatingChatWidthPx: 480.3,
            isSidebarOpen: false,
            sidebarDetailsWidthPx: 420.4,
            sidebarMode: "fixed",
            themeMode: "light",
          }),
        ),
        setItem: vi.fn(),
      },
    });

    expect(readShellSession()).toEqual({
      activeAppId: "docs",
      floatingChatMode: "fixed-right",
      floatingChatNavigationScope: "window-1",
      floatingChatThreadId: "thread-1",
      floatingChatWidthPx: 480,
      isSidebarOpen: false,
      sidebarDetailsWidthPx: 420,
      sidebarMode: "fixed",
      themeMode: "light",
    });
  });

  it("clamps persisted sidebar width to the desktop contract", () => {
    expect(clampSidebarDetailsWidth(120, 1200)).toBe(MIN_SIDEBAR_DETAILS_WIDTH_PX);
    expect(clampSidebarDetailsWidth(800, 1200)).toBe(MAX_SIDEBAR_DETAILS_WIDTH_PX);
    expect(clampSidebarDetailsWidth(560, 980)).toBe(440);
  });

  it("clamps persisted floating chat width to the right dock contract", () => {
    expect(clampFloatingChatWidth(120, 1400)).toBe(360);
    expect(clampFloatingChatWidth(900, 1400)).toBe(720);
    expect(clampFloatingChatWidth(720, 1040)).toBe(480);
  });

  it("writes local shell state without backend coupling", () => {
    const setItem = vi.fn();
    vi.stubGlobal("window", {
      localStorage: {
        getItem: vi.fn(),
        setItem,
      },
    });

    writeShellSession(shellSession());

    expect(setItem).toHaveBeenCalledWith(
      "maverick:base-shell:session",
      JSON.stringify({
        activeAppId: "chat",
        floatingChatMode: "overlay",
        floatingChatNavigationScope: null,
        floatingChatThreadId: null,
        floatingChatWidthPx: DEFAULT_FLOATING_CHAT_WIDTH_PX,
        isSidebarOpen: false,
        sidebarDetailsWidthPx: DEFAULT_SIDEBAR_DETAILS_WIDTH_PX,
        sidebarMode: "rail",
        themeMode: "dark",
      }),
    );
  });

  it("starts with the sidebar closed on mobile even when the local session was open or fixed", () => {
    expect(
      resolveInitialSidebarOpen(
        shellSession({
          activeAppId: "memory",
          isSidebarOpen: true,
          sidebarMode: "rail",
        }),
        { isInitialChatLaunch: false, isMobileLayout: true },
      ),
    ).toBe(false);
    expect(
      resolveInitialSidebarOpen(
        shellSession({
          activeAppId: "memory",
          sidebarMode: "fixed",
        }),
        { isInitialChatLaunch: false, isMobileLayout: true },
      ),
    ).toBe(false);
  });

  it("keeps desktop fixed sidebars open at startup", () => {
    expect(
      resolveInitialSidebarOpen(
        shellSession({
          activeAppId: "memory",
          sidebarMode: "fixed",
        }),
        { isInitialChatLaunch: false, isMobileLayout: false },
      ),
    ).toBe(true);
  });
});
