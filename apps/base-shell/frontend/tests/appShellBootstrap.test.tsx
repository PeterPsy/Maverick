// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createSafeRequestRetryExecutor } from "@maverick/pwa-cache";
import { MaverickHttpError } from "../src/api";
import type { AppRegistryItem, PlatformSettings, SessionPayload, WorkspaceItem } from "../src/api";
import { AppShell } from "../src/AppShell";
import { revokeShellAuthorization, shellCacheLifecycle, shellRetryCoordinator } from "../src/pwaCacheRuntime";

const api = vi.hoisted(() => ({
  configureActiveProvider: vi.fn(),
  createWorkspace: vi.fn(),
  getPlatformSettings: vi.fn(),
  getProviderSetupSettings: vi.fn(),
  getPlatformStatus: vi.fn(),
  getSession: vi.fn(),
  listApps: vi.fn(),
  listPinnedApps: vi.fn(),
  listWorkspaces: vi.fn(),
  logout: vi.fn(),
  savePinnedApps: vi.fn(),
  switchWorkspace: vi.fn(),
}));
const dataCacheBrokerHost = vi.hoisted(() => ({
  frameScope: null as null | { sessionGeneration: string; workspaceId: string },
  principal: null as null | { sessionExpiresAt: string; userId: string; workspaceId: string },
}));

vi.mock("../src/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api")>();
  return {
    ...actual,
    configureActiveProvider: api.configureActiveProvider,
    createWorkspace: api.createWorkspace,
    getPlatformSettings: api.getPlatformSettings,
    getProviderSetupSettings: api.getProviderSetupSettings,
    getPlatformStatus: api.getPlatformStatus,
    getSession: api.getSession,
    listApps: api.listApps,
    listPinnedApps: api.listPinnedApps,
    listWorkspaces: api.listWorkspaces,
    logout: api.logout,
    savePinnedApps: api.savePinnedApps,
    switchWorkspace: api.switchWorkspace,
  };
});
vi.mock("../src/usePwaDataCacheBrokerHost", () => ({
  usePwaDataCacheBrokerHost: (options: {
    frameScope: null | { sessionGeneration: string; workspaceId: string };
    principal: null | { sessionExpiresAt: string; userId: string; workspaceId: string };
  }) => {
    dataCacheBrokerHost.frameScope = options.frameScope;
    dataCacheBrokerHost.principal = options.principal;
  },
}));

vi.mock("../src/components/WorkspaceView", () => ({
  WorkspaceView: ({ activeWorkspaceId, isLoading }: { activeWorkspaceId: string; isLoading: boolean }) => (
    <div data-loading={String(isLoading)} data-testid="workspace-view" data-workspace-id={activeWorkspaceId}>
      <iframe data-testid="mounted-app-frame" title="Mounted app" />
    </div>
  ),
}));
vi.mock("../src/components/Sidebar", () => ({
  Sidebar: ({
    isLoading,
    isWorkspacesLoading,
    onReorderPinnedApps,
    onWorkspaceChange,
    pinnedAppIds,
    workspaces,
  }: {
    isLoading: boolean;
    isWorkspacesLoading: boolean;
    onReorderPinnedApps: (appIds: string[]) => Promise<void>;
    onWorkspaceChange: (workspaceId: string) => Promise<void>;
    pinnedAppIds: string[];
    workspaces: WorkspaceItem[];
  }) => (
    <aside
      data-apps-loading={String(isLoading)}
      data-pinned-apps={JSON.stringify(pinnedAppIds)}
      data-testid="sidebar"
      data-workspace-count={String(workspaces.length)}
      data-workspaces-loading={String(isWorkspacesLoading)}
    >
      <button data-testid="reorder-pins" onClick={() => void onReorderPinnedApps(["mail", "crm", "chat"])} type="button" />
      <button data-testid="switch-workspace" onClick={() => void onWorkspaceChange("other")} type="button" />
    </aside>
  ),
}));
vi.mock("../src/components/FloatingChatHost", () => ({
  FloatingChatHost: () => <div data-testid="floating-chat-host" />,
}));
vi.mock("../src/components/LoginScreen", () => ({
  LoginScreen: ({ onAuthenticated }: { onAuthenticated: () => void }) => (
    <div data-testid="login-screen">
      <button data-testid="retry-authenticated-bootstrap" onClick={onAuthenticated} type="button" />
    </div>
  ),
}));
vi.mock("../src/components/ProviderSetupDialog", () => ({
  ProviderSetupDialog: () => <div data-testid="provider-setup" />,
}));

describe("AppShell bootstrap", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.clearAllMocks();
    dataCacheBrokerHost.frameScope = null;
    dataCacheBrokerHost.principal = null;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    shellRetryCoordinator.cancelAll("test reset");
    api.getSession.mockResolvedValue(sessionPayload());
    api.listApps.mockResolvedValue({ items: [app("chat")] });
    api.listPinnedApps.mockResolvedValue({ pinned_apps: ["chat"] });
    api.listWorkspaces.mockResolvedValue({ active_workspace_id: "default", items: [workspace("default")] });
    api.getPlatformSettings.mockRejectedValue(new Error("/api/settings/platform should not be part of shell bootstrap"));
    api.getProviderSetupSettings.mockResolvedValue(platformSettings());
    api.getPlatformStatus.mockRejectedValue(new Error("/api/status should not be part of shell bootstrap"));
    api.createWorkspace.mockResolvedValue(workspace("created"));
    api.switchWorkspace.mockResolvedValue({ active_workspace_id: "other" });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  async function renderShell() {
    await act(async () => {
      root.render(<AppShell />);
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  it("shows the shell from session workspace without waiting for platform status", async () => {
    await act(async () => {
      root.render(<AppShell />);
      await Promise.resolve();
      await Promise.resolve();
    });

    const view = container.querySelector("[data-testid='workspace-view']");
    expect(view?.getAttribute("data-workspace-id")).toBe("default");
    expect(view?.getAttribute("data-loading")).toBe("false");
    expect(api.getPlatformStatus).not.toHaveBeenCalled();
    expect(api.getPlatformSettings).not.toHaveBeenCalled();
    expect(api.getProviderSetupSettings).toHaveBeenCalled();
  });

  it("keeps app and workspace navigation usable while optional app and provider state stalls", async () => {
    api.listPinnedApps.mockReturnValue(new Promise(() => undefined));
    api.getProviderSetupSettings.mockReturnValue(new Promise(() => undefined));

    await act(async () => {
      root.render(<AppShell />);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    const view = container.querySelector("[data-testid='workspace-view']");
    const sidebar = container.querySelector("[data-testid='sidebar']");
    expect(view?.getAttribute("data-loading")).toBe("false");
    expect(sidebar?.getAttribute("data-apps-loading")).toBe("false");
    expect(sidebar?.getAttribute("data-workspaces-loading")).toBe("false");
    expect(sidebar?.getAttribute("data-workspace-count")).toBe("1");
    expect(api.listPinnedApps).toHaveBeenCalledOnce();
    expect(api.listWorkspaces).toHaveBeenCalledOnce();
  });

  it("keeps the normal shell tree mounted after a transport failure hint", async () => {
    await act(async () => {
      root.render(<AppShell />);
      await Promise.resolve();
      await Promise.resolve();
    });

    const view = container.querySelector("[data-testid='workspace-view']");
    const sidebar = container.querySelector("[data-testid='sidebar']");
    const appFrame = container.querySelector("[data-testid='mounted-app-frame']");

    await act(async () => {
      shellRetryCoordinator.hint();
      await Promise.resolve();
    });

    expect(container.querySelector("[data-testid='workspace-view']")).toBe(view);
    expect(container.querySelector("[data-testid='sidebar']")).toBe(sidebar);
    expect(container.querySelector("[data-testid='mounted-app-frame']")).toBe(appFrame);
    expect(container.querySelector("[data-testid='login-screen']")).toBeNull();
  });

  it("bootstraps authenticated shell state after confirmed transport recovery", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("transport interrupted"))
      .mockResolvedValueOnce(jsonResponse(sessionPayload()));
    api.getSession.mockImplementation((signal: AbortSignal, retryKey: string) => (
      shellRetryCoordinator.runRequest({
        executor: createSafeRequestRetryExecutor({ endpoint: "/api/session" }),
        key: retryKey,
        signal,
      })
    ));

    await act(async () => {
      root.render(<AppShell />);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.getSession).toHaveBeenCalledOnce();
    expect(container.querySelector("[data-testid='workspace-view']")).toBeNull();
    expect(container.querySelector("[aria-label='Loading workspace']")).not.toBeNull();
    expect(container.querySelector("[data-testid='login-screen']")).toBeNull();

    await act(async () => {
      shellRetryCoordinator.confirmUsefulTransport();
      await vi.advanceTimersByTimeAsync(250);
    });

    expect(api.getSession).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(container.querySelector("[data-testid='workspace-view']")?.getAttribute("data-workspace-id")).toBe("default");
    expect(container.querySelector("[data-testid='login-screen']")).toBeNull();
  });

  it("keeps deferred workspace state loading and retries it after transport recovery", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("transport interrupted"))
      .mockResolvedValueOnce(jsonResponse({ items: [workspace("recovered")] }));
    api.listWorkspaces.mockImplementation((signal: AbortSignal, retryKey: string) => (
      shellRetryCoordinator.runRequest({
        executor: createSafeRequestRetryExecutor({ endpoint: "/api/workspaces" }),
        key: retryKey,
        signal,
      })
    ));

    await act(async () => {
      root.render(<AppShell />);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.querySelector("[data-testid='sidebar']")?.getAttribute("data-workspaces-loading")).toBe("true");
    expect(api.listWorkspaces).toHaveBeenCalledOnce();

    await act(async () => {
      shellRetryCoordinator.confirmUsefulTransport();
      await vi.advanceTimersByTimeAsync(250);
    });

    expect(api.listWorkspaces).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(container.querySelector("[data-testid='sidebar']")?.getAttribute("data-workspaces-loading")).toBe("false");
    expect(container.querySelector("[data-testid='sidebar']")?.getAttribute("data-workspace-count")).toBe("1");
  });

  it("revalidates shell state when transport recovery signals are coalesced", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("transport interrupted"))
      .mockResolvedValueOnce(jsonResponse(sessionPayload()));
    api.getSession.mockImplementation((signal: AbortSignal, retryKey: string) => (
      shellRetryCoordinator.runRequest({
        executor: createSafeRequestRetryExecutor({ endpoint: "/api/session" }),
        key: retryKey,
        signal,
      })
    ));

    await act(async () => {
      root.render(<AppShell />);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.getSession).toHaveBeenCalledOnce();
    expect(container.querySelector("[data-testid='workspace-view']")).toBeNull();

    await act(async () => {
      shellRetryCoordinator.confirmUsefulTransport();
      shellRetryCoordinator.confirmUsefulTransport();
      await vi.advanceTimersByTimeAsync(250);
    });

    expect(api.getSession).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(container.querySelector("[data-testid='workspace-view']")?.getAttribute("data-workspace-id")).toBe("default");
    expect(container.querySelector("[data-testid='login-screen']")).toBeNull();
  });

  it("treats terminal HTTP responses as normal outcomes instead of retry waits", async () => {
    api.getSession.mockRejectedValueOnce(new MaverickHttpError("/api/session", new Response("forbidden", { status: 403 })));

    await act(async () => {
      root.render(<AppShell />);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.querySelector("[data-testid='login-screen']")).not.toBeNull();
    expect(container.querySelector("[aria-label='Loading workspace']")).toBeNull();
    expect(api.getSession).toHaveBeenCalledOnce();
  });

  it("keeps the mounted shell without rebootstrap on a generic transport confirmation", async () => {
    await act(async () => {
      root.render(<AppShell />);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector("[data-testid='workspace-view']")).not.toBeNull();

    await act(async () => {
      shellRetryCoordinator.confirmUsefulTransport();
      await Promise.resolve();
    });

    expect(api.getSession).toHaveBeenCalledOnce();
    expect(container.querySelector("[data-testid='workspace-view']")).not.toBeNull();
    expect(container.querySelector("[data-testid='login-screen']")).toBeNull();
  });

  it("preserves loaded rail pins when an App Store refresh fails and accepts the next update", async () => {
    const pins = ["chat", "storage", "crm", "mail"];
    api.listPinnedApps.mockResolvedValue({ pinned_apps: pins });
    await renderShell();

    api.listPinnedApps.mockRejectedValueOnce(new Error("Backend restarting"));
    await act(async () => dispatchPinnedAppsChanged());

    expect(container.querySelector("[data-testid='sidebar']")?.getAttribute("data-pinned-apps"))
      .toBe(JSON.stringify(pins));
    expect(api.savePinnedApps).not.toHaveBeenCalled();

    api.listPinnedApps.mockResolvedValueOnce({ pinned_apps: [...pins, "calendar"] });
    await act(async () => dispatchPinnedAppsChanged());

    expect(container.querySelector("[data-testid='sidebar']")?.getAttribute("data-pinned-apps"))
      .toBe(JSON.stringify([...pins, "calendar"]));
    expect(api.getSession).toHaveBeenCalledOnce();
  });

  it("does not let a delayed pin refresh replace a newer invalidation result", async () => {
    await renderShell();
    const oldRead = deferred<{ pinned_apps: string[] }>();
    api.listPinnedApps.mockReturnValueOnce(oldRead.promise);
    await act(async () => dispatchPinnedAppsChanged());
    const oldSignal = api.listPinnedApps.mock.calls[1][0] as AbortSignal | undefined;

    api.listPinnedApps.mockResolvedValueOnce({ pinned_apps: ["chat", "crm", "mail"] });
    await act(async () => dispatchPinnedAppsChanged());
    await act(async () => oldRead.resolve({ pinned_apps: ["chat"] }));

    expect(oldSignal?.aborted).toBe(true);
    expect(container.querySelector("[data-testid='sidebar']")?.getAttribute("data-pinned-apps"))
      .toBe(JSON.stringify(["chat", "crm", "mail"]));
  });

  it("does not let a delayed bootstrap pin read replace an App Store update", async () => {
    const bootstrapRead = deferred<{ pinned_apps: string[] }>();
    api.listPinnedApps.mockReturnValueOnce(bootstrapRead.promise);
    await renderShell();
    api.listPinnedApps.mockResolvedValueOnce({ pinned_apps: ["chat", "storage"] });
    await act(async () => dispatchPinnedAppsChanged());
    await act(async () => bootstrapRead.resolve({ pinned_apps: ["chat"] }));

    expect(container.querySelector("[data-testid='sidebar']")?.getAttribute("data-pinned-apps"))
      .toBe(JSON.stringify(["chat", "storage"]));
  });

  it("does not overwrite an optimistic reorder or its rollback pins with an older read", async () => {
    const pins = ["chat", "crm", "mail"];
    api.listPinnedApps.mockResolvedValue({ pinned_apps: pins });
    await renderShell();
    const oldRead = deferred<{ pinned_apps: string[] }>();
    const save = deferred<{ pinned_apps: string[] }>();
    api.listPinnedApps.mockReturnValueOnce(oldRead.promise);
    api.savePinnedApps.mockReturnValueOnce(save.promise);
    await act(async () => dispatchPinnedAppsChanged());
    await act(async () => container.querySelector<HTMLButtonElement>("[data-testid='reorder-pins']")?.click());
    await act(async () => oldRead.resolve({ pinned_apps: ["chat"] }));

    expect(container.querySelector("[data-testid='sidebar']")?.getAttribute("data-pinned-apps"))
      .toBe(JSON.stringify(["mail", "crm", "chat"]));
    await act(async () => save.reject(new Error("Save failed")));
    expect(container.querySelector("[data-testid='sidebar']")?.getAttribute("data-pinned-apps"))
      .toBe(JSON.stringify(pins));
  });

  it("discards and aborts a pending pin refresh when the workspace changes", async () => {
    await renderShell();
    const oldRead = deferred<{ pinned_apps: string[] }>();
    api.listPinnedApps.mockReturnValueOnce(oldRead.promise);
    await act(async () => dispatchPinnedAppsChanged());
    const oldSignal = api.listPinnedApps.mock.calls[1][0] as AbortSignal | undefined;

    api.getSession.mockResolvedValue(sessionPayload("other"));
    api.listPinnedApps.mockResolvedValue({ pinned_apps: ["chat", "calendar"] });
    await act(async () => {
      container.querySelector<HTMLButtonElement>("[data-testid='switch-workspace']")?.click();
    });
    await act(async () => oldRead.resolve({ pinned_apps: ["chat", "crm", "mail"] }));

    expect(oldSignal?.aborted).toBe(true);
    expect(container.querySelector("[data-testid='sidebar']")?.getAttribute("data-pinned-apps"))
      .toBe(JSON.stringify(["chat", "calendar"]));
  });

  it.each([401, 403])("revokes the shell instead of retaining rail pins after refresh HTTP %i", async (status) => {
    await renderShell();
    api.listPinnedApps.mockRejectedValueOnce(
      new MaverickHttpError("/api/apps/app-store/backend", new Response(null, { status })),
    );
    await act(async () => dispatchPinnedAppsChanged());

    expect(container.querySelector("[data-testid='sidebar']")).toBeNull();
    expect(container.querySelector("[data-testid='login-screen']")).not.toBeNull();
  });

  it("ends mounted shell loading when workspace reload returns an authorization response", async () => {
    await act(async () => {
      root.render(<AppShell />);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector("[data-testid='workspace-view']")).not.toBeNull();

    api.getSession.mockRejectedValueOnce(
      new MaverickHttpError("/api/session", new Response("unauthenticated", { status: 401 })),
    );
    await act(async () => {
      container.querySelector<HTMLButtonElement>("[data-testid='switch-workspace']")?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.querySelector("[aria-label='Loading workspace']")).toBeNull();
    expect(container.querySelector("[data-testid='workspace-view']")).toBeNull();
    expect(container.querySelector("[data-testid='login-screen']")).not.toBeNull();
  });

  it("unmounts every authenticated app frame after a warm cache revalidation loses authorization", async () => {
    await act(async () => {
      root.render(<AppShell />);
      await Promise.resolve();
      await Promise.resolve();
    });
    const mountedFrame = container.querySelector("[data-testid='mounted-app-frame']");
    expect(mountedFrame).not.toBeNull();
    const cleanup = vi.spyOn(shellCacheLifecycle, "authorizationFailure").mockResolvedValue(completeCleanup());

    await act(async () => {
      await revokeShellAuthorization(403);
    });

    expect(cleanup).toHaveBeenCalledOnce();
    expect(container.querySelector("[data-testid='mounted-app-frame']")).toBeNull();
    expect(container.querySelector("[data-testid='workspace-view']")).toBeNull();
    expect(container.querySelector("[data-testid='login-screen']")).not.toBeNull();
  });

  it("fences the real workspace mutation before the request and keeps the next scope unpublished", async () => {
    const transition = vi.spyOn(shellCacheLifecycle, "transition");
    const cleanup = deferred<Awaited<ReturnType<typeof shellCacheLifecycle.transition>>>();
    const switchRequest = deferred<{ active_workspace_id: string }>();
    transition
      .mockResolvedValueOnce(completeCleanup())
      .mockImplementationOnce(() => {
        expect(container.querySelector("[data-testid='mounted-app-frame']")).toBeNull();
        expect(dataCacheBrokerHost.frameScope).toBeNull();
        expect(dataCacheBrokerHost.principal).toBeNull();
        return cleanup.promise;
      });

    await renderShell();
    const previousFrame = container.querySelector("[data-testid='mounted-app-frame']");
    expect(previousFrame).not.toBeNull();

    api.getSession.mockResolvedValueOnce(sessionPayload("other"));
    api.switchWorkspace.mockImplementationOnce(() => {
      expect(container.querySelector("[data-testid='mounted-app-frame']")).toBeNull();
      expect(dataCacheBrokerHost.frameScope).toBeNull();
      expect(dataCacheBrokerHost.principal).toBeNull();
      return switchRequest.promise;
    });
    await act(async () => {
      container.querySelector<HTMLButtonElement>("[data-testid='switch-workspace']")?.click();
      await until(() => api.switchWorkspace.mock.calls.length === 1);
    });

    expect(api.switchWorkspace).toHaveBeenCalledWith("other");
    expect(api.getSession).toHaveBeenCalledOnce();
    expect(transition).toHaveBeenCalledOnce();
    expect(container.querySelector("[data-testid='mounted-app-frame']")).toBeNull();
    expect(previousFrame?.isConnected).toBe(false);

    await act(async () => {
      switchRequest.resolve({ active_workspace_id: "other" });
      await switchRequest.promise;
      await until(() => transition.mock.calls.length === 2);
    });

    expect(container.querySelector("[data-testid='mounted-app-frame']")).toBeNull();
    expect(container.querySelector("[data-testid='workspace-view']")).toBeNull();
    expect(container.querySelector("[aria-label='Loading workspace']")).not.toBeNull();
    expect(dataCacheBrokerHost.frameScope).toBeNull();
    expect(dataCacheBrokerHost.principal).toBeNull();
    expect(transition).toHaveBeenNthCalledWith(2, expect.objectContaining({ workspaceId: "other" }));
    expect(api.listApps).toHaveBeenCalledOnce();

    await act(async () => {
      cleanup.resolve(completeCleanup());
      await cleanup.promise;
      await until(() => container.querySelector("[data-testid='workspace-view']") !== null);
    });

    expect(container.querySelector("[data-testid='workspace-view']")?.getAttribute("data-workspace-id")).toBe("other");
    expect(api.listApps).toHaveBeenCalledTimes(2);
    expect(dataCacheBrokerHost.frameScope?.workspaceId).toBe("other");
    expect(dataCacheBrokerHost.principal?.workspaceId).toBe("other");
  });

  it("unmounts authenticated frames before logout or cache cleanup can settle", async () => {
    const transition = vi.spyOn(shellCacheLifecycle, "transition").mockResolvedValue(completeCleanup());
    const logoutRequest = deferred<SessionPayload>();
    const cleanup = deferred<Awaited<ReturnType<typeof shellCacheLifecycle.endSession>>>();
    vi.spyOn(shellCacheLifecycle, "endSession").mockReturnValue(cleanup.promise);
    api.logout.mockReturnValue(logoutRequest.promise);

    await renderShell();
    expect(transition).toHaveBeenCalledOnce();
    const mountedFrame = container.querySelector("[data-testid='mounted-app-frame']");
    expect(mountedFrame).not.toBeNull();

    await act(async () => {
      dispatchShellLogout();
      await Promise.resolve();
    });

    expect(container.querySelector("[data-testid='mounted-app-frame']")).toBeNull();
    expect(container.querySelector("[data-testid='workspace-view']")).toBeNull();
    expect(dataCacheBrokerHost.frameScope).toBeNull();
    expect(dataCacheBrokerHost.principal).toBeNull();
    expect(mountedFrame?.isConnected).toBe(false);
    expect(shellCacheLifecycle.endSession).not.toHaveBeenCalled();

    await act(async () => {
      logoutRequest.resolve({ authenticated: false });
      await logoutRequest.promise;
      await until(() => vi.mocked(shellCacheLifecycle.endSession).mock.calls.length === 1);
    });

    expect(container.querySelector("[data-testid='mounted-app-frame']")).toBeNull();
    expect(container.querySelector("[aria-label='Loading workspace']")).not.toBeNull();

    await act(async () => {
      cleanup.resolve(completeCleanup());
      await cleanup.promise;
      await until(() => container.querySelector("[data-testid='login-screen']") !== null);
    });

    expect(api.getSession).toHaveBeenCalledOnce();
    expect(container.querySelector("[data-testid='login-screen']")).not.toBeNull();
  });

  it("does not republish a pending workspace after a concurrent authorization revocation", async () => {
    const transition = vi.spyOn(shellCacheLifecycle, "transition");
    const cleanup = deferred<Awaited<ReturnType<typeof shellCacheLifecycle.transition>>>();
    const authorizationCleanup = deferred<Awaited<ReturnType<typeof shellCacheLifecycle.authorizationFailure>>>();
    vi.spyOn(shellCacheLifecycle, "authorizationFailure").mockReturnValue(authorizationCleanup.promise);
    transition
      .mockResolvedValueOnce(completeCleanup())
      .mockReturnValueOnce(cleanup.promise);

    await renderShell();
    api.getSession.mockResolvedValueOnce(sessionPayload("other"));
    await act(async () => {
      container.querySelector<HTMLButtonElement>("[data-testid='switch-workspace']")?.click();
      await until(() => transition.mock.calls.length === 2);
    });
    expect(container.querySelector("[data-testid='workspace-view']")).toBeNull();

    let revocation!: Promise<void>;
    await act(async () => {
      revocation = revokeShellAuthorization(401);
      await Promise.resolve();
    });
    expect(container.querySelector("[data-testid='login-screen']")).not.toBeNull();

    await act(async () => {
      cleanup.resolve(completeCleanup());
      authorizationCleanup.resolve(completeCleanup());
      await cleanup.promise;
      await revocation;
    });

    expect(container.querySelector("[data-testid='workspace-view']")).toBeNull();
    expect(container.querySelector("[data-testid='mounted-app-frame']")).toBeNull();
    expect(container.querySelector("[data-testid='login-screen']")).not.toBeNull();
    expect(dataCacheBrokerHost.frameScope).toBeNull();
    expect(dataCacheBrokerHost.principal).toBeNull();
    expect(api.listApps).toHaveBeenCalledOnce();
  });

  it("does not strand a new bootstrap when authorization is revoked during an existing cleanup", async () => {
    await renderShell();
    expect(container.querySelector("[data-testid='mounted-app-frame']")).not.toBeNull();

    const authorizationCleanup = deferred<Awaited<ReturnType<typeof shellCacheLifecycle.authorizationFailure>>>();
    const cleanup = vi.spyOn(shellCacheLifecycle, "authorizationFailure").mockReturnValue(authorizationCleanup.promise);
    let firstRevocation!: Promise<void>;

    try {
      await act(async () => {
        firstRevocation = revokeShellAuthorization(403);
        await Promise.resolve();
      });
      expect(container.querySelector("[data-testid='login-screen']")).not.toBeNull();

      api.getSession.mockRejectedValueOnce(
        new MaverickHttpError("/api/session", new Response("unauthenticated", { status: 401 })),
      );
      await act(async () => {
        container.querySelector<HTMLButtonElement>("[data-testid='retry-authenticated-bootstrap']")?.click();
        await until(() => api.getSession.mock.calls.length === 2);
        await Promise.resolve();
      });

      expect(cleanup).toHaveBeenCalledOnce();
      expect(container.querySelector("[aria-label='Loading workspace']")).toBeNull();
      expect(container.querySelector("[data-testid='login-screen']")).not.toBeNull();
      expect(container.querySelector("[data-testid='mounted-app-frame']")).toBeNull();
    } finally {
      authorizationCleanup.resolve(completeCleanup());
      await firstRevocation;
    }
  });
});

function sessionPayload(workspaceId = "default"): Extract<SessionPayload, { authenticated: true }> {
  return {
    authenticated: true,
    expires_at: "2026-07-08T00:00:00Z",
    user: {
      account_type: "local",
      display_name: "Admin",
      email: null,
      platform_role: "admin",
      user_id: "user-1",
      username: "admin",
    },
    workspace_id: workspaceId,
  };
}

function completeCleanup() {
  return { pendingCleanupCount: 0, removed: 0, status: "complete" as const };
}

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
  });
}

function dispatchShellLogout() {
  window.dispatchEvent(new MessageEvent("message", {
    data: { type: "maverick.shell.logout" },
    origin: window.location.origin,
    source: window,
  }));
}

function dispatchPinnedAppsChanged() {
  window.dispatchEvent(new MessageEvent("message", {
    data: { type: "maverick.app.data-changed", owner_app_id: "app-store", resource: "pinned-apps" },
    origin: window.location.origin,
    source: window,
  }));
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

async function until(condition: () => boolean, attempts = 20): Promise<void> {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (condition()) return;
    await Promise.resolve();
  }
  throw new Error("Condition was not reached before the test deadline.");
}

function app(appId: string): AppRegistryItem {
  return {
    app_id: appId,
    backend_mount: "",
    description: "",
    distribution_mode: "sealed",
    frontend_launchable: true,
    frontend_mount: `/apps/${appId}/`,
    frontend_role: "workspace",
    logo: null,
    name: appId,
    provides: [],
    publisher: "maverick",
    requires: [],
    source_access: "none",
    status: "enabled",
    version: "1.0.0",
    views: [],
  };
}

function workspace(workspaceId: string): WorkspaceItem {
  return {
    description: null,
    governance: {},
    is_active: true,
    name: workspaceId,
    quota: {},
    status: "active",
    workspace_id: workspaceId,
  };
}

function platformSettings(): PlatformSettings {
  return {
    provider: {
      active_provider: null,
      available_providers: [],
      blocked_reason: "provider_not_configured",
      model_settings: null,
      selection: null,
      workspace_id: "default",
    },
    recovery: {},
    runtime: {
      active_provider: null,
      all_sessions: [],
      cleanup_allowed: false,
      cleanup_scope: "none",
      model_settings: null,
      selection: null,
      sessions: [],
      workspace_id: "default",
    },
    user: sessionPayload().user,
    workspace: workspace("default"),
  };
}
