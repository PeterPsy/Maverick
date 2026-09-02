// @vitest-environment happy-dom

import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { IsolatedMaverickFrame, requestAppFrameLaunch } from "../src/components/IsolatedMaverickFrame";
import {
  isMaverickFrameMessage,
  postToMaverickFrame,
  setMaverickFrameOrigin,
} from "../src/iframePolicy";

describe("isolated Maverick frame policy", () => {
  afterEach(() => {
    document.body.replaceChildren();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("accepts messages only from the registered exact frame origin and source", () => {
    const frame = document.createElement("iframe");
    const foreign = document.createElement("iframe");
    document.body.append(frame, foreign);
    setMaverickFrameOrigin(frame, "https://af-session.sidecars.maverick.test");

    expect(isMaverickFrameMessage(message(frame, "https://af-session.sidecars.maverick.test"), frame)).toBe(true);
    expect(isMaverickFrameMessage(message(frame, "https://attacker.example"), frame)).toBe(false);
    expect(isMaverickFrameMessage(message(foreign, "https://af-session.sidecars.maverick.test"), frame)).toBe(false);
    expect(() => setMaverickFrameOrigin(frame, window.location.origin)).toThrow(/distinct exact origin/i);
  });

  it("posts only to the registered exact origin and never broadens the target", () => {
    const frame = document.createElement("iframe");
    document.body.append(frame);
    const postMessage = vi.spyOn(frame.contentWindow!, "postMessage");

    postToMaverickFrame(frame, { type: "ignored-before-registration" });
    expect(postMessage).not.toHaveBeenCalled();

    setMaverickFrameOrigin(frame, "https://af-session.sidecars.maverick.test");
    postToMaverickFrame(frame, { type: "accepted" });
    expect(postMessage).toHaveBeenCalledWith(
      { type: "accepted" },
      "https://af-session.sidecars.maverick.test",
    );
    expect(postMessage).not.toHaveBeenCalledWith(expect.anything(), "*");
  });

  it("keeps the iframe on about:blank until it submits the isolated bootstrap", async () => {
    const isolatedOrigin = "https://af-session.sidecars.maverick.test";
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      bootstrap_url: `${isolatedOrigin}/.well-known/maverick-app-frame-bootstrap`,
      method: "POST",
      origin: isolatedOrigin,
      ticket: "one-shot-ticket",
      ticket_field: "ticket",
    }), { status: 200 })));
    let submittedAction = "";
    let submittedTarget = "";
    let submittedTicket = "";
    vi.spyOn(HTMLFormElement.prototype, "submit").mockImplementation(function submit(this: HTMLFormElement) {
      submittedAction = this.action;
      submittedTarget = this.target;
      submittedTicket = this.querySelector<HTMLInputElement>('input[name="ticket"]')?.value || "";
    });
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(createElement(IsolatedMaverickFrame, {
        appId: "storage",
        launchPath: "/apps/storage/",
      }));
    });
    await vi.waitFor(() => expect(submittedTicket).toBe("one-shot-ticket"));

    const frame = container.querySelector("iframe");
    expect(frame?.getAttribute("src")).toBe("about:blank");
    expect(frame?.dataset.maverickFrameOrigin).toBe(isolatedOrigin);
    expect(submittedAction).toBe(`${isolatedOrigin}/.well-known/maverick-app-frame-bootstrap`);
    expect(submittedTarget).toBe(frame?.name);
    expect(fetch).toHaveBeenCalledWith(
      "/api/app-frames/browser-launch",
      expect.objectContaining({
        body: JSON.stringify({ app_id: "storage", path: "/apps/storage/" }),
        method: "POST",
      }),
    );

    act(() => root.unmount());
  });

  it("rejects launch payloads that reuse the platform origin", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      bootstrap_url: `${window.location.origin}/.well-known/maverick-app-frame-bootstrap`,
      method: "POST",
      origin: window.location.origin,
      ticket: "ticket",
      ticket_field: "ticket",
    }), { status: 200 })));

    await expect(requestAppFrameLaunch("storage", "/apps/storage/"))
      .rejects.toThrow(/invalid isolated app-frame launch/i);
  });

  it("rejects legacy same-origin launch payloads", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      launch_url: "/apps/storage/",
      mode: "same_origin",
      origin: window.location.origin,
    }), { status: 200 })));

    await expect(requestAppFrameLaunch("storage", "/apps/storage/"))
      .rejects.toThrow(/invalid isolated app-frame launch/i);
  });
});

function message(frame: HTMLIFrameElement, origin: string): MessageEvent {
  return new MessageEvent("message", {
    data: { type: "test" },
    origin,
    source: frame.contentWindow,
  });
}
