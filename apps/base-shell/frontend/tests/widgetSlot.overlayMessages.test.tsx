// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createWidgetContext, listWidgets, type WidgetRegistryItem } from "../src/api";
import { WidgetSlot } from "../src/components/WidgetSlot";

vi.mock("../src/api", () => ({
  createWidgetContext: vi.fn(),
  listWidgets: vi.fn(),
}));

const ownerAppId = "chat";
const widgetId = "chat-floating";

function overlayWidget(): WidgetRegistryItem {
  return {
    actions: {},
    content_kinds: ["shell.overlay.bottomright"],
    frontend_mount: `/api/apps/widgets/${ownerAppId}/${widgetId}/frontend/`,
    host: "base-shell",
    owner_app_id: ownerAppId,
    widget_id: widgetId,
  };
}

describe("WidgetSlot overlay widget messages", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    interceptHappyDomIframeFetch();
    vi.mocked(listWidgets).mockResolvedValue({ items: [overlayWidget()] });
    vi.mocked(createWidgetContext).mockResolvedValue({ context: {}, context_token: "context-token" });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    clearHappyDomFetchInterceptor();
    vi.clearAllMocks();
  });

  it("accepts bounded px resize messages only from the mounted widget frame", async () => {
    await renderOverlay(root);
    const iframe = await waitForIframe(container);
    const frameWindow = requireFrameWindow(iframe);
    const slot = overlaySlot(container);

    expect(slot.style.width).toBe("3rem");
    expect(slot.style.height).toBe("3rem");

    await dispatchResize(window, "420px", "320px");
    expect(slot.style.width).toBe("3rem");
    expect(slot.style.height).toBe("3rem");

    await dispatchResize(frameWindow, "100vw", "320px");
    expect(slot.style.width).toBe("3rem");
    expect(slot.style.height).toBe("3rem");

    await dispatchResize(frameWindow, "420px", "320.2px");
    expect(slot.style.width).toBe("420px");
    expect(slot.style.height).toBe("321px");

    await dispatchResize(frameWindow, "9999px", "320px");
    expect(slot.style.width).toBe("420px");
    expect(slot.style.height).toBe("321px");

    await dispatchResize(frameWindow, "420px", "9999px");
    expect(slot.style.width).toBe("420px");
    expect(slot.style.height).toBe("321px");
  });

  it("ignores capture-area start messages from non-mounted frames", async () => {
    await renderOverlay(root);
    const iframe = await waitForIframe(container);
    const frameWindow = requireFrameWindow(iframe);
    const framePostMessage = vi.spyOn(frameWindow, "postMessage");
    framePostMessage.mockClear();

    await act(async () => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: {
            navigation_scope: "thread:alpha",
            owner_app_id: ownerAppId,
            type: "maverick.shell.capture-area.start",
            widget_id: widgetId,
          },
          origin: window.location.origin,
          source: window,
        }),
      );
      await Promise.resolve();
    });

    expect(framePostMessage).not.toHaveBeenCalledWith(
      expect.objectContaining({ type: "maverick.widget.capture-area.error" }),
      window.location.origin,
    );
  });
});

async function renderOverlay(root: Root) {
  await act(async () => {
    root.render(
      <WidgetSlot
        activeWorkspaceId="default"
        content={{ placement: "bottom-right" }}
        contentKind="shell.overlay.bottomright"
        hostAppId="base-shell"
        label="Floating shell widget"
        onOpenApp={vi.fn()}
        size="overlay"
      />,
    );
  });
}

function interceptHappyDomIframeFetch() {
  const happyDomWindow = window as Window & {
    happyDOM?: {
      settings?: {
        fetch?: {
          interceptor?: {
            beforeAsyncRequest?: () => Promise<Response>;
          } | null;
        };
      };
    };
  };
  if (happyDomWindow.happyDOM?.settings?.fetch) {
    happyDomWindow.happyDOM.settings.fetch.interceptor = {
      beforeAsyncRequest: async () => new Response("<!doctype html><html></html>"),
    };
  }
}

function clearHappyDomFetchInterceptor() {
  const happyDomWindow = window as Window & {
    happyDOM?: { settings?: { fetch?: { interceptor?: unknown } } };
  };
  if (happyDomWindow.happyDOM?.settings?.fetch) {
    happyDomWindow.happyDOM.settings.fetch.interceptor = null;
  }
}

async function waitForIframe(parent: HTMLElement): Promise<HTMLIFrameElement> {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const iframe = parent.querySelector("iframe");
    if (iframe instanceof HTMLIFrameElement) {
      return iframe;
    }
    await act(async () => {
      await Promise.resolve();
    });
  }
  throw new Error("Widget iframe was not mounted.");
}

function requireFrameWindow(iframe: HTMLIFrameElement): Window {
  if (!iframe.contentWindow) {
    throw new Error("Expected iframe contentWindow.");
  }
  return iframe.contentWindow;
}

function overlaySlot(parent: HTMLElement): HTMLElement {
  const slot = parent.querySelector(".bs-widget-slot--overlay");
  if (!(slot instanceof HTMLElement)) {
    throw new Error("Overlay widget slot was not mounted.");
  }
  return slot;
}

async function dispatchResize(source: MessageEventSource, width: string, height: string) {
  await act(async () => {
    window.dispatchEvent(
      new MessageEvent("message", {
        data: {
          height,
          owner_app_id: ownerAppId,
          type: "maverick.widget.resize",
          widget_id: widgetId,
          width,
        },
        origin: window.location.origin,
        source,
      }),
    );
    await Promise.resolve();
  });
}
