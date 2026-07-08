// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AppRegistryItem, PlatformSettings, SessionPayload, WorkspaceItem } from "../src/api";
import { AppShell } from "../src/AppShell";

const api = vi.hoisted(() => ({
  configureActiveProvider: vi.fn(),
  getPlatformSettings: vi.fn(),
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
  Sidebar: () => <aside data-testid="sidebar" />,
}));
vi.mock("../src/components/FloatingChatHost", () => ({
  FloatingChatHost: () => <div data-testid="floating-chat-host" />,
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
    api.getSession.mockResolvedValue(sessionPayload());
    api.listApps.mockResolvedValue({ items: [app("chat")] });
    api.listPinnedApps.mockResolvedValue({ pinned_apps: ["chat"] });
    api.listWorkspaces.mockResolvedValue({ active_workspace_id: "default", items: [workspace("default")] });
    api.getPlatformSettings.mockResolvedValue(platformSettings());
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
