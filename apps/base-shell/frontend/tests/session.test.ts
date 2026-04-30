import { afterEach, describe, expect, it, vi } from "vitest";
import { readShellSession, writeShellSession } from "../src/session";

describe("base-shell session", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("falls back to the shell defaults when storage is unavailable", () => {
    vi.stubGlobal("window", undefined);

    expect(readShellSession()).toEqual({
      activeAppId: null,
      isSidebarOpen: true,
    });
  });

  it("sanitizes persisted local shell state", () => {
    vi.stubGlobal("window", {
      localStorage: {
        getItem: vi.fn(() =>
          JSON.stringify({
            activeAppId: " docs ",
            isSidebarOpen: false,
          }),
        ),
        setItem: vi.fn(),
      },
    });

    expect(readShellSession()).toEqual({
      activeAppId: "docs",
      isSidebarOpen: false,
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

    writeShellSession({ activeAppId: "chat", isSidebarOpen: false });

    expect(setItem).toHaveBeenCalledWith(
      "maverick:base-shell:session",
      JSON.stringify({ activeAppId: "chat", isSidebarOpen: false }),
    );
  });
});
