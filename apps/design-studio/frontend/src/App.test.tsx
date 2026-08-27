// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { writeCachedLaunchTarget } from "./api";
import type { SidecarLaunch } from "./types";


(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  requestLaunch: vi.fn(),
  callBackend: vi.fn(),
  startPoll: vi.fn(() => vi.fn()),
}));

vi.mock("./api", async (importOriginal) => ({
  ...await importOriginal<typeof import("./api")>(),
  requestOpenDesignLaunch: mocks.requestLaunch,
}));

vi.mock("./backendApi", async (importOriginal) => ({
  ...await importOriginal<typeof import("./backendApi")>(),
  callDesignStudioBackend: mocks.callBackend,
}));

vi.mock("./startupStatusPolling", () => ({
  startNonOverlappingPoll: mocks.startPoll,
}));

const LAUNCH: SidecarLaunch = {
  origin: "https://sc-proof.sidecars.example",
  bootstrap_url: "https://sc-proof.sidecars.example/.well-known/maverick-sidecar-bootstrap",
  method: "POST",
  ticket_field: "ticket",
  ticket: "one-shot-ticket",
  expires_in_seconds: 30,
  sidecar_instance_id: "instance_12345678",
};

describe("Design Studio usable frame readiness", () => {
  let container: HTMLDivElement;
  let root: Root;
  let parentPostMessage: ReturnType<typeof vi.spyOn>;
  let consoleInfo: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    window.history.replaceState({}, "", "/apps/design-studio?od_project_id=od_project_1");
    sessionStorage.clear();
    mocks.requestLaunch.mockReset().mockResolvedValue(LAUNCH);
    mocks.callBackend.mockReset().mockResolvedValue({
      target: "empty",
      od_project_id: "",
      project: null,
    });
    mocks.startPoll.mockClear();
    vi.spyOn(HTMLFormElement.prototype, "submit").mockImplementation(() => undefined);
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      queueMicrotask(() => callback(0));
      return 1;
    });
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);
    parentPostMessage = vi.spyOn(window, "postMessage").mockImplementation(() => undefined);
    consoleInfo = vi.spyOn(console, "info").mockImplementation(() => undefined);
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("keeps 401/410/503-style iframe load events in bootstrapping", async () => {
    const frame = await renderThroughBootstrap();
    const sidecarPostMessage = vi.mocked(frame.contentWindow!.postMessage);

    // Cross-origin iframe load events do not expose their HTTP status; these
    // are intentionally identical to loads of 401, 410, and 503 documents.
    for (const _status of [401, 410, 503]) {
      await act(async () => {
        frame.dispatchEvent(new Event("load"));
      });
      expect(hostPhase()).toBe("bootstrapping");
    }

    expect(firstPaintEvents()).toHaveLength(0);
    expect(container.querySelector(".design-studio-toolbar")).toBeNull();
    expect(container.querySelector(".design-studio-empty")).toBeNull();
    expect(sidecarPostMessage).toHaveBeenCalledWith({
      type: "maverick.opendesign.navigate",
      version: 1,
      od_project_id: "od_project_1",
    }, LAUNCH.origin);
  });

  it("becomes ready only for the exact usable project surface and records it once", async () => {
    vi.useFakeTimers();
    vi.spyOn(performance, "now").mockReturnValueOnce(1).mockReturnValue(12);
    const frame = await renderThroughBootstrap();
    const frameWindow = frame.contentWindow;
    expect(frameWindow).not.toBeNull();

    await dispatchUsable(frameWindow, "https://untrusted.example", {
      surface: "project",
      od_project_id: "od_project_1",
    });
    await dispatchUsable(window, LAUNCH.origin, {
      surface: "project",
      od_project_id: "od_project_1",
    });
    await dispatchUsable(frameWindow, LAUNCH.origin, {
      surface: "project",
      od_project_id: "wrong_project",
    });
    await dispatchLegacyReady(frameWindow, LAUNCH.origin);
    expect(hostPhase(), container.innerHTML).toBe("bootstrapping");
    expect(firstPaintEvents()).toHaveLength(0);

    await dispatchUsable(frameWindow, LAUNCH.origin, {
      surface: "project",
      od_project_id: "od_project_1",
    });
    expect(hostPhase()).toBe("ready");
    expect(container.querySelector(".design-studio-toolbar")).not.toBeNull();
    expect(firstPaintEvents()).toHaveLength(1);
    expect(firstPaintEvents()[0]?.[1]).toMatchObject({
      metric: "first_paint_ms",
      source: "maverick.opendesign.usable",
    });

    await dispatchUsable(frameWindow, LAUNCH.origin, {
      surface: "project",
      od_project_id: "od_project_1",
    });
    expect(firstPaintEvents()).toHaveLength(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_500);
    });
    expect(mocks.startPoll).not.toHaveBeenCalled();
  });

  it("requires the empty usable surface when no project was requested", async () => {
    window.history.replaceState({}, "", "/apps/design-studio");
    writeCachedLaunchTarget(sessionStorage, "design-studio", LAUNCH.origin, {
      target: "empty",
      od_project_id: "",
      project: null,
    });
    const frame = await renderThroughBootstrap();
    const frameWindow = frame.contentWindow;
    expect(frameWindow).not.toBeNull();

    await dispatchUsable(frameWindow, LAUNCH.origin, {
      surface: "project",
      od_project_id: "od_project_1",
    });
    expect(hostPhase()).toBe("bootstrapping");

    await dispatchUsable(frameWindow, LAUNCH.origin, { surface: "empty" });
    expect(hostPhase()).toBe("ready");
    expect(container.querySelector(".design-studio-empty button")).not.toBeNull();
  });

  it("binds the one-shot ticket after canonical shell navigation arrives", async () => {
    window.history.replaceState({}, "", "/apps/design-studio");
    let releaseHandshake: FrameRequestCallback | null = null;
    vi.mocked(window.requestAnimationFrame).mockImplementationOnce((callback) => {
      releaseHandshake = callback;
      return 2;
    });

    await act(async () => {
      root.render(<App />);
    });
    expect(releaseHandshake).not.toBeNull();
    await act(async () => {
      window.dispatchEvent(new MessageEvent("message", {
        data: {
          type: "maverick.app.navigate",
          app_id: "design-studio",
          params: { od_project_id: "od_shell_project" },
        },
        origin: window.location.origin,
        source: window.parent,
      }));
      releaseHandshake?.(0);
      await Promise.resolve();
    });

    expect(mocks.requestLaunch).toHaveBeenCalledWith(
      "design-studio",
      { od_project_id: "od_shell_project", od_run_id: "" },
      window.location.origin,
      expect.any(AbortSignal),
    );
  });

  async function renderThroughBootstrap(): Promise<HTMLIFrameElement> {
    await act(async () => {
      root.render(<App />);
    });
    for (let index = 0; index < 4; index += 1) {
      await act(async () => {
        await Promise.resolve();
      });
    }
    const frame = container.querySelector("iframe");
    expect(frame).not.toBeNull();
    if (frame?.contentWindow) {
      vi.spyOn(frame.contentWindow, "postMessage").mockImplementation(() => undefined);
    }
    expect(hostPhase(), container.innerHTML).toBe("bootstrapping");
    return frame as HTMLIFrameElement;
  }

  async function dispatchUsable(
    source: MessageEventSource | null,
    origin: string,
    surface: { surface: "empty" | "project"; od_project_id?: string },
  ): Promise<void> {
    await act(async () => {
      window.dispatchEvent(new MessageEvent("message", {
        data: { type: "maverick.opendesign.usable", version: 1, ...surface },
        origin,
        source,
      }));
    });
  }

  async function dispatchLegacyReady(
    source: MessageEventSource | null,
    origin: string,
  ): Promise<void> {
    await act(async () => {
      window.dispatchEvent(new MessageEvent("message", {
        data: { type: "maverick.opendesign.ready", version: 1 },
        origin,
        source,
      }));
    });
  }

  function hostPhase(): string | undefined {
    return container.querySelector("main")?.dataset.phase;
  }

  function firstPaintEvents(): unknown[][] {
    return consoleInfo.mock.calls.filter(
      (call: unknown[]) => call[0] === "maverick.opendesign.first-paint",
    );
  }
});
