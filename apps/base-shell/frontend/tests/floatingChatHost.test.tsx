// @vitest-environment happy-dom

import { act } from "react";
import type { ComponentProps } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FloatingChatHost } from "../src/components/FloatingChatHost";
import type { ShellThemeState } from "../src/theme";

const widgetSlotMock = vi.fn((props: Record<string, unknown>) => {
  void props;
  return <div data-testid="widget-slot" />;
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

describe("FloatingChatHost mount gate", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    widgetSlotMock.mockClear();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("does not mount WidgetSlot while Chat is the active app", async () => {
    await renderHost(root, { isChatAppActive: true });

    expect(widgetSlotMock).not.toHaveBeenCalled();
    expect(container.querySelector("[data-testid='widget-slot']")).toBeNull();
  });

  it("does not mount the mobile widget when the mobile panel is closed", async () => {
    await renderHost(root, { isMobileLayout: true, isMobileChatOpen: false });

    expect(widgetSlotMock).not.toHaveBeenCalled();
  });

  it("mounts WidgetSlot when the floating host is visible", async () => {
    await renderHost(root, { isChatAppActive: false });

    expect(widgetSlotMock).toHaveBeenCalledTimes(1);
    expect(container.querySelector("[data-testid='widget-slot']")).not.toBeNull();
  });

  it.each(["overlay", "fixed-right"] as const)("keeps %s chat alive while Chat is active", async (floatingChatMode) => {
    await renderHost(root, { floatingChatMode });
    const widget = container.querySelector("[data-testid='widget-slot']");
    await renderHost(root, { floatingChatMode, isChatAppActive: true });
    expect(container.querySelector("[data-testid='widget-slot']")).toBe(widget);
    expect(container.querySelector(".bs-floating-chat-host")?.getAttribute("aria-hidden")).toBe("true");
    expect(widgetSlotMock.mock.calls.at(-1)?.[0].isActive).toBe(false);
    await renderHost(root, { floatingChatMode });
    expect(container.querySelector("[data-testid='widget-slot']")).toBe(widget);
  });

  it("preserves mobile chat across closing, reopening and visiting Chat", async () => {
    await renderHost(root, { isMobileLayout: true, isMobileChatOpen: true });
    const widget = container.querySelector("[data-testid='widget-slot']");
    await renderHost(root, { isMobileLayout: true, isMobileChatOpen: false });
    expect(container.querySelector("[data-testid='widget-slot']")).toBe(widget);
    await renderHost(root, { isMobileLayout: true, isMobileChatOpen: true, isChatAppActive: true });
    expect(container.querySelector("[data-testid='widget-slot']")).toBe(widget);
    await renderHost(root, { isMobileLayout: true, isMobileChatOpen: true });
    expect(container.querySelector("[data-testid='widget-slot']")).toBe(widget);
  });

  it("keeps one document across placements and discards it with the frame scope", async () => {
    await renderHost(root);
    const overlay = container.querySelector("[data-testid='widget-slot']");
    await renderHost(root, { floatingChatMode: "fixed-right" });
    expect(container.querySelectorAll("[data-testid='widget-slot']")).toHaveLength(1);
    await renderHost(root, { isMobileLayout: true, isMobileChatOpen: true });
    expect(container.querySelector("[data-testid='widget-slot']")).toBe(overlay);
    await renderHost(root);
    expect(container.querySelector("[data-testid='widget-slot']")).toBe(overlay);
    await renderHost(root, { isChatAppActive: true, frameScope: { ...FRAME_SCOPE, sessionGeneration: "new-session" } });
    expect(container.querySelectorAll("[data-testid='widget-slot']")).toHaveLength(0);
    await renderHost(root, { frameScope: { ...FRAME_SCOPE, sessionGeneration: "new-session" } });
    expect(container.querySelectorAll("[data-testid='widget-slot']")).toHaveLength(1);
    expect(container.querySelector("[data-testid='widget-slot']")).not.toBe(overlay);
  });

  it("exposes and enforces the shared budget on keyboard resizing", async () => {
    const onWidthChange = vi.fn();
    await renderHost(root, { floatingChatMode: "fixed-right", widthPx: 420, maxWidthPx: 430, onWidthChange });
    const separator = container.querySelector<HTMLElement>('[role="separator"]')!;
    expect(separator.getAttribute("aria-valuemax")).toBe("430");
    expect(separator.getAttribute("aria-valuenow")).toBe("420");
    await act(async () => separator.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true })));
    expect(onWidthChange).toHaveBeenLastCalledWith(430);
    await act(async () => separator.dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true })));
    expect(onWidthChange).toHaveBeenLastCalledWith(430);
  });

  it("passes active app params into the floating Chat widget context", async () => {
    await renderHost(root, {
      activeApp: {
        app_id: "design-studio",
        name: "Design Studio",
        version: "0.1.0",
        description: "OpenDesign",
        publisher: "Loopino",
        status: "enabled",
        distribution_mode: "bundled",
        source_access: "built-in",
        views: [],
        provides: [],
        requires: [],
        logo: null,
        frontend_mount: "/apps/design-studio/",
        frontend_role: "workspace",
        frontend_launchable: true,
        backend_mount: "/api/apps/design-studio/backend",
      },
      activeAppParams: { od_project_id: "od_project_1" },
    });

    expect(widgetSlotMock.mock.calls[0][0]).toMatchObject({
      content: { active_app: {
        app_id: "design-studio", logo: { kind: "glyph", value: "design_services" },
        params: { od_project_id: "od_project_1" },
      } },
    });
  });
});

async function renderHost(root: Root, overrides: Partial<ComponentProps<typeof FloatingChatHost>> = {}) {
  await act(async () => {
    root.render(
      <FloatingChatHost
        activeApp={null}
        activeWorkspaceId="default"
        floatingChatMode="overlay"
        isChatAppActive={false}
        isMobileChatClosing={false}
        isMobileChatOpen={false}
        isMobileLayout={false}
        navigationScope={null}
        onActiveThreadChange={vi.fn()}
        onCloseDock={vi.fn()}
        onCloseMobileChat={vi.fn()}
        onOpenApp={vi.fn()}
        onOpenDock={vi.fn()}
        onWidthChange={vi.fn()}
        shellTheme={shellTheme}
        threadId={null}
        user={{ username: "admin" }}
        widthPx={420}
        {...overrides}
        frameScope={overrides.frameScope ?? FRAME_SCOPE}
      />,
    );
    await Promise.resolve();
  });
}
