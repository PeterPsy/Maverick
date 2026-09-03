import { afterEach, describe, expect, it, vi } from "vitest";
import { readMaverickAppFrameContext } from "../src";

describe("isolated app-frame context", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("returns the host-injected app and workspace scope", () => {
    vi.stubGlobal("window", {
      __MAVERICK_APP_FRAME_CONTEXT__: Object.freeze({
        app_id: "fitness-coach",
        workspace_id: "default",
      }),
      location: { search: "?workspace_id=attacker" },
    });

    expect(readMaverickAppFrameContext()).toEqual({
      appId: "fitness-coach",
      workspaceId: "default",
    });
  });

  it("fails closed when the injected scope is absent or malformed", () => {
    vi.stubGlobal("window", { location: { search: "?workspace_id=default" } });
    expect(readMaverickAppFrameContext()).toBeNull();

    vi.stubGlobal("window", {
      __MAVERICK_APP_FRAME_CONTEXT__: {
        app_id: "fitness-coach",
        workspace_id: " default",
      },
    });
    expect(readMaverickAppFrameContext()).toBeNull();
  });
});
