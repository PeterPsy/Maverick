/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  APP_FRAME_AUTHORIZATION_REQUIRED_MESSAGE,
  IsolatedMaverickFrame,
} from "./IsolatedMaverickFrame";
import { registeredMaverickFrameOwner } from "../iframePolicy";

type LaunchPayload = {
  bootstrap_url: string;
  method: "POST";
  origin: string;
  ticket: string;
  ticket_field: "ticket";
};

const roots: Root[] = [];
const FRAME_SCOPE = Object.freeze({ sessionGeneration: "session-one", workspaceId: "default" });
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

afterEach(() => {
  roots.splice(0).forEach((root) => act(() => root.unmount()));
  document.body.replaceChildren();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("IsolatedMaverickFrame authorization recovery", () => {
  it("relaunches only for an exact message from its registered frame and preserves the current route", async () => {
    const origin = "http://af-123.sidecars.maverick.localhost:8000";
    const initialLaunch = launchPayload(origin, "initial-ticket");
    const recoveredLaunch = launchPayload(origin, "recovered-ticket");
    const laterLaunch = launchPayload(origin, "later-ticket");
    const initialResponse = deferred<Response>();
    const fetchMock = vi.fn()
      .mockReturnValueOnce(initialResponse.promise)
      .mockResolvedValueOnce(jsonResponse(recoveredLaunch))
      .mockResolvedValueOnce(jsonResponse(laterLaunch));
    vi.stubGlobal("fetch", fetchMock);

    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    roots.push(root);
    await act(async () => {
      root.render(
        <IsolatedMaverickFrame
          appId="chat"
          frameScope={FRAME_SCOPE}
          launchPath="/apps/chat/?thread=initial"
          title="Chat"
        />,
      );
    });
    await flushPromises();

    const frame = container.querySelector("iframe");
    expect(frame).not.toBeNull();
    initialResponse.resolve(jsonResponse(initialLaunch));
    await flushPromises();
    const initialPostMessage = vi.spyOn(frame!.contentWindow!, "postMessage").mockImplementation(() => undefined);
    await finishBootstrap(frame as HTMLIFrameElement);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(initialPostMessage).toHaveBeenCalledWith(expect.objectContaining({
      bootstrap_id: expect.any(String),
      launch: initialLaunch,
      type: "maverick.app-frame.bootstrap",
    }), "*");
    const initialRelayDocument = frame!.srcdoc;
    expect(frame?.dataset.maverickFrameOrigin).toBe(origin);
    expect(registeredMaverickFrameOwner(new MessageEvent("message", {
      origin,
      source: frame?.contentWindow,
    }), FRAME_SCOPE)).toBe("chat");

    window.dispatchEvent(new MessageEvent("message", {
      data: { type: APP_FRAME_AUTHORIZATION_REQUIRED_MESSAGE },
      origin: "https://attacker.example",
      source: frame?.contentWindow,
    }));
    window.dispatchEvent(new MessageEvent("message", {
      data: { type: APP_FRAME_AUTHORIZATION_REQUIRED_MESSAGE },
      origin,
      source: window,
    }));
    await flushPromises();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const currentPath = "/apps/chat/?thread=current#composer";
    const trustedMessage = new MessageEvent("message", {
      data: { path: currentPath, type: APP_FRAME_AUTHORIZATION_REQUIRED_MESSAGE },
      origin,
      source: frame?.contentWindow,
    });
    window.dispatchEvent(trustedMessage);
    window.dispatchEvent(trustedMessage);
    await flushPromises();

    window.dispatchEvent(trustedMessage);
    await flushPromises();
    const recoveredRelayDocument = frame!.srcdoc;
    expect(recoveredRelayDocument).not.toBe(initialRelayDocument);
    await finishBootstrap(frame as HTMLIFrameElement);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({
      app_id: "chat",
      path: currentPath,
    });
    const laterPath = "/apps/chat/?thread=later";
    window.dispatchEvent(new MessageEvent("message", {
      data: { path: laterPath, type: APP_FRAME_AUTHORIZATION_REQUIRED_MESSAGE },
      origin,
      source: frame?.contentWindow,
    }));
    await flushPromises();
    expect(frame!.srcdoc).not.toBe(recoveredRelayDocument);
    await finishBootstrap(frame as HTMLIFrameElement);

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(JSON.parse(String(fetchMock.mock.calls[2]?.[1]?.body))).toEqual({
      app_id: "chat",
      path: laterPath,
    });
    expect(frame?.dataset.maverickFrameOrigin).toBe(laterLaunch.origin);
  });

  it("paints the initial frame with Maverick colors before the remote document loads", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));

    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    roots.push(root);
    await act(async () => {
      root.render(
        <IsolatedMaverickFrame
          appId="chat"
          frameScope={FRAME_SCOPE}
          launchPath="/apps/chat/"
          loadingTheme="dark"
          title="Chat"
        />,
      );
    });

    const frame = container.querySelector("iframe");
    expect(frame?.srcdoc).toContain("#070708");
    expect(frame?.srcdoc).toContain("color-scheme:dark");
    expect(frame?.srcdoc).toContain("maverick.app-frame.bootstrap");
    expect(frame?.srcdoc).toContain('form.target="_self"');
    expect(frame?.src).not.toContain("about:blank");
  });
});

function launchPayload(origin: string, ticket: string): LaunchPayload {
  return {
    bootstrap_url: `${origin}/.well-known/maverick-app-frame-bootstrap`,
    method: "POST",
    origin,
    ticket,
    ticket_field: "ticket",
  };
}

function jsonResponse(payload: LaunchPayload): Response {
  return {
    json: async () => payload,
    ok: true,
  } as Response;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

async function flushPromises() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function finishBootstrap(frame: HTMLIFrameElement) {
  await act(async () => {
    frame.dispatchEvent(new Event("load"));
    await Promise.resolve();
    const bootstrapId = frame.srcdoc.match(/data-maverick-loader="([^"]+)"/)?.[1];
    if (!bootstrapId) throw new Error("Expected a local app-frame bootstrap relay.");
    window.dispatchEvent(new MessageEvent("message", {
      data: {
        bootstrap_id: bootstrapId,
        type: "maverick.app-frame.bootstrap-submitted",
      },
      origin: window.location.origin,
      source: frame.contentWindow,
    }));
    await Promise.resolve();
    frame.dispatchEvent(new Event("load"));
  });
}
