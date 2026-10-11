// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { useMountedAppIds } from "../src/hooks/useMountedAppIds";
import { setMaverickFrameOrigin, type MaverickFrameScope } from "../src/iframePolicy";

const scope = { sessionGeneration: "loaded-apps-session", workspaceId: "default" };
const origin = "https://af-loaded-apps.sidecars.maverick.test";

function MountedApps({ frameScope }: { frameScope: MaverickFrameScope | null }) {
  return <output>{useMountedAppIds(frameScope).join(",")}</output>;
}

describe("loaded app indicators", () => {
  let container: HTMLDivElement;
  let root: Root;
  let frames: HTMLIFrameElement[];

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    frames = [];
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    act(() => root.render(<MountedApps frameScope={scope} />));
  });

  afterEach(() => {
    act(() => root.unmount());
    for (const frame of frames) {
      setMaverickFrameOrigin(frame, null, "unused", scope);
      frame.remove();
    }
    container.remove();
  });

  function mountFrame(owner: string, frameScope = scope) {
    const frame = document.createElement("iframe");
    frames.push(frame);
    document.body.append(frame);
    act(() => setMaverickFrameOrigin(frame, origin, owner, frameScope));
    return frame;
  }

  function unmountFrame(frame: HTMLIFrameElement) {
    act(() => {
      setMaverickFrameOrigin(frame, null, "unused", scope);
      frame.remove();
    });
  }

  it("keeps an app loaded while its widget remains after its main view hibernates", () => {
    const main = mountFrame("chat");
    const widget = mountFrame("chat");
    mountFrame("storage");
    expect(container.textContent).toBe("chat,storage");
    unmountFrame(main);
    expect(container.textContent).toBe("chat,storage");
    unmountFrame(widget);
    expect(container.textContent).toBe("storage");
  });

  it("counts widget-only apps and updates immediately on mount and removal", () => {
    const widget = mountFrame("agents");
    expect(container.textContent).toBe("agents");
    unmountFrame(widget);
    expect(container.textContent).toBe("");
  });

  it("clears old workspace/session indicators and ignores unregistered frames", () => {
    mountFrame("chat");
    const next = { sessionGeneration: "next-session", workspaceId: "other" };
    mountFrame("storage", next);
    const foreign = document.createElement("iframe");
    frames.push(foreign);
    document.body.append(foreign);
    expect(container.textContent).toBe("chat");
    act(() => root.render(<MountedApps frameScope={next} />));
    expect(container.textContent).toBe("storage");
    act(() => root.render(<MountedApps frameScope={null} />));
    expect(container.textContent).toBe("");
  });
});
