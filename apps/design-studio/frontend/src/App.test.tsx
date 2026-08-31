// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { SidecarLaunchError } from "./api";
import type { SidecarLaunch } from "./types";


(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  requestBootstrapStatus: vi.fn(),
  requestLaunch: vi.fn(),
}));
vi.mock("./api", async (importOriginal) => ({
  ...await importOriginal<typeof import("./api")>(),
  requestOpenDesignBootstrapStatus: mocks.requestBootstrapStatus,
  requestOpenDesignLaunch: mocks.requestLaunch,
}));

const LAUNCH: SidecarLaunch = {
  origin: "https://sc-proof.sidecars.example",
  bootstrap_url: "https://sc-proof.sidecars.example/.well-known/maverick-sidecar-bootstrap",
  method: "POST",
  ticket_field: "ticket",
  ticket: "one-shot-ticket",
  confirmation_token: "bootstrap-confirmation-token",
  expires_in_seconds: 30,
  sidecar_instance_id: "instance_12345678",
};

describe("Design Studio native OpenDesign host", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    window.history.replaceState({}, "", "/apps/design-studio?od_project_id=project_1&od_conversation_id=conversation_1");
    mocks.requestLaunch.mockReset().mockResolvedValue(LAUNCH);
    mocks.requestBootstrapStatus.mockReset().mockResolvedValue("ready");
    vi.spyOn(HTMLFormElement.prototype, "submit").mockImplementation(() => undefined);
    vi.spyOn(window, "postMessage").mockImplementation(() => undefined);
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
  });

  it("launches the exact native deep link and has no replacement controls", async () => {
    const frame = await renderThroughBootstrap();

    expect(mocks.requestLaunch).toHaveBeenCalledWith(
      "design-studio",
      "/projects/project_1/conversations/conversation_1",
      window.location.origin,
      expect.any(AbortSignal),
    );
    expect(container.querySelector("iframe")?.title).toBe("OpenDesign");
    expect(container.querySelector("button")).toBeNull();
    expect(container.textContent).not.toContain("Nuovo progetto");

    await act(async () => frame.dispatchEvent(new Event("load")));
    expect(container.querySelector("main")?.dataset.phase).toBe("ready");
  });

  it("does not accept iframe load until Core confirms bootstrap redemption", async () => {
    let confirmBootstrap!: (status: "ready") => void;
    mocks.requestBootstrapStatus.mockReturnValue(new Promise((resolve) => {
      confirmBootstrap = resolve;
    }));
    const frame = await renderThroughBootstrap();

    await act(async () => frame.dispatchEvent(new Event("load")));
    expect(container.querySelector("main")?.dataset.phase).toBe("bootstrapping");

    await act(async () => {
      confirmBootstrap("ready");
      await Promise.resolve();
    });
    expect(container.querySelector("main")?.dataset.phase).toBe("ready");
  });

  it("keeps diagnostics and retry available when Core never confirms bootstrap", async () => {
    mocks.requestBootstrapStatus.mockRejectedValue(
      new SidecarLaunchError("sidecar_bootstrap_confirmation_expired", 410),
    );
    await act(async () => {
      root.render(<App />);
      await Promise.resolve();
      await Promise.resolve();
    });
    const frame = container.querySelector("iframe");
    expect(frame).not.toBeNull();

    await act(async () => frame?.dispatchEvent(new Event("load")));
    expect(container.querySelector("main")?.dataset.phase).toBe("error");
    expect(container.querySelector("[data-testid='opendesign-retry']")).not.toBeNull();
    expect(container.textContent).toContain("Core non ha confermato");
  });

  it("requests a fresh authenticated launch instead of injecting navigation", async () => {
    await renderThroughBootstrap();
    mocks.requestLaunch.mockClear();

    await act(async () => {
      window.dispatchEvent(new MessageEvent("message", {
        origin: window.location.origin,
        source: window.parent,
        data: {
          type: "maverick.app.navigate",
          app_id: "design-studio",
          params: { app_page: "projects/project_2/conversations/conversation_2" },
        },
      }));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mocks.requestLaunch).toHaveBeenCalledWith(
      "design-studio",
      "/projects/project_2/conversations/conversation_2",
      window.location.origin,
      expect.any(AbortSignal),
    );
  });

  async function renderThroughBootstrap(): Promise<HTMLIFrameElement> {
    await act(async () => {
      root.render(<App />);
      await Promise.resolve();
      await Promise.resolve();
    });
    const frame = container.querySelector("iframe");
    expect(frame).not.toBeNull();
    expect(["bootstrapping", "ready"]).toContain(
      container.querySelector("main")?.dataset.phase,
    );
    return frame as HTMLIFrameElement;
  }
});
