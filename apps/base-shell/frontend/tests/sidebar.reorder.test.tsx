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
  user_id: "user-admin",
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
  let reorderPinnedApps: ReturnType<typeof vi.fn<(appIds: string[]) => void>>;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers();
    HTMLElement.prototype.setPointerCapture = vi.fn();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    openApp = vi.fn<(appId: string, params?: Record<string, string | boolean | null>) => void>();
    reorderPinnedApps = vi.fn<(appIds: string[]) => void>();
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

  it("keeps the drag ghost clamped inside the rail bounds", async () => {
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

    const ghost = container.querySelector(".bs-sidebar__rail-drag-ghost");
    expect(ghost).toBeInstanceOf(HTMLElement);
    expect((ghost as HTMLElement).style.left).toBe("30px");
    expect((ghost as HTMLElement).style.top).toBe("140px");
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

  it("does not enable long-press reorder on mobile", async () => {
    await renderSidebar({ isMobileLayout: true });
    const chatButton = railButton("Chat");

    await act(async () => {
      dispatchPointer(chatButton, "pointerdown", { clientY: 20 });
      vi.advanceTimersByTime(360);
      dispatchPointer(chatButton, "pointermove", { clientY: 130 });
      dispatchPointer(chatButton, "pointerup", { clientY: 130 });
    });

    expect(reorderPinnedApps).not.toHaveBeenCalled();
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
      dispatchPointer(chatButton, "pointermove", { clientY: 135 });
      dispatchPointer(chatButton, "pointerup", { clientY: 135 });
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
      dispatchPointer(nextChatButton, "pointermove", { clientY: 180 });
      dispatchPointer(nextChatButton, "pointerup", { clientY: 180 });
    });

    expect(reorderPinnedApps).toHaveBeenCalledWith(["agents", "skills", "docs", "chat"]);
  });

  async function renderSidebar(overrides: Partial<{ isMobileLayout: boolean; pinnedAppIds: string[] }> = {}) {
    await act(async () => {
      root.render(
        <Sidebar
          activeAppId="chat"
          activeAppParams={{}}
          activeWorkspaceId="default"
          apps={apps}
          isLoading={false}
          isMobileLayout={overrides.isMobileLayout ?? false}
          isOpen={true}
          isPinned={false}
          mobilePrimaryActionRequestId={0}
          mode="rail"
          onClose={vi.fn()}
          onModeChange={vi.fn()}
          onOpenApp={(appId, params) => {
            if (params === undefined) {
              openApp(appId);
              return;
            }
            openApp(appId, params);
          }}
          onOpenSettings={vi.fn()}
          onOpenSidebar={vi.fn()}
          onPrimaryActionStateChange={vi.fn()}
          onReorderPinnedApps={(appIds) => reorderPinnedApps(appIds)}
          onWorkspaceChanged={vi.fn()}
          pinnedAppIds={overrides.pinnedAppIds ?? ["chat", "agents", "skills"]}
          railMetrics={{}}
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

  function dispatchPointer(target: Element, type: string, options: { clientY: number }) {
    const event = new MouseEvent(type, {
      bubbles: true,
      button: 0,
      cancelable: true,
      clientX: 20,
      clientY: options.clientY,
    }) as MouseEvent & { pointerId: number; pointerType: string };
    Object.defineProperty(event, "pointerId", { value: 1 });
    Object.defineProperty(event, "pointerType", { value: "mouse" });
    target.dispatchEvent(event);
  }
});
