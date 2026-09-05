import { afterEach, describe, expect, it, vi } from "vitest";
import { getActiveProvider, getPlatformStatus, getSession, isRetryableReadError, listApps, listPinnedApps, MaverickHttpError, MaverickTransportError, normalizeAppRegistryPayload, retryAfterMs, savePinnedApps } from "../src/api";
import { buildProviderSetupDraft } from "../src/components/ProviderSetupDialog";
import { shellCacheLifecycle, subscribeShellAuthorizationRevocation } from "../src/pwaCacheRuntime";

describe("base-shell api normalization", () => {
  afterEach(() => {
    vi.useRealTimers();
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

  it("preserves public app identity independently from the workspace binding id", () => {
    const payload = normalizeAppRegistryPayload({
      items: [
        {
          app_id: "workspace-chat",
          public_app_id: "chat",
          frontend_mount: "/apps/workspace-chat/",
          name: "Workspace Chat",
        },
      ],
    });

    expect(payload.items[0]).toMatchObject({
      app_id: "workspace-chat",
      public_app_id: "chat",
    });
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
    expect(fetch).toHaveBeenCalledWith("/api/apps", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal: expect.any(AbortSignal),
    });
  });

  it("aborts a stalled request instead of leaving shell loaders pending", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockImplementation((_input, init) => (
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("The operation was aborted.", "AbortError")),
          { once: true },
        );
      })
    ));

    const assertion = expect(listApps()).rejects.toThrow("Request timed out after 15000 ms: /api/apps");
    await vi.advanceTimersByTimeAsync(15_000);
    await assertion;
  });

  it("classifies transport and explicitly retryable read responses without hiding terminal HTTP", () => {
    const transport = new MaverickTransportError("transport failed");
    const unavailable = new MaverickHttpError("/api/session", new Response(null, {
      status: 503,
      headers: { "Retry-After": "2" },
    }));
    const forbidden = new MaverickHttpError("/api/session", new Response(null, { status: 403 }));
    const unauthenticated = new MaverickHttpError("/api/session", new Response(null, { status: 401 }));

    expect(isRetryableReadError(transport)).toBe(true);
    expect(isRetryableReadError(unavailable)).toBe(true);
    expect(retryAfterMs(unavailable)).toBe(2_000);
    expect(isRetryableReadError(forbidden)).toBe(false);
    expect(isRetryableReadError(unauthenticated)).toBe(false);
  });

  it("cleans browser data scopes on authorization responses", async () => {
    const cleanup = vi.spyOn(shellCacheLifecycle, "authorizationFailure").mockResolvedValue({
      pendingCleanupCount: 0,
      removed: 0,
      status: "complete",
    });
    const revoked = vi.fn();
    const unsubscribe = subscribeShellAuthorizationRevocation(revoked);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 401 }));

    await expect(getSession()).rejects.toMatchObject({ status: 401 });
    expect(revoked).toHaveBeenCalledOnce();
    expect(revoked).toHaveBeenCalledWith(401);
    expect(cleanup).toHaveBeenCalledOnce();
    unsubscribe();
  });

  it.each([401, 403])("preserves a real %i through request, lifecycle cleanup, and retry coordination", async (status) => {
    await shellCacheLifecycle.transition({
      appId: "base-shell",
      userId: "auth-regression-user",
      workspaceId: "default",
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status }));
    const controller = new AbortController();

    const pending = getSession(controller.signal, "base-shell:test-auth-terminal");

    await expect(pending).rejects.toBeInstanceOf(MaverickHttpError);
    await expect(pending).rejects.toMatchObject({ status });
  });

  it("retries shell GETs only through the SDK-owned concrete request", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("transport interrupted"))
      .mockResolvedValueOnce(new Response(JSON.stringify({ authenticated: false }), {
        headers: { "Content-Type": "application/json" },
      }));

    const pending = getSession(new AbortController().signal, "base-shell:test-session-retry");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    await vi.advanceTimersByTimeAsync(2_000);

    await expect(pending).resolves.toEqual({ authenticated: false });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const [target, init] of fetchMock.mock.calls) {
      expect(target).toBe("/api/session");
      expect(init).toMatchObject({
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        method: "GET",
        redirect: "error",
        signal: expect.any(AbortSignal),
      });
      expect(init?.body).toBeUndefined();
    }
  });

  it("keeps POST read actions one-shot when they have no mutation deduplication contract", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValue(new TypeError("transport interrupted"));

    await expect(listPinnedApps()).rejects.toBeInstanceOf(MaverickTransportError);
    await vi.runAllTimersAsync();

    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("does not let delayed authorization cleanup reclassify an HTTP response as a timeout", async () => {
    vi.useFakeTimers();
    const pendingCleanup = deferred<Awaited<ReturnType<typeof shellCacheLifecycle.authorizationFailure>>>();
    vi.spyOn(shellCacheLifecycle, "authorizationFailure").mockReturnValue(pendingCleanup.promise);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 403 }));

    const observed = getSession().catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(15_000);
    pendingCleanup.resolve({ pendingCleanupCount: 0, removed: 0, status: "complete" });

    const error = await observed;
    expect(error).toBeInstanceOf(MaverickHttpError);
    expect(error).toMatchObject({ status: 403 });
    expect(error).not.toBeInstanceOf(MaverickTransportError);
  });

  it("reads and saves ordered pinned apps through the App Store backend", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ pinned_apps: ["chat", "agents"] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ state: { pinned_apps: ["agents", "chat"] } }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

    await expect(listPinnedApps()).resolves.toEqual({ pinned_apps: ["chat", "agents"] });
    await expect(savePinnedApps([" agents ", "", "chat"])).resolves.toEqual({ pinned_apps: ["agents", "chat"] });
    expect(fetch).toHaveBeenNthCalledWith(1, "/api/apps/app-store/backend", {
      credentials: "same-origin",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      method: "POST",
      body: JSON.stringify({ action: "pinned_apps.list" }),
      signal: expect.any(AbortSignal),
    });
    const saveInit = vi.mocked(fetch).mock.calls[1]?.[1];
    const saveBody = JSON.parse(String(saveInit?.body)) as Record<string, unknown>;
    expect(saveInit).toMatchObject({
      credentials: "same-origin",
      headers: expect.objectContaining({
        Accept: "application/json",
        "Content-Type": "application/json",
        "Idempotency-Key": saveBody.idempotency_key,
      }),
      method: "POST",
      signal: expect.any(AbortSignal),
    });
    expect(saveBody).toMatchObject({
      action: "pinned_apps.set",
      app_ids: ["agents", "chat"],
      request_fingerprint: expect.stringMatching(/^sha256:[0-9a-f]{64}$/),
    });
  });

  it("retries the real pinned-app mutation with one stable server deduplication contract", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("transport interrupted after send"))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ state: { pinned_apps: ["chat", "agents"] } }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );

    const pending = savePinnedApps(["chat", "agents"]);
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(2_000);
    await expect(pending).resolves.toEqual({ pinned_apps: ["chat", "agents"] });

    const attempts = vi.mocked(fetch).mock.calls;
    expect(attempts).toHaveLength(2);
    expect(attempts[0]?.[1]?.body).toBe(attempts[1]?.[1]?.body);
    expect((attempts[0]?.[1]?.headers as Record<string, string>)["Idempotency-Key"])
      .toBe((attempts[1]?.[1]?.headers as Record<string, string>)["Idempotency-Key"]);
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
        user_id: "settings",
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}
