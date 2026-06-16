// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AppRegistryItem } from "../src/api";
import { AppFrameHost } from "../src/components/AppFrameHost";

type AppFrameParams = Record<string, string | boolean | null>;
type PostedMessage = {
  app_id?: string;
  params?: Record<string, string | boolean>;
  theme?: {
    color_scheme: "dark" | "light";
    effective: "dark" | "light";
    mode: "dark" | "light" | "system";
  };
  type?: string;
};

vi.mock("../src/api", () => ({
  getAppDependencies: vi.fn(),
  saveAppDependencySelection: vi.fn(),
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

const chat = app("chat", "Chat");
const agents = app("agents", "Agents");
const defaultTheme = {
  color_scheme: "dark" as const,
  effective: "dark" as const,
  mode: "dark" as const,
};

describe("AppFrameHost app frame readiness", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", MockWebSocket);
    interceptHappyDomIframeFetch();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    clearHappyDomFetchInterceptor();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("keeps the previous app frame visible until the target app is ready", async () => {
    await renderHost(root, chat);

    expect(frameByTitle(container, "Chat viewport").className).toContain("is-active");

    await renderHost(root, agents);
    const agentsFrame = await waitForFrame(container, "Agents viewport");

    expect(frameByTitle(container, "Chat viewport").className).toContain("is-active");
    expect(agentsFrame.className).toContain("is-hidden");
    expect(pendingIndicator(container)).toBeNull();

    await act(async () => {
      vi.advanceTimersByTime(140);
      await Promise.resolve();
    });

    expect(pendingIndicator(container)?.textContent).toBe("Loading Agents");
    expect(pendingIndicator(container)?.parentElement?.className).toContain("is-over-frame");

    await dispatchAppReady(agentsFrame, "agents");

    expect(frameByTitle(container, "Chat viewport").className).toContain("is-hidden");
    expect(frameByTitle(container, "Agents viewport").className).toContain("is-active");
    expect(pendingIndicator(container)).toBeNull();
  });

  it("reveals a loaded target frame if it does not send ready", async () => {
    await renderHost(root, chat);
    await renderHost(root, agents);
    const agentsFrame = await waitForFrame(container, "Agents viewport");

    expect(agentsFrame.className).toContain("is-hidden");

    await act(async () => {
      vi.advanceTimersByTime(140);
      agentsFrame.dispatchEvent(new Event("load"));
      vi.advanceTimersByTime(900);
      await Promise.resolve();
    });

    expect(frameByTitle(container, "Agents viewport").className).toContain("is-active");
    expect(pendingIndicator(container)).toBeNull();
  });

  it("resends pending navigation when a cold target app becomes ready", async () => {
    const appParams = { thread_id: "thread-1", include_archived: true, empty: null, skip: false };

    await renderHost(root, chat);
    await renderHost(root, agents, appParams);
    const agentsFrame = await waitForFrame(container, "Agents viewport");
    const postMessageSpy = vi.spyOn(agentsFrame.contentWindow!, "postMessage");

    await act(async () => {
      agentsFrame.dispatchEvent(new Event("load"));
      await Promise.resolve();
    });

    expect(navigateMessages(postMessageSpy)).toEqual([
      {
        app_id: "agents",
        params: { thread_id: "thread-1", include_archived: true },
        theme: defaultTheme,
        type: "maverick.app.navigate",
      },
    ]);

    await dispatchAppReady(agentsFrame, "agents");

    expect(navigateMessages(postMessageSpy)).toEqual([
      {
        app_id: "agents",
        params: { thread_id: "thread-1", include_archived: true },
        theme: defaultTheme,
        type: "maverick.app.navigate",
      },
      {
        app_id: "agents",
        params: { thread_id: "thread-1", include_archived: true },
        theme: defaultTheme,
        type: "maverick.app.navigate",
      },
    ]);

    await dispatchAppReady(agentsFrame, "agents");

    expect(navigateMessages(postMessageSpy)).toHaveLength(2);
  });
});

async function renderHost(root: Root, activeApp: AppRegistryItem, activeAppParams: AppFrameParams = {}) {
  await act(async () => {
    root.render(
      <AppFrameHost
        activeApp={activeApp}
        activeAppParams={activeAppParams}
        activeWorkspaceId="default"
        isMobileLayout={true}
        onOpenApp={vi.fn()}
      />,
    );
    await Promise.resolve();
  });
}

async function waitForFrame(parent: HTMLElement, title: string): Promise<HTMLIFrameElement> {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const frame = parent.querySelector(`iframe[title="${title}"]`);
    if (frame instanceof HTMLIFrameElement) {
      return frame;
    }
    await act(async () => {
      await Promise.resolve();
    });
  }
  throw new Error(`Frame ${title} was not mounted.`);
}

function frameByTitle(parent: HTMLElement, title: string): HTMLIFrameElement {
  const frame = parent.querySelector(`iframe[title="${title}"]`);
  if (!(frame instanceof HTMLIFrameElement)) {
    throw new Error(`Frame ${title} was not mounted.`);
  }
  return frame;
}

function navigateMessages(postMessageSpy: { mock: { calls: unknown[][] } }): PostedMessage[] {
  return postMessageSpy.mock.calls
    .map(([message]) => message)
    .filter((message): message is PostedMessage => {
      if (!message || typeof message !== "object" || Array.isArray(message)) {
        return false;
      }
      return (message as PostedMessage).type === "maverick.app.navigate";
    });
}

function pendingIndicator(parent: HTMLElement): HTMLElement | null {
  return parent.querySelector(".bs-shell-pending-indicator");
}

async function dispatchAppReady(frame: HTMLIFrameElement, appId: string) {
  if (!frame.contentWindow) {
    throw new Error("Expected iframe contentWindow.");
  }
  await act(async () => {
    window.dispatchEvent(
      new MessageEvent("message", {
        data: {
          app_id: appId,
          type: "maverick.app.ready",
        },
        origin: window.location.origin,
        source: frame.contentWindow,
      }),
    );
    await Promise.resolve();
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
      beforeAsyncRequest: async () => new Response("<!doctype html><html><body></body></html>"),
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

class MockWebSocket {
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;

  close() {
    return undefined;
  }
}
