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

describe("nested widget frame launch", () => {
  it("accepts only an exact parent/host/owner/widget attestation", () => {
    const launch = validateNestedWidgetLaunch(validPayload(), widget, parentOrigin);

    expect(launch).toMatchObject({
      hostAppId: "chat",
      origin: "https://storage-widget.example",
      ownerAppId: "storage",
      parentOrigin,
      widgetId: "file-preview",
    });
    expect(() => validateNestedWidgetLaunch({ ...validPayload(), parent_origin: "https://other.example" }, widget, parentOrigin)).toThrow();
    expect(() => validateNestedWidgetLaunch({ ...validPayload(), owner_app_id: "chat" }, widget, parentOrigin)).toThrow();
    expect(() => validateNestedWidgetLaunch({ ...validPayload(), origin: parentOrigin }, widget, parentOrigin)).toThrow();
    expect(() => validateNestedWidgetLaunch({ ...validPayload(), bootstrap_url: "https://other.example/bootstrap" }, widget, parentOrigin)).toThrow();
  });

  it("submits only the opaque ticket through a hidden POST form targeted at the iframe", () => {
    const frame = document.createElement("iframe");
    frame.name = "nested-storage-widget";
    document.body.append(frame);
    const submit = vi.spyOn(HTMLFormElement.prototype, "submit").mockImplementation(function (this: HTMLFormElement) {
      expect(this.method).toBe("POST");
      expect(this.action).toBe(validPayload().bootstrap_url);
      expect(this.target).toBe(frame.name);
      expect(new FormData(this).get("ticket")).toBe("one-shot-ticket");
    });

    submitNestedWidgetBootstrap(
      frame,
      validateNestedWidgetLaunch(validPayload(), widget, parentOrigin),
    );

    expect(submit).toHaveBeenCalledTimes(1);
    expect(document.querySelector("form")).toBeNull();
    frame.remove();
    submit.mockRestore();
  });

  it("requires the exact nested origin, frame source, owner, and widget on readiness", () => {
    const frame = document.createElement("iframe");
    document.body.append(frame);
    const launch = validateNestedWidgetLaunch(validPayload(), widget, parentOrigin);
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
    expires_in_seconds: 60,
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
