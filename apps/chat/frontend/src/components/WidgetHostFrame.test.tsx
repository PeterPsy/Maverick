/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createWidgetContext, listWidgets } from "../api/client";
import type { WidgetRegistryItem } from "../api/client";
import { WidgetHostFrame } from "./WidgetHostFrame";

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  createWidgetContext: vi.fn(),
  listWidgets: vi.fn(),
}));

const currentDir = dirname(fileURLToPath(import.meta.url));
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const widget: WidgetRegistryItem = {
  actions: {},
  content_kinds: ["storage.file.preview"],
  frontend_mount: "/api/apps/widgets/storage/file-preview/frontend/",
  host: "chat",
  owner_app_id: "storage",
  widget_id: "file-preview",
};

describe("WidgetHostFrame", () => {
  let container: HTMLDivElement;
  let root: Root;
  let submit: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    vi.mocked(listWidgets).mockResolvedValue({ items: [widget] });
    vi.mocked(createWidgetContext).mockResolvedValue({
      context: {},
      context_token: "signed-context",
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(validLaunch()), {
      headers: { "Content-Type": "application/json" },
      status: 200,
    })));
    submit = vi.spyOn(HTMLFormElement.prototype, "submit").mockImplementation(() => undefined);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("POST-bootstraps a distinct owner origin and reveals it only after an exact ready message", async () => {
    await renderWidget();

    const frame = container.querySelector("iframe");
    expect(frame).not.toBeNull();
    expect(frame?.getAttribute("src")).toBe("about:blank");
    expect(frame?.hidden).toBe(true);
    expect(submit).toHaveBeenCalledTimes(1);

    const fetchCall = vi.mocked(fetch).mock.calls[0];
    expect(fetchCall[0]).toBe("/api/apps/widgets/browser-launch");
    expect(JSON.parse(String(fetchCall[1]?.body))).toEqual({
      context_token: "signed-context",
      frontend_path: widget.frontend_mount,
      owner_app_id: "storage",
      widget_id: "file-preview",
    });

    await dispatchReady(frame!, "https://attacker.example");
    expect(frame?.hidden).toBe(true);

    await dispatchReady(frame!, validLaunch().origin);
    expect(container.querySelector("iframe")?.hidden).toBe(false);
    expect(container.querySelector('[data-testid="fallback"]')).toBeNull();
  });

  it("shows the host fallback when launch attestation does not match the Storage owner", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({
      ...validLaunch(),
      owner_app_id: "chat",
    }), { status: 200 }));

    await renderWidget();

    expect(container.querySelector("iframe")).toBeNull();
    expect(container.textContent).toContain("Nested widget launch attestation failed.");
  });

  it("shows the host fallback when the nested frame never confirms readiness", async () => {
    vi.useFakeTimers();
    try {
      await renderWidget();
      await act(async () => vi.advanceTimersByTime(10_000));

      expect(container.querySelector("iframe")).toBeNull();
      expect(container.textContent).toContain("Widget load timed out.");
    } finally {
      vi.useRealTimers();
    }
  });

  it("retains the widget sandbox, owned scrolling, and fullscreen contract", () => {
    const source = readFileSync(resolve(currentDir, "WidgetHostFrame.tsx"), "utf8");

    expect(source).toContain('scrolling="no"');
    expect(source).toContain('allow="fullscreen"');
    expect(source).toContain("allowFullScreen");
    expect(source).toContain('"maverick.widget.open-app"');
  });

  async function renderWidget() {
    await act(async () => {
      root.render(
        <WidgetHostFrame
          content={{ kind: "storage.file.preview", payload: { file_id: "file-1" } }}
          fallback={(state) => <div data-testid="fallback">{state.status}:{state.status === "fallback" ? state.reason : ""}</div>}
          hostAppId="chat"
          messageId="message-1"
        />,
      );
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
  }
});

function validLaunch() {
  return {
    bootstrap_url: "https://storage-widget.example/.well-known/maverick-app-frame-bootstrap",
    expires_in_seconds: 60,
    host_app_id: "chat",
    method: "POST",
    origin: "https://storage-widget.example",
    owner_app_id: "storage",
    parent_origin: window.location.origin,
    ticket: "one-shot-ticket",
    ticket_field: "ticket",
    widget_id: "file-preview",
  };
}

async function dispatchReady(frame: HTMLIFrameElement, origin: string) {
  await act(async () => {
    window.dispatchEvent(new MessageEvent("message", {
      data: {
        type: "maverick.app-frame.loaded",
        owner_app_id: "storage",
        widget_id: "file-preview",
      },
      origin,
      source: frame.contentWindow,
    }));
  });
}
