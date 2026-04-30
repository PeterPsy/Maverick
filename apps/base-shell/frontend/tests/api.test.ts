import { afterEach, describe, expect, it, vi } from "vitest";
import { getActiveProvider, getPlatformStatus, getSession, listApps, normalizeAppRegistryPayload } from "../src/api";
import { buildProviderSetupDraft } from "../src/components/ProviderSetupDialog";

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

  it("reads app registry through the platform endpoint", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ items: [{ app_id: "chat", name: "Chat", frontend_mount: "/apps/chat/" }] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(listApps()).resolves.toEqual({
      items: [expect.objectContaining({ app_id: "chat", name: "Chat" })],
    });
    expect(fetch).toHaveBeenCalledWith("/api/apps", { credentials: "same-origin", headers: { Accept: "application/json" } });
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

  it("reads session and provider surfaces from core APIs", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ authenticated: true, user: { username: "admin" }, workspace_id: "default" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ workspace_id: "default", active_provider: { provider_id: "codex", label: "Codex" } }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

    await expect(getSession()).resolves.toMatchObject({ authenticated: true, workspace_id: "default" });
    await expect(getActiveProvider()).resolves.toMatchObject({ active_provider: { provider_id: "codex" } });
  });

  it("prefills provider setup from available providers when no provider is active", () => {
    const draft = buildProviderSetupDraft({
      user: {
        user_id: "user-admin",
        username: "admin",
        email: null,
        display_name: null,
        account_type: "standard",
        platform_role: "admin",
      },
      workspace: {
        workspace_id: "default",
        name: "Default",
        description: null,
        status: "active",
        governance: {},
        quota: {},
        is_active: true,
      },
      provider: {
        workspace_id: "default",
        active_provider: null,
        selection: null,
        model_settings: null,
        blocked_reason: "no_provider_configured",
        available_providers: [
          {
            provider_id: "codex",
            label: "Codex",
            description: "Codex runtime",
            status: "available",
            default_model_family: "gpt-5.2",
            model_options: [
              {
                model_id: "gpt-5.2",
                label: "GPT-5.2",
                description: null,
                default_reasoning_effort: "medium",
                supported_reasoning_efforts: [],
              },
            ],
            capabilities: {},
          },
        ],
      },
      runtime: {
        workspace_id: "default",
        active_provider: null,
        selection: null,
        model_settings: null,
        sessions: [],
      },
      recovery: {},
    });

    expect(draft).toEqual({
      providerId: "codex",
      modelId: "gpt-5.2",
      reasoningEffort: "medium",
    });
  });
});
