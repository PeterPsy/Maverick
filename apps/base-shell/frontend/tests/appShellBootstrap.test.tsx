// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AppRegistryItem, PlatformSettings, SessionPayload, WorkspaceItem } from "../src/api";
import { AppShell } from "../src/AppShell";
import { recordMaverickNetworkFailure, recordMaverickNetworkSuccess } from "../src/connectivity";

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

vi.mock("../src/components/WorkspaceView", () => ({
  WorkspaceView: ({ activeWorkspaceId, isLoading }: { activeWorkspaceId: string; isLoading: boolean }) => (
    <div data-loading={String(isLoading)} data-testid="workspace-view" data-workspace-id={activeWorkspaceId} />
  ),
}));
vi.mock("../src/components/Sidebar", () => ({
  Sidebar: ({
    isLoading,
    isWorkspacesLoading,
    workspaces,
  }: {
    isLoading: boolean;
    isWorkspacesLoading: boolean;
    workspaces: WorkspaceItem[];
  }) => (
    <aside
      data-apps-loading={String(isLoading)}
      data-testid="sidebar"
      data-workspace-count={String(workspaces.length)}
      data-workspaces-loading={String(isWorkspacesLoading)}
    />
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
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    recordMaverickNetworkSuccess(new Date("2026-08-26T12:00:00Z"));
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
  });

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

  it("bootstraps authenticated shell state after a confirmed cold-offline reconnection", async () => {
    recordMaverickNetworkFailure();
    api.getSession.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await act(async () => {
      root.render(<AppShell />);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.getSession).toHaveBeenCalledOnce();
    expect(container.querySelector("[data-testid='workspace-view']")).toBeNull();

    await act(async () => {
      recordMaverickNetworkSuccess(new Date("2026-08-26T12:01:00Z"));
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.getSession).toHaveBeenCalledTimes(2);
    expect(container.querySelector("[data-testid='workspace-view']")?.getAttribute("data-workspace-id")).toBe("default");
    expect(container.querySelector("[data-testid='login-screen']")).toBeNull();
  });

  it("hides stale authenticated state until reconnect session revalidation completes", async () => {
    await act(async () => {
      root.render(<AppShell />);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector("[data-testid='workspace-view']")).not.toBeNull();

    await act(async () => {
      recordMaverickNetworkFailure();
      await Promise.resolve();
    });
    let resolveSession: ((value: SessionPayload) => void) | undefined;
    api.getSession.mockReturnValueOnce(new Promise((resolve) => { resolveSession = resolve; }));

    await act(async () => {
      recordMaverickNetworkSuccess(new Date("2026-08-26T12:02:00Z"));
      await Promise.resolve();
    });

    expect(api.getSession).toHaveBeenCalledTimes(2);
    expect(container.querySelector("[data-testid='workspace-view']")).toBeNull();
    expect(container.querySelector("[data-testid='login-screen']")).toBeNull();

    await act(async () => {
      resolveSession?.({ authenticated: false });
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.querySelector("[data-testid='login-screen']")).not.toBeNull();
    expect(container.querySelector("[data-testid='workspace-view']")).toBeNull();
  });
});

function sessionPayload(): Extract<SessionPayload, { authenticated: true }> {
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
    workspace_id: "default",
  };
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
