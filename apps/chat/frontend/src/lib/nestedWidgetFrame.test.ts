/**
 * @vitest-environment happy-dom
 */
import { describe, expect, it, vi } from "vitest";
import type { WidgetRegistryItem } from "../api/types";
import {
  isNestedWidgetLoadedMessage,
  submitNestedWidgetBootstrap,
  validateNestedWidgetLaunch,
} from "./nestedWidgetFrame";

const widget: WidgetRegistryItem = {
  actions: {},
  content_kinds: ["storage.file.preview"],
  frontend_mount: "/api/apps/widgets/storage/file-preview/frontend/",
  host: "chat",
  owner_app_id: "storage",
  widget_id: "file-preview",
};
const parentOrigin = "https://chat-frame.example";
const contextToken = "signed-context";

describe("nested widget frame launch", () => {
  it("accepts only an exact parent/host/owner/widget attestation", () => {
    const launch = validateNestedWidgetLaunch(validPayload(), widget, parentOrigin, contextToken);

    expect(launch).toMatchObject({
      hostAppId: "chat",
      origin: "https://storage-widget.example",
      ownerAppId: "storage",
      parentOrigin,
      widgetId: "file-preview",
    });
    expect(launch.targetUrl).toBe(validPayload().frontend_url);
    expect(() => validateNestedWidgetLaunch({ ...validPayload(), parent_origin: "https://other.example" }, widget, parentOrigin, contextToken)).toThrow();
    expect(() => validateNestedWidgetLaunch({ ...validPayload(), owner_app_id: "chat" }, widget, parentOrigin, contextToken)).toThrow();
    expect(() => validateNestedWidgetLaunch({ ...validPayload(), origin: parentOrigin }, widget, parentOrigin, contextToken)).toThrow();
    expect(() => validateNestedWidgetLaunch({ ...validPayload(), bootstrap_url: "https://other.example/bootstrap" }, widget, parentOrigin, contextToken)).toThrow();
    expect(() => validateNestedWidgetLaunch({ ...validPayload(), frontend_url: "https://storage-widget.example/other" }, widget, parentOrigin, contextToken)).toThrow();
    expect(() => validateNestedWidgetLaunch({ ...validPayload(), frontend_url: `${validPayload().frontend_url}&extra=value` }, widget, parentOrigin, contextToken)).toThrow();
    expect(() => validateNestedWidgetLaunch({ ...validPayload(), bootstrap_transport: "form" }, widget, parentOrigin, contextToken)).toThrow();
  });

  it("exchanges only the opaque ticket with exact-origin CORS before navigating the iframe", async () => {
    const frame = document.createElement("iframe");
    frame.name = "nested-storage-widget";
    const fetchImpl = vi.fn(async () => new Response(null, { status: 204 }));

    await submitNestedWidgetBootstrap(
      frame,
      validateNestedWidgetLaunch(validPayload(), widget, parentOrigin, contextToken),
      fetchImpl,
    );

    expect(fetchImpl).toHaveBeenCalledWith(validPayload().bootstrap_url, expect.objectContaining({
      body: "ticket=one-shot-ticket",
      cache: "no-store",
      credentials: "include",
      method: "POST",
      redirect: "error",
      referrerPolicy: "no-referrer",
    }));
    expect(frame.getAttribute("src")).toBe(validPayload().frontend_url);
  });

  it("requires the exact nested origin, frame source, owner, and widget on readiness", () => {
    const frame = document.createElement("iframe");
    document.body.append(frame);
    const launch = validateNestedWidgetLaunch(validPayload(), widget, parentOrigin, contextToken);
    const message = (overrides: Record<string, unknown> = {}, origin = launch.origin, source = frame.contentWindow) => new MessageEvent("message", {
      data: {
        type: "maverick.app-frame.loaded",
        owner_app_id: "storage",
        widget_id: "file-preview",
        ...overrides,
      },
      origin,
      source,
    });

    expect(isNestedWidgetLoadedMessage(message(), frame, launch)).toBe(true);
    expect(isNestedWidgetLoadedMessage(message({}, "https://other.example"), frame, launch)).toBe(false);
    expect(isNestedWidgetLoadedMessage(message({ widget_id: "other" }), frame, launch)).toBe(false);
    expect(isNestedWidgetLoadedMessage(message({}, launch.origin, window), frame, launch)).toBe(false);
    frame.remove();
  });
});

function validPayload() {
  return {
    bootstrap_url: "https://storage-widget.example/.well-known/maverick-app-frame-bootstrap",
    bootstrap_transport: "cors",
    expires_in_seconds: 60,
    frontend_url: "https://storage-widget.example/api/apps/widgets/storage/file-preview/frontend/#context=signed-context",
    host_app_id: "chat",
    method: "POST",
    origin: "https://storage-widget.example",
    owner_app_id: "storage",
    parent_origin: parentOrigin,
    ticket: "one-shot-ticket",
    ticket_field: "ticket",
    widget_id: "file-preview",
  };
}
