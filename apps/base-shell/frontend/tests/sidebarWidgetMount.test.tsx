// @vitest-environment happy-dom

import { act, useEffect } from "react";
import type { ComponentProps } from "react";
import { flushSync } from "react-dom";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AppRegistryItem, SessionUser, WorkspaceItem } from "../src/api";
import { Sidebar } from "../src/components/Sidebar";
import type { WidgetPrimaryActionState } from "../src/components/WidgetSlot";
import type { ShellThemeState } from "../src/theme";

const widgetSlotMountMock = vi.fn();
const widgetSlotUnmountMock = vi.fn();
const widgetSlotMock = vi.fn((props: Record<string, unknown>) => {
  useEffect(() => {
    widgetSlotMountMock(props);
    return () => widgetSlotUnmountMock(props);
  }, []);
  return <div data-testid="widget-slot" data-content-kind={String(props.contentKind || "")} />;
});

vi.mock("../src/components/WidgetSlot", () => ({
  WidgetSlot: (props: Record<string, unknown>) => widgetSlotMock(props),
}));

const shellTheme = {
  color_scheme: "dark",
  effective: "dark",
  mode: "dark",
} satisfies ShellThemeState;
const FRAME_SCOPE = Object.freeze({ sessionGeneration: "session-default", workspaceId: "default" });

describe("Sidebar widget mount gate", () => {
  let container: HTMLDivElement;
  let root: Root;
  let primaryActionStateChange: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    widgetSlotMock.mockClear();
    widgetSlotMountMock.mockClear();
    widgetSlotUnmountMock.mockClear();
    primaryActionStateChange = vi.fn();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("offers current-app settings, not workspace creation, also for non-admin users", async () => {
    const openSettings = vi.fn();
    await renderSidebar(root, primaryActionStateChange, { isOpen: true, onOpenAppSettings: openSettings, user: { platform_role: "user", username: "member" } as SessionUser });
    const button = container.querySelector<HTMLButtonElement>('.bs-sidebar__app-settings')!;
    expect(button.getAttribute("aria-label")).toBe("Impostazioni di chat");
    await act(async () => button.click());
    expect(openSettings).toHaveBeenCalledOnce();
    expect(container.querySelector('.bs-workspace-switcher__create')).toBeNull();
  });

  it("does not mount primary or footer widgets while the detail layer is closed", async () => {
    await renderSidebar(root, primaryActionStateChange, { isOpen: false, isPinned: false });

    expect(widgetSlotMock).not.toHaveBeenCalled();
    expect(primaryActionStateChange).toHaveBeenCalledWith({
      available: false,
      label: "",
      preferredSurface: "app",
    });
  });

  it("keeps the rail but suppresses sidebar widgets, resize and hover/focus opening for opted-out apps", async () => {
    const open = vi.fn();
    const canvas = { ...app("canvas"), sidebar_enabled: false };
    await renderSidebar(root, primaryActionStateChange, { apps: [canvas], activeAppId: "canvas",
      pinnedAppIds: ["canvas"], isOpen: true, isPinned: true, mode: "fixed", onOpenSidebar: open });
    const sidebar = container.querySelector<HTMLElement>(".bs-sidebar")!;
    await act(async () => {
      sidebar.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
      container.querySelector<HTMLButtonElement>(".bs-sidebar__rail-button")!.focus();
    });
    expect(open).not.toHaveBeenCalled();
    expect(sidebar.classList.contains("is-closed")).toBe(true);
    expect(sidebar.classList.contains("bs-sidebar--rail")).toBe(true);
    expect(container.querySelector(".bs-sidebar__rail")).not.toBeNull();
    expect(container.querySelector(".bs-sidebar__resize-handle")).toBeNull();
    expect(widgetSlotMock).not.toHaveBeenCalled();
    expect(primaryActionStateChange).toHaveBeenCalledWith({ available: false, label: "", preferredSurface: "app" });
  });

  it("exposes workspace, app settings, theme and mode through the two rail menus", async () => {
    const settings = vi.fn();
    const theme = vi.fn();
    const mode = vi.fn();
    await renderSidebar(root, primaryActionStateChange, { apps: [{ ...app("canvas"), sidebar_enabled: false }],
      activeAppId: "canvas", onOpenAppSettings: settings, onThemeModeChange: theme, onModeChange: mode });
    const top = container.querySelector<HTMLButtonElement>('button[aria-label="Controlli workspace"]')!;
    await act(async () => top.focus());
    expect(top.getAttribute("aria-expanded")).toBe("true");
    expect(container.querySelector('select[aria-label="Workspace"]')).not.toBeNull();
    await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="Impostazioni di canvas"]')!.click());
    expect(settings).toHaveBeenCalledOnce();
    await act(async () => top.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
    expect(top.getAttribute("aria-expanded")).toBe("false");
    const bottom = container.querySelector<HTMLButtonElement>('button[aria-label="Controlli Maverick"]')!;
    await act(async () => bottom.focus());
    await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="Light mode"]')!.click());
    await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="Sidebar fissa"]')!.click());
    expect(theme).toHaveBeenCalledWith("light");
    expect(mode).toHaveBeenCalledWith("fixed");
    expect(widgetSlotMock).not.toHaveBeenCalled();
  });

  it("provides compact mobile controls without opening the sidebar or mounting widgets", async () => {
    await renderSidebar(root, primaryActionStateChange, { apps: [{ ...app("canvas"), sidebar_enabled: false }],
      activeAppId: "canvas", isMobileLayout: true, isOpen: true });
    expect(container.querySelector('.bs-sidebar__rail-menu--mobile select[aria-label="Workspace"]')).not.toBeNull();
    expect(container.querySelector('.bs-sidebar__rail-menu--mobile button[aria-label="Light mode"]')).not.toBeNull();
    expect(container.querySelector('.bs-sidebar')?.classList.contains("is-closed")).toBe(true);
    expect(widgetSlotMock).not.toHaveBeenCalled();
  });

  it("mounts primary and footer widgets when the detail layer is open", async () => {
    await renderSidebar(root, primaryActionStateChange, { isOpen: true, isPinned: false });

    expect(widgetSlotMock).toHaveBeenCalledTimes(2);
    expect(widgetSlotMountMock).toHaveBeenCalledTimes(2);
  });

  it("waits for app metadata before mounting sidebar widgets from a saved fixed preference", async () => {
    await renderSidebar(root, primaryActionStateChange, { apps: [], isLoading: true, isOpen: true, isPinned: true });
    expect(widgetSlotMock).not.toHaveBeenCalled();
    expect(container.querySelector(".bs-sidebar")?.classList.contains("is-closed")).toBe(true);
  });

  it("mounts primary and footer widgets in the first opening render", () => {
    renderSidebarSync(root, primaryActionStateChange, { isOpen: false, isPinned: false });

    widgetSlotMock.mockClear();
    widgetSlotMountMock.mockClear();
    widgetSlotUnmountMock.mockClear();

    act(() => {
      flushSync(() => {
        root.render(sidebarElement(primaryActionStateChange, { isOpen: true, isPinned: false }));
      });

      expect(widgetSlotMock).toHaveBeenCalledTimes(2);
      expect(container.querySelectorAll("[data-testid='widget-slot']")).toHaveLength(2);
    });
  });

  it("keeps mounted sidebar widgets alive while the overlay closes and reopens", async () => {
    await renderSidebar(root, primaryActionStateChange, { isOpen: true, isPinned: false });

    expect(container.querySelectorAll("[data-testid='widget-slot']")).toHaveLength(2);
    expect(widgetSlotMountMock).toHaveBeenCalledTimes(2);

    widgetSlotMock.mockClear();
    widgetSlotMountMock.mockClear();
    widgetSlotUnmountMock.mockClear();

    await renderSidebar(root, primaryActionStateChange, { isOpen: false, isPinned: false });

    expect(container.querySelectorAll("[data-testid='widget-slot']")).toHaveLength(2);
    expect(widgetSlotUnmountMock).not.toHaveBeenCalled();
    expect(widgetSlotMountMock).not.toHaveBeenCalled();

    await renderSidebar(root, primaryActionStateChange, { isOpen: true, isPinned: false });

    expect(container.querySelectorAll("[data-testid='widget-slot']")).toHaveLength(2);
    expect(widgetSlotUnmountMock).not.toHaveBeenCalled();
    expect(widgetSlotMountMock).not.toHaveBeenCalled();
  });
});

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

async function renderSidebar(
  root: Root,
  primaryActionStateChange: ReturnType<typeof vi.fn>,
  overrides: Partial<ComponentProps<typeof Sidebar>>,
) {
  await act(async () => {
    root.render(sidebarElement(primaryActionStateChange, overrides));
    await Promise.resolve();
  });
}

function renderSidebarSync(
  root: Root,
  primaryActionStateChange: ReturnType<typeof vi.fn>,
  overrides: Partial<ComponentProps<typeof Sidebar>>,
) {
  act(() => {
    flushSync(() => {
      root.render(sidebarElement(primaryActionStateChange, overrides));
    });
  });
}

function sidebarElement(
  primaryActionStateChange: ReturnType<typeof vi.fn>,
  overrides: Partial<ComponentProps<typeof Sidebar>>,
) {
  return (
    <Sidebar
      activeAppId="chat"
      activeAppParams={{}}
      activeWorkspaceId="default"
      apps={[app("chat")]}
      isLoading={false}
      isMobileLayout={false}
      isOpen={false}
      isPinned={false}
      mobilePrimaryActionRequestId={0}
      mode="rail"
      onClose={vi.fn()}
      onModeChange={vi.fn()}
      onOpenApp={vi.fn()}
      onOpenSettings={vi.fn()}
      onOpenSidebar={vi.fn()}
      onPrimaryActionStateChange={primaryActionStateChange as (state: WidgetPrimaryActionState) => void}
      onReorderPinnedApps={vi.fn()}
      onSidebarDetailsWidthChange={vi.fn()}
      onThemeModeChange={vi.fn()}
      onWorkspaceChange={vi.fn()}
      onOpenAppSettings={vi.fn()}
      pinnedAppIds={["chat"]}
      railMetrics={{}}
      shellTheme={shellTheme}
      sidebarDetailsWidthPx={360}
      themeMode="dark"
      user={{ platform_role: "admin", username: "admin" } as SessionUser}
      workspaces={[{ workspace_id: "default", name: "Default", description: null, status: "active", governance: {}, quota: {}, is_active: true } as WorkspaceItem]}
      {...overrides}
      frameScope={overrides.frameScope ?? FRAME_SCOPE}
    />
  );
}
