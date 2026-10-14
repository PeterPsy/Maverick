// @vitest-environment happy-dom

import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { IsolatedLoopinoFrame, requestAppFrameLaunch } from "../src/components/IsolatedLoopinoFrame";
import {
  appFrameBrowserFeaturePolicy,
  isLoopinoFrameMessage,
  registeredLoopinoFrameOwner,
  postToLoopinoFrame,
  setLoopinoFrameOrigin,
  widgetFrameBrowserFeaturePolicy,
} from "../src/iframePolicy";
import { shellCacheLifecycle, subscribeShellAuthorizationRevocation } from "../src/pwaCacheRuntime";

const FRAME_SCOPE = Object.freeze({ sessionGeneration: "session-one", workspaceId: "default" });

describe("isolated Loopino frame policy", () => {
  afterEach(() => {
    document.body.replaceChildren();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("accepts messages only from the registered exact frame origin and source", () => {
    const frame = document.createElement("iframe");
    const foreign = document.createElement("iframe");
    document.body.append(frame, foreign);
    setLoopinoFrameOrigin(frame, "https://af-session.sidecars.loopino.test", "storage", FRAME_SCOPE);

    expect(isLoopinoFrameMessage(message(frame, "https://af-session.sidecars.loopino.test"), frame)).toBe(true);
    expect(registeredLoopinoFrameOwner(message(frame, "https://af-session.sidecars.loopino.test"), FRAME_SCOPE)).toBe("storage");
    expect(registeredLoopinoFrameOwner(message(frame, "https://af-session.sidecars.loopino.test"), {
      sessionGeneration: "session-two",
      workspaceId: "other",
    })).toBeNull();
    expect(isLoopinoFrameMessage(message(frame, "https://attacker.example"), frame)).toBe(false);
    expect(isLoopinoFrameMessage(message(foreign, "https://af-session.sidecars.loopino.test"), frame)).toBe(false);
    expect(() => setLoopinoFrameOrigin(frame, window.location.origin, "storage", FRAME_SCOPE)).toThrow(/distinct exact origin/i);
    setLoopinoFrameOrigin(frame, null, "storage", FRAME_SCOPE);
  });

  it("posts only to the registered exact origin and never broadens the target", () => {
    const frame = document.createElement("iframe");
    document.body.append(frame);
    const postMessage = vi.spyOn(frame.contentWindow!, "postMessage");

    postToLoopinoFrame(frame, { type: "ignored-before-registration" });
    expect(postMessage).not.toHaveBeenCalled();

    setLoopinoFrameOrigin(frame, "https://af-session.sidecars.loopino.test", "storage", FRAME_SCOPE);
    postToLoopinoFrame(frame, { type: "accepted" });
    expect(postMessage).toHaveBeenCalledWith(
      { type: "accepted" },
      "https://af-session.sidecars.loopino.test",
    );
    expect(postMessage).not.toHaveBeenCalledWith(expect.anything(), "*");
    setLoopinoFrameOrigin(frame, null, "storage", FRAME_SCOPE);
  });

  it("delegates clipboard writes only to Chat app and widget frames", () => {
    expect(appFrameBrowserFeaturePolicy("chat")).toBe("clipboard-write; fullscreen; microphone");
    expect(widgetFrameBrowserFeaturePolicy("chat")).toBe("clipboard-write; fullscreen; microphone");
    expect(appFrameBrowserFeaturePolicy("storage")).toBe("fullscreen; microphone");
    expect(widgetFrameBrowserFeaturePolicy("storage")).toBe("fullscreen");
  });

  it("keeps the iframe on a themed local document until it self-submits the isolated bootstrap", async () => {
    const isolatedOrigin = "https://af-session.sidecars.loopino.test";
    let resolveLaunch!: (response: Response) => void;
    const launchResponse = new Promise<Response>((resolve) => {
      resolveLaunch = resolve;
    });
    vi.stubGlobal("fetch", vi.fn(() => launchResponse));
    const launchPayload = {
      bootstrap_url: `${isolatedOrigin}/.well-known/loopino-app-frame-bootstrap`,
      method: "POST",
      origin: isolatedOrigin,
      ticket: "one-shot-ticket",
      ticket_field: "ticket",
    };
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(createElement(IsolatedLoopinoFrame, {
        appId: "storage",
        frameScope: FRAME_SCOPE,
        launchPath: "/apps/storage/",
      }));
    });

    const frame = container.querySelector("iframe");
    resolveLaunch(new Response(JSON.stringify(launchPayload), { status: 200 }));
    await vi.waitFor(() => expect(frame?.dataset.loopinoFrameOrigin).toBe(isolatedOrigin));
    act(() => frame?.dispatchEvent(new Event("load")));
    acknowledgeBootstrap(frame!);

    expect(frame?.getAttribute("src")).toBeNull();
    expect(frame?.srcdoc).toContain("#070708");
    expect(frame?.srcdoc).toContain("loopino.app-frame.bootstrap");
    expect(frame?.srcdoc).toContain('form.target="_self"');
    expect(frame?.dataset.loopinoFrameOrigin).toBe(isolatedOrigin);
    expect(frame?.dataset.loopinoFrameBootstrapArmed).toBe("true");
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
      bootstrap_url: `${window.location.origin}/.well-known/loopino-app-frame-bootstrap`,
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

  it("routes isolated launch authorization failures through the shell revocation channel", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 401 })));
    const cleanup = vi.spyOn(shellCacheLifecycle, "authorizationFailure")
      .mockResolvedValue({ pendingCleanupCount: 0, removed: 0, status: "complete" });
    const revoked = vi.fn();
    const unsubscribe = subscribeShellAuthorizationRevocation(revoked);

    await expect(requestAppFrameLaunch("storage", "/apps/storage/"))
      .rejects.toThrow(/unable to launch isolated app frame/i);

    expect(revoked).toHaveBeenCalledOnce();
    expect(revoked).toHaveBeenCalledWith(401);
    expect(cleanup).toHaveBeenCalledOnce();
    unsubscribe();
  });
});

function message(frame: HTMLIFrameElement, origin: string): MessageEvent {
  return new MessageEvent("message", {
    data: { type: "test" },
    origin,
    source: frame.contentWindow,
  });
}

function acknowledgeBootstrap(frame: HTMLIFrameElement) {
  const bootstrapId = frame.srcdoc.match(/data-loopino-loader="([^"]+)"/)?.[1];
  if (!bootstrapId) throw new Error("Expected a local app-frame bootstrap relay.");
  act(() => {
    window.dispatchEvent(new MessageEvent("message", {
      data: {
        bootstrap_id: bootstrapId,
        type: "loopino.app-frame.bootstrap-submitted",
      },
      origin: window.location.origin,
      source: frame.contentWindow,
    }));
  });
}
