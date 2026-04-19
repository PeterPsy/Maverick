import { afterEach, describe, expect, it, vi } from "vitest";
import { getPlatformStatus, listApps, normalizeAppRegistryPayload } from "../src/api";

describe("base-shell api normalization", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("normalizes sparse registry records without inventing optional apps", () => {
    const payload = normalizeAppRegistryPayload({
      items: [
        {
          app_id: "chat",
          frontend_mount: "/apps/chat/",
          name: "Chat",
          views: ["chat"],
        },
        {
          name: "missing id",
        },
      ],
    });

    expect(payload.items).toEqual([
      expect.objectContaining({
        app_id: "chat",
        backend_mount: "",
        distribution_mode: "unknown",
        frontend_mount: "/apps/chat/",
        logo: null,
        status: "unknown",
        views: ["chat"],
      }),
    ]);
  });

  it("reads app registry through the v3 platform endpoint", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ items: [{ app_id: "chat", name: "Chat", frontend_mount: "/apps/chat/" }] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(listApps()).resolves.toEqual({
      items: [expect.objectContaining({ app_id: "chat", name: "Chat" })],
    });
    expect(fetch).toHaveBeenCalledWith("/api/apps", { headers: { Accept: "application/json" } });
  });

  it("normalizes platform status app records", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ apps: [{ app_id: "chat", name: "Chat" }], status: "ok", workspace_id: "default" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(getPlatformStatus()).resolves.toEqual({
      apps: [expect.objectContaining({ app_id: "chat" })],
      status: "ok",
      workspace_id: "default",
    });
  });
});
