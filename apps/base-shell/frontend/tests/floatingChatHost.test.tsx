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
      />,
    );
    await Promise.resolve();
  });
}
