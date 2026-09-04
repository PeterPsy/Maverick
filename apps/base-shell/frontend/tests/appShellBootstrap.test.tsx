// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MaverickHttpError, MaverickTransportError } from "../src/api";
import type { AppRegistryItem, PlatformSettings, SessionPayload, WorkspaceItem } from "../src/api";
import { AppShell } from "../src/AppShell";
import { shellCacheLifecycle, shellRetryCoordinator } from "../src/pwaCacheRuntime";

const api = vi.hoisted(() => ({
  configureActiveProvider: vi.fn(),
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
  onAuthorizationFailure: null as null | ((status: 401 | 403) => Promise<void> | void),
  principal: null as null | { sessionExpiresAt: string; userId: string; workspaceId: string },
}));

vi.mock("../src/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api")>();
  return {
    ...actual,
    configureActiveProvider: api.configureActiveProvider,
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
    onAuthorizationFailure: (status: 401 | 403) => Promise<void> | void;
    principal: null | { sessionExpiresAt: string; userId: string; workspaceId: string };
  }) => {
    dataCacheBrokerHost.frameScope = options.frameScope;
    dataCacheBrokerHost.onAuthorizationFailure = options.onAuthorizationFailure;
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
    onWorkspaceChanged,
    workspaces,
  }: {
    isLoading: boolean;
    isWorkspacesLoading: boolean;
    onWorkspaceChanged: () => Promise<void>;
    workspaces: WorkspaceItem[];
  }) => (
    <aside
      data-apps-loading={String(isLoading)}
      data-testid="sidebar"
      data-workspace-count={String(workspaces.length)}
      data-workspaces-loading={String(isWorkspacesLoading)}
    >
      <button data-testid="revalidate-workspace" onClick={() => void onWorkspaceChanged()} type="button" />
    </aside>
  ),
}));
vi.mock("../src/components/FloatingChatHost", () => ({
  FloatingChatHost: () => <div data-testid="floating-chat-host" />,
}));
vi.mock("../src/components/LoginScreen", () => ({
  LoginScreen: () => <div data-testid="login-screen" />,
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
    dataCacheBrokerHost.onAuthorizationFailure = null;
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
    api.getSession.mockRejectedValueOnce(new MaverickTransportError("Transport failed: /api/session"));

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

    expect(api.getSession).toHaveBeenCalledTimes(2);
    expect(container.querySelector("[data-testid='workspace-view']")?.getAttribute("data-workspace-id")).toBe("default");
    expect(container.querySelector("[data-testid='login-screen']")).toBeNull();
  });

  it("keeps deferred workspace state loading and retries it after transport recovery", async () => {
    vi.useFakeTimers();
    api.listWorkspaces
      .mockRejectedValueOnce(new MaverickTransportError("Transport failed: /api/workspaces"))
      .mockResolvedValueOnce({ items: [workspace("recovered")] });

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

    expect(api.listWorkspaces).toHaveBeenCalledTimes(2);
    expect(container.querySelector("[data-testid='sidebar']")?.getAttribute("data-workspaces-loading")).toBe("false");
    expect(container.querySelector("[data-testid='sidebar']")?.getAttribute("data-workspace-count")).toBe("1");
  });

  it("revalidates shell state when transport recovery signals are coalesced", async () => {
    vi.useFakeTimers();
    api.getSession.mockRejectedValueOnce(new MaverickTransportError("Transport failed: /api/session"));

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

    expect(api.getSession).toHaveBeenCalledTimes(2);
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

  it("ends mounted shell loading when explicit revalidation returns an authorization response", async () => {
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
      container.querySelector<HTMLButtonElement>("[data-testid='revalidate-workspace']")?.click();
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
    expect(dataCacheBrokerHost.onAuthorizationFailure).not.toBeNull();

    await act(async () => {
      await dataCacheBrokerHost.onAuthorizationFailure?.(403);
    });

    expect(container.querySelector("[data-testid='mounted-app-frame']")).toBeNull();
    expect(container.querySelector("[data-testid='workspace-view']")).toBeNull();
    expect(container.querySelector("[data-testid='login-screen']")).not.toBeNull();
  });

  it("keeps the next workspace unpublished while its cache lifecycle transition is pending", async () => {
    const transition = vi.spyOn(shellCacheLifecycle, "transition");
    const cleanup = deferred<Awaited<ReturnType<typeof shellCacheLifecycle.transition>>>();
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
    await act(async () => {
      container.querySelector<HTMLButtonElement>("[data-testid='revalidate-workspace']")?.click();
      await until(() => transition.mock.calls.length === 2);
    });

    expect(container.querySelector("[data-testid='mounted-app-frame']")).toBeNull();
    expect(container.querySelector("[data-testid='workspace-view']")).toBeNull();
    expect(container.querySelector("[aria-label='Loading workspace']")).not.toBeNull();
    expect(dataCacheBrokerHost.frameScope).toBeNull();
    expect(dataCacheBrokerHost.principal).toBeNull();
    expect(previousFrame?.isConnected).toBe(false);
    expect(transition).toHaveBeenNthCalledWith(2, expect.objectContaining({ workspaceId: "other" }));

    await act(async () => {
      cleanup.resolve(completeCleanup());
      await cleanup.promise;
      await until(() => container.querySelector("[data-testid='workspace-view']") !== null);
    });

    expect(container.querySelector("[data-testid='workspace-view']")?.getAttribute("data-workspace-id")).toBe("other");
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

  it("does not republish a pending workspace after a concurrent broker authorization failure", async () => {
    const transition = vi.spyOn(shellCacheLifecycle, "transition");
    const cleanup = deferred<Awaited<ReturnType<typeof shellCacheLifecycle.transition>>>();
    transition
      .mockResolvedValueOnce(completeCleanup())
      .mockReturnValueOnce(cleanup.promise);

    await renderShell();
    api.getSession.mockResolvedValueOnce(sessionPayload("other"));
    await act(async () => {
      container.querySelector<HTMLButtonElement>("[data-testid='revalidate-workspace']")?.click();
      await until(() => transition.mock.calls.length === 2);
    });
    expect(container.querySelector("[data-testid='workspace-view']")).toBeNull();

    await act(async () => {
      await dataCacheBrokerHost.onAuthorizationFailure?.(401);
      cleanup.resolve(completeCleanup());
      await cleanup.promise;
      await Promise.resolve();
    });

    expect(container.querySelector("[data-testid='workspace-view']")).toBeNull();
    expect(container.querySelector("[data-testid='mounted-app-frame']")).toBeNull();
    expect(container.querySelector("[data-testid='login-screen']")).not.toBeNull();
    expect(dataCacheBrokerHost.frameScope).toBeNull();
    expect(dataCacheBrokerHost.principal).toBeNull();
    expect(api.listApps).toHaveBeenCalledOnce();
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

function dispatchShellLogout() {
  window.dispatchEvent(new MessageEvent("message", {
    data: { type: "maverick.shell.logout" },
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
