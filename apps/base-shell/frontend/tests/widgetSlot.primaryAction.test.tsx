// @vitest-environment happy-dom

import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createWidgetContext, listWidgets, type WidgetRegistryItem } from "../src/api";
import { WidgetSlot } from "../src/components/WidgetSlot";
import type { WidgetPrimaryActionState } from "../src/components/WidgetSlot";
import { setMaverickFrameOrigin } from "../src/iframePolicy";

vi.mock("../src/api", () => ({
  createWidgetContext: vi.fn(),
  listWidgets: vi.fn(),
}));

const ownerAppId = "agents";
const widgetId = "agents-sidebar-footer";

function footerWidget(): WidgetRegistryItem {
  return {
    actions: {},
    content_kinds: ["shell.sidebar.footer"],
    frontend_mount: `/api/apps/widgets/${ownerAppId}/${widgetId}/frontend/`,
    host: "base-shell",
    owner_app_id: ownerAppId,
    widget_id: widgetId,
  };
}

function PrimaryActionHarness({ onOpenSidebar }: { onOpenSidebar: () => void }) {
  const [primaryAction, setPrimaryAction] = useState<WidgetPrimaryActionState>({
    available: false,
    label: "",
    preferredSurface: "app",
  });
  const [requestId, setRequestId] = useState(0);

  return (
    <>
      <button
        aria-label="Mobile primary action"
        data-preferred-surface={primaryAction.preferredSurface}
        disabled={!primaryAction.available}
        onClick={() => {
          if (primaryAction.preferredSurface === "sidebar") {
            onOpenSidebar();
          }
          setRequestId((current) => current + 1);
        }}
        type="button"
      >
        {primaryAction.label || "Primary action"}
      </button>
      <WidgetSlot
        activeWorkspaceId="default"
        content={{ is_mobile_layout: true }}
        contentKind="shell.sidebar.footer"
        hostAppId="base-shell"
        label="App sidebar footer"
        onOpenApp={vi.fn()}
        onPrimaryActionStateChange={setPrimaryAction}
        preferredOwnerAppId={ownerAppId}
        primaryActionRequestId={requestId}
        size="compact"
      />
    </>
  );
}

describe("WidgetSlot primary action protocol", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    interceptHappyDomIframeFetch();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(isolatedLaunchResponse());
    vi.spyOn(HTMLFormElement.prototype, "submit").mockImplementation(() => undefined);
    vi.mocked(listWidgets).mockResolvedValue({ items: [footerWidget()] });
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

  it("accepts state only from the mounted footer frame and invokes that frame from the enabled header action", async () => {
    const openSidebar = vi.fn();
    await act(async () => {
      root.render(<PrimaryActionHarness onOpenSidebar={openSidebar} />);
    });
    const iframe = await waitForIframe(container);
    const frameWindow = iframe.contentWindow;
    if (!frameWindow) {
      throw new Error("Expected iframe contentWindow.");
    }
    const framePostMessage = vi.spyOn(frameWindow, "postMessage");
    const primaryButton = primaryActionButton(container);

    expect(primaryButton.disabled).toBe(true);

    await act(async () => {
      iframe.dispatchEvent(new Event("load"));
    });
    expect(framePostMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        owner_app_id: ownerAppId,
        type: "maverick.widget.primary-action.query",
        widget_id: widgetId,
      }),
      iframe.dataset.maverickFrameOrigin,
    );

    await dispatchWidgetState(window);
    expect(primaryButton.disabled).toBe(true);

    await dispatchWidgetState(frameWindow);
    expect(primaryButton.disabled).toBe(false);
    expect(primaryButton.dataset.preferredSurface).toBe("sidebar");
    expect(primaryButton.textContent).toBe("New Agent");

    await act(async () => {
      primaryButton.click();
    });
    expect(openSidebar).toHaveBeenCalledTimes(1);
    expect(framePostMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        owner_app_id: ownerAppId,
        type: "maverick.widget.primary-action.invoke",
        widget_id: widgetId,
      }),
      iframe.dataset.maverickFrameOrigin,
    );
  });

  it("shows shell pending chrome until a sidebar widget frame is loaded", async () => {
    const context = deferred<{ context: Record<string, unknown>; context_token: string }>();
    vi.mocked(createWidgetContext).mockReturnValueOnce(context.promise);

    await act(async () => {
      root.render(
        <WidgetSlot
          activeWorkspaceId="default"
          content={{ is_mobile_layout: false }}
          contentKind="shell.sidebar.primary"
          hostAppId="base-shell"
          label="App sidebar content"
          onOpenApp={vi.fn()}
          preferredOwnerAppId={ownerAppId}
        />,
      );
    });

    expect(pendingIndicator(container)?.textContent).toBe("Loading App sidebar content");
    expect(container.querySelector("iframe")).toBeNull();

    await act(async () => {
      context.resolve({ context: {}, context_token: "context-token" });
      await Promise.resolve();
    });
    const iframe = await waitForIframe(container);

    expect(pendingIndicator(container)?.textContent).toBe("Loading App sidebar content");

    await act(async () => {
      iframe.dispatchEvent(new Event("load"));
    });

    expect(pendingIndicator(container)).toBeNull();
  });

  it("opens the shell sidebar when a mounted widget or app requests it", async () => {
    const openSidebar = vi.fn();
    await act(async () => {
      root.render(
        <WidgetSlot
          activeWorkspaceId="default"
          content={{ is_mobile_layout: false }}
          contentKind="shell.sidebar.primary"
          hostAppId="base-shell"
          label="App sidebar content"
          onOpenApp={vi.fn()}
          onOpenSidebar={openSidebar}
          preferredOwnerAppId={ownerAppId}
        />,
      );
    });

    await dispatchSidebarOpen();

    expect(openSidebar).toHaveBeenCalledTimes(1);
  });

  it("opens external URLs only when requested by the mounted widget frame", async () => {
    const openedWindow = { focus: vi.fn(), opener: window } as unknown as Window;
    const openSpy = vi.spyOn(window, "open").mockReturnValue(openedWindow);
    await act(async () => {
      root.render(
        <WidgetSlot
          activeWorkspaceId="default"
          content={{ is_mobile_layout: true }}
          contentKind="shell.sidebar.footer"
          hostAppId="base-shell"
          label="App sidebar footer"
          onOpenApp={vi.fn()}
          preferredOwnerAppId={ownerAppId}
          size="compact"
        />,
      );
    });
    const iframe = await waitForIframe(container);
    const frameWindow = iframe.contentWindow;
    if (!frameWindow) {
      throw new Error("Expected iframe contentWindow.");
    }
    const authorizationUrl = "https://accounts.google.com/o/oauth2/v2/auth?client_id=client-id";

    await dispatchExternalUrl(window, authorizationUrl);
    await dispatchExternalUrl(frameWindow, "javascript:alert(1)");
    expect(openSpy).not.toHaveBeenCalled();

    await dispatchExternalUrl(frameWindow, authorizationUrl);

    expect(openSpy).toHaveBeenCalledWith(authorizationUrl, "_blank", "noopener,noreferrer");
    expect(openedWindow.focus).toHaveBeenCalledTimes(1);
  });
});

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

function primaryActionButton(parent: HTMLElement): HTMLButtonElement {
  const button = parent.querySelector('button[aria-label="Mobile primary action"]');
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error("Primary action button was not mounted.");
  }
  return button;
}

function pendingIndicator(parent: HTMLElement): HTMLElement | null {
  return parent.querySelector(".bs-shell-pending-indicator");
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

async function dispatchWidgetState(source: MessageEventSource) {
  await act(async () => {
    window.dispatchEvent(
      new MessageEvent("message", {
        data: {
          available: true,
          label: "New Agent",
          owner_app_id: ownerAppId,
          preferred_surface: "sidebar",
          type: "maverick.widget.primary-action.state",
          widget_id: widgetId,
        },
        origin: messageOrigin(source),
        source,
      }),
    );
  });
}

async function dispatchSidebarOpen() {
  await act(async () => {
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "maverick.shell.sidebar.open" },
        origin: window.location.origin,
        source: window,
      }),
    );
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

async function dispatchExternalUrl(source: MessageEventSource, url: string) {
  await act(async () => {
    window.dispatchEvent(
      new MessageEvent("message", {
        data: {
          owner_app_id: ownerAppId,
          type: "maverick.app.external-url",
          url,
          widget_id: widgetId,
        },
        origin: messageOrigin(source),
        source,
      }),
    );
    await Promise.resolve();
  });
}
