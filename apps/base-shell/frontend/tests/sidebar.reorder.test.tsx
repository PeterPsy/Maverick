// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AppRegistryItem, SessionUser, WorkspaceItem } from "../src/api";
import { Sidebar } from "../src/components/Sidebar";

vi.mock("../src/components/WidgetSlot", () => ({
  WidgetSlot: () => null,
}));

function app(app_id: string, name = app_id): AppRegistryItem {
  return {
    app_id,
    backend_mount: "",
    description: "",
    distribution_mode: "sealed",
    frontend_mount: `/apps/${app_id}/`,
    frontend_role: "workspace",
    frontend_launchable: true,
    logo: null,
    name,
    publisher: "maverick",
    source_access: "none",
    status: "enabled",
    version: "1.0.0",
    provides: [],
    requires: [],
    views: [],
  };
}

const apps = [app("app-store", "App Store"), app("chat", "Chat"), app("agents", "Agents"), app("skills", "Skills"), app("docs", "Docs")];
const user: SessionUser = {
  user_id: "settings",
  username: "admin",
  email: null,
  display_name: null,
  account_type: "standard",
  platform_role: "admin",
};
const workspaces: WorkspaceItem[] = [
  {
    workspace_id: "default",
    name: "Default",
    description: null,
    status: "active",
    governance: {},
    quota: {},
    is_active: true,
  },
];

describe("Sidebar desktop rail reorder", () => {
  let container: HTMLDivElement;
  let root: Root;
  let openApp: ReturnType<typeof vi.fn<(appId: string, params?: Record<string, string | boolean | null>) => void>>;
  let closeSidebar: ReturnType<typeof vi.fn<() => void>>;
  let reorderPinnedApps: ReturnType<typeof vi.fn<(appIds: string[]) => void>>;
  let openSettings: ReturnType<typeof vi.fn<() => void>>;
  let resizeSidebar: ReturnType<typeof vi.fn<(widthPx: number) => void>>;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers();
    HTMLElement.prototype.setPointerCapture = vi.fn();
    HTMLElement.prototype.hasPointerCapture = vi.fn(() => true);
    HTMLElement.prototype.releasePointerCapture = vi.fn();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    openApp = vi.fn<(appId: string, params?: Record<string, string | boolean | null>) => void>();
    openSettings = vi.fn<() => void>();
    closeSidebar = vi.fn<() => void>();
    reorderPinnedApps = vi.fn<(appIds: string[]) => void>();
    resizeSidebar = vi.fn<(widthPx: number) => void>();
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("keeps normal click navigation on desktop", async () => {
    await renderSidebar();

    await act(async () => {
      railButton("Chat").click();
    });

    expect(openApp).toHaveBeenCalledWith("chat");
    expect(reorderPinnedApps).not.toHaveBeenCalled();
  });

  it("reorders after long press and suppresses the trailing click", async () => {
    await renderSidebar();
    stubRailRects([
      ["Chat", 0, 40],
      ["Agents", 50, 90],
      ["Skills", 100, 140],
    ]);

    const chatButton = railButton("Chat");
    await act(async () => {
      dispatchPointer(chatButton, "pointerdown", { clientY: 20 });
      vi.advanceTimersByTime(360);
      dispatchPointer(chatButton, "pointermove", { clientY: 130 });
      dispatchPointer(chatButton, "pointerup", { clientY: 130 });
      chatButton.click();
    });

    expect(reorderPinnedApps).toHaveBeenCalledWith(["agents", "skills", "chat"]);
    expect(openApp).not.toHaveBeenCalled();
  });

  it("does not render a detached drag ghost during long press", async () => {
    await renderSidebar();
    stubRailRects([
      ["Chat", 0, 40],
      ["Agents", 50, 90],
      ["Skills", 100, 140],
    ]);

    const chatButton = railButton("Chat");
    await act(async () => {
      dispatchPointer(chatButton, "pointerdown", { clientY: 20 });
      vi.advanceTimersByTime(360);
      dispatchPointer(chatButton, "pointermove", { clientY: 500 });
    });

    expect(container.querySelector(".bs-sidebar__rail-drag-ghost")).toBeNull();
    expect(railButton("Chat").className).toContain("is-dragging");
  });

  it("cancels a pending long press when the pointer moves before the timer", async () => {
    await renderSidebar();
    const chatButton = railButton("Chat");

    await act(async () => {
      dispatchPointer(chatButton, "pointerdown", { clientY: 20 });
      dispatchPointer(chatButton, "pointermove", { clientY: 40 });
      vi.advanceTimersByTime(360);
      dispatchPointer(chatButton, "pointerup", { clientY: 40 });
      chatButton.click();
    });

    expect(openApp).toHaveBeenCalledWith("chat");
    expect(reorderPinnedApps).not.toHaveBeenCalled();
  });

  it("does not render the application rail on mobile", async () => {
    await renderSidebar({ isMobileLayout: true });

    expect(container.querySelector(".bs-sidebar__rail")).toBeNull();
    expect(reorderPinnedApps).not.toHaveBeenCalled();
  });

  it("keeps Settings visible as a static rail shortcut outside the reorder scroller", async () => {
    await renderSidebar({ apps: [...apps, app("settings", "Settings")] });

    const settingsButton = railButton("Settings");
    expect(settingsButton.closest(".bs-sidebar__rail-static")).not.toBeNull();
    expect(settingsButton.closest(".bs-sidebar__rail-apps")).toBeNull();

    await act(async () => {
      settingsButton.click();
    });

    expect(openSettings).toHaveBeenCalledTimes(1);
    expect(openApp).not.toHaveBeenCalledWith("settings");
  });

  it("keeps the mobile sidebar open when the pointer leaves toward the header", async () => {
    await renderSidebar({ isMobileLayout: true });
    const sidebar = container.querySelector(".bs-sidebar");
    if (!(sidebar instanceof HTMLElement)) {
      throw new Error("Sidebar was not mounted.");
    }

    await act(async () => {
      sidebar.dispatchEvent(new MouseEvent("mouseleave", { bubbles: true, cancelable: true }));
    });

    expect(closeSidebar).not.toHaveBeenCalled();
  });

  it("supports keyboard reorder with Alt and arrow keys", async () => {
    await renderSidebar();

    await act(async () => {
      railButton("Agents").dispatchEvent(
        new KeyboardEvent("keydown", { altKey: true, bubbles: true, cancelable: true, key: "ArrowUp" }),
      );
    });

    expect(reorderPinnedApps).toHaveBeenCalledWith(["agents", "chat", "skills"]);
  });

  it("renders a desktop resize icon and drags the sidebar width", async () => {
    await renderSidebar();

    const handle = resizeHandle();
    expect(handle.textContent).toContain("arrow_right_alt");
    expect(handle.parentElement?.className).toContain("bs-sidebar");
    handle.getBoundingClientRect = () => ({ bottom: 500, height: 400, left: 0, right: 40, toJSON: () => ({}), top: 100, width: 40, x: 0, y: 100 });

    await act(async () => {
      dispatchPointer(handle, "pointerdown", { clientX: 320, clientY: 200 });
      dispatchPointer(handle, "pointermove", { clientX: 392, clientY: 200 });
      dispatchPointer(handle, "pointerup", { clientX: 392, clientY: 200 });
    });

    expect(resizeSidebar).toHaveBeenCalledWith(392);
    expect(handle.style.getPropertyValue("--bs-sidebar-resize-icon-y")).toBe("100px");
  });

  it("does not render the resize icon on mobile", async () => {
    await renderSidebar({ isMobileLayout: true });

    expect(container.querySelector(".bs-sidebar__resize-handle")).toBeNull();
  });

  it("drops reliably into the penultimate and final slots", async () => {
    await renderSidebar({ pinnedAppIds: ["chat", "agents", "skills", "docs"] });
    stubRailRects([
      ["Chat", 0, 40],
      ["Agents", 50, 90],
      ["Skills", 100, 140],
      ["Docs", 150, 190],
    ]);

    const chatButton = railButton("Chat");
    await act(async () => {
      dispatchPointer(chatButton, "pointerdown", { clientY: 20 });
      vi.advanceTimersByTime(360);
      dispatchPointer(chatButton, "pointermove", { clientY: 101 });
      dispatchPointer(chatButton, "pointerup", { clientY: 101 });
    });

    expect(reorderPinnedApps).toHaveBeenCalledWith(["agents", "skills", "chat", "docs"]);

    reorderPinnedApps.mockClear();
    await renderSidebar({ pinnedAppIds: ["chat", "agents", "skills", "docs"] });
    stubRailRects([
      ["Chat", 0, 40],
      ["Agents", 50, 90],
      ["Skills", 100, 140],
      ["Docs", 150, 190],
    ]);

    const nextChatButton = railButton("Chat");
    await act(async () => {
      dispatchPointer(nextChatButton, "pointerdown", { clientY: 20 });
      vi.advanceTimersByTime(360);
      dispatchPointer(nextChatButton, "pointermove", { clientY: 151 });
      dispatchPointer(nextChatButton, "pointerup", { clientY: 151 });
    });

    expect(reorderPinnedApps).toHaveBeenCalledWith(["agents", "skills", "docs", "chat"]);
  });

  async function renderSidebar(overrides: Partial<{ apps: AppRegistryItem[]; isMobileLayout: boolean; pinnedAppIds: string[] }> = {}) {
    await act(async () => {
      root.render(
        <Sidebar
          activeAppId="chat"
          activeAppParams={{}}
          activeWorkspaceId="default"
          apps={overrides.apps ?? apps}
          frameScope={{ sessionGeneration: "session-default", workspaceId: "default" }}
          isLoading={false}
          isMobileLayout={overrides.isMobileLayout ?? false}
          isOpen={true}
          isPinned={false}
          mobilePrimaryActionRequestId={0}
          mode="rail"
          onClose={closeSidebar}
          onModeChange={vi.fn()}
          onOpenApp={(appId, params) => {
            if (params === undefined) {
              openApp(appId);
              return;
            }
            openApp(appId, params);
          }}
          onOpenSettings={openSettings}
          onOpenSidebar={vi.fn()}
          onPrimaryActionStateChange={vi.fn()}
          onReorderPinnedApps={(appIds) => reorderPinnedApps(appIds)}
          onSidebarDetailsWidthChange={(widthPx) => resizeSidebar(widthPx)}
          onSidebarResizeActiveChange={vi.fn()}
          onWorkspaceChanged={vi.fn()}
          pinnedAppIds={overrides.pinnedAppIds ?? ["chat", "agents", "skills"]}
          railMetrics={{}}
          sidebarDetailsWidthPx={320}
          user={user}
          workspaces={workspaces}
        />,
      );
    });
  }

  function railButton(labelPrefix: string): HTMLButtonElement {
    const button = Array.from(container.querySelectorAll("button")).find((candidate) =>
      candidate.getAttribute("aria-label")?.startsWith(labelPrefix),
    );
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error(`Rail button ${labelPrefix} was not mounted.`);
    }
    return button;
  }

  function resizeHandle(): HTMLButtonElement {
    const button = container.querySelector(".bs-sidebar__resize-handle");
    if (!(button instanceof HTMLButtonElement)) {
      throw new Error("Resize handle was not mounted.");
    }
    return button;
  }

  function stubRailRects(rects: Array<[string, number, number]>) {
    for (const [labelPrefix, top, bottom] of rects) {
      const item = railButton(labelPrefix).closest(".bs-sidebar__rail-item");
      if (!(item instanceof HTMLElement)) {
        throw new Error(`Rail item ${labelPrefix} was not mounted.`);
      }
      item.getBoundingClientRect = () => ({ bottom, height: bottom - top, left: 0, right: 40, toJSON: () => ({}), top, width: 40, x: 0, y: top });
      railButton(labelPrefix).getBoundingClientRect = () => ({ bottom, height: bottom - top, left: 0, right: 40, toJSON: () => ({}), top, width: 40, x: 0, y: top });
    }
    const railApps = container.querySelector(".bs-sidebar__rail-apps");
    if (railApps instanceof HTMLElement) {
      railApps.getBoundingClientRect = () => ({ bottom: 160, height: 160, left: 0, right: 60, toJSON: () => ({}), top: 0, width: 60, x: 0, y: 0 });
    }
  }

  function dispatchPointer(target: Element, type: string, options: { clientX?: number; clientY: number }) {
    const event = new MouseEvent(type, {
      bubbles: true,
      button: 0,
      cancelable: true,
      clientX: options.clientX ?? 20,
      clientY: options.clientY,
    }) as MouseEvent & { pointerId: number; pointerType: string };
    Object.defineProperty(event, "pointerId", { value: 1 });
    Object.defineProperty(event, "pointerType", { value: "mouse" });
    target.dispatchEvent(event);
  }
});
