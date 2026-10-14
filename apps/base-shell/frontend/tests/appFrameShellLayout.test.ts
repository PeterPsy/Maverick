// @vitest-environment happy-dom

import { describe, expect, it, vi } from "vitest";
import { syncAppFrameShellLayout } from "../src/lib/appFrameShellLayout";
import { setLoopinoFrameOrigin } from "../src/iframePolicy";

const FRAME_SCOPE = Object.freeze({ sessionGeneration: "session-one", workspaceId: "default" });

describe("app frame shell layout bridge", () => {
  it("sends mobile shell layout only to the registered isolated frame origin", () => {
    const iframe = document.createElement("iframe");
    document.body.append(iframe);
    const postMessage = vi.spyOn(iframe.contentWindow!, "postMessage");

    expect(syncAppFrameShellLayout(iframe, true)).toBe(false);
    expect(postMessage).not.toHaveBeenCalled();

    setLoopinoFrameOrigin(iframe, "https://af-layout.sidecars.loopino.test", "chat", FRAME_SCOPE);
    expect(syncAppFrameShellLayout(iframe, true)).toBe(true);
    expect(postMessage).toHaveBeenLastCalledWith(
      { mobile: true, type: "loopino.shell.layout-changed" },
      "https://af-layout.sidecars.loopino.test",
    );

    expect(syncAppFrameShellLayout(iframe, false)).toBe(true);
    expect(postMessage).toHaveBeenLastCalledWith(
      { mobile: false, type: "loopino.shell.layout-changed" },
      "https://af-layout.sidecars.loopino.test",
    );

    setLoopinoFrameOrigin(iframe, null, "chat", FRAME_SCOPE);
    iframe.remove();
  });
});
