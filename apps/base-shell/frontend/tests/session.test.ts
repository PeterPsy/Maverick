import { afterEach, describe, expect, it, vi } from "vitest";
import { readShellSession, writeShellSession } from "../src/session";

describe("base-shell session", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("falls back to the v3 shell defaults when storage is unavailable", () => {
    vi.stubGlobal("window", undefined);

    expect(readShellSession()).toEqual({
      activeAppId: "chat",
      isSidebarOpen: true,
      pinnedAppIds: ["chat"],
    });
  });

  it("sanitizes persisted local shell state", () => {
    vi.stubGlobal("window", {
      localStorage: {
        getItem: vi.fn(() =>
          JSON.stringify({
            activeAppId: " docs ",
            isSidebarOpen: false,
            pinnedAppIds: ["chat", "chat", "", "docs"],
          }),
        ),
        setItem: vi.fn(),
      },
    });

    expect(readShellSession()).toEqual({
      activeAppId: "docs",
      isSidebarOpen: false,
      pinnedAppIds: ["chat", "docs"],
    });
  });

  it("writes local shell state without backend coupling", () => {
    const setItem = vi.fn();
    vi.stubGlobal("window", {
      localStorage: {
        getItem: vi.fn(),
        setItem,
      },
    });

    writeShellSession({ activeAppId: "chat", isSidebarOpen: false, pinnedAppIds: ["chat"] });

    expect(setItem).toHaveBeenCalledWith(
      "maverick3:base-shell:session",
      JSON.stringify({ activeAppId: "chat", isSidebarOpen: false, pinnedAppIds: ["chat"] }),
    );
  });
});
