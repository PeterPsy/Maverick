// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createWidgetContext, listWidgets, type WidgetRegistryItem } from "../src/api";
import { WidgetSlot } from "../src/components/WidgetSlot";
import { setMaverickFrameOrigin } from "../src/iframePolicy";

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
    vi.spyOn(globalThis, "fetch").mockResolvedValue(isolatedLaunchResponse());
    vi.spyOn(HTMLFormElement.prototype, "submit").mockImplementation(() => undefined);
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
    vi.restoreAllMocks();
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

  it("reports active chat thread changes back to the shell", async () => {
    const onActiveThreadChange = vi.fn();
    await renderOverlay(root, { onActiveThreadChange });

    await dispatchActiveThreadChanged(window, " selected-thread ", " floating-window ");

    expect(onActiveThreadChange).toHaveBeenCalledWith({
      navigationScope: "floating-window",
      ownerAppId,
      threadId: "selected-thread",
    });
  });
});

async function renderOverlay(
  root: Root,
  props: {
    onActiveThreadChange?: (event: { navigationScope: string; ownerAppId: string; threadId: string }) => void;
  } = {},
) {
  await act(async () => {
    root.render(
      <WidgetSlot
        activeWorkspaceId="default"
        content={{ placement: "bottom-right" }}
        contentKind="shell.overlay.bottomright"
        hostAppId="base-shell"
        label="Floating shell widget"
        onActiveThreadChange={props.onActiveThreadChange}
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
      if (!iframe.dataset.maverickFrameOrigin) {
        setMaverickFrameOrigin(iframe, "https://af-widget.sidecars.maverick.test");
      }
      iframe.dataset.maverickFrameBootstrapArmed = "true";
      return iframe;
    }
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 0));
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
        origin: messageOrigin(source),
        source,
      }),
    );
    await Promise.resolve();
  });
}

async function dispatchActiveThreadChanged(source: MessageEventSource, activeThreadId: string, navigationScope: string) {
  await act(async () => {
    window.dispatchEvent(
      new MessageEvent("message", {
        data: {
          active_thread_id: activeThreadId,
          navigation_scope: navigationScope,
          owner_app_id: ownerAppId,
          type: "maverick.chat.active-thread-changed",
        },
        origin: messageOrigin(source),
        source,
      }),
    );
    await Promise.resolve();
  });
}

function messageOrigin(source: MessageEventSource): string {
  if (source === window) return window.location.origin;
  const frame = [...document.querySelectorAll("iframe")]
    .find((candidate) => candidate.contentWindow === source);
  return frame?.dataset.maverickFrameOrigin || "https://foreign-frame.invalid";
}

function isolatedLaunchResponse(): Response {
  return new Response(JSON.stringify({
    bootstrap_url: "https://af-widget.sidecars.maverick.test/.well-known/maverick-app-frame-bootstrap",
    method: "POST",
    origin: "https://af-widget.sidecars.maverick.test",
    ticket: "test-ticket",
    ticket_field: "ticket",
  }), { headers: { "Content-Type": "application/json" }, status: 200 });
}
