// @vitest-environment happy-dom

import { describe, expect, it } from "vitest";
import { syncAppFrameShellLayout } from "../src/lib/appFrameShellLayout";

describe("app frame shell layout bridge", () => {
  it("exposes the mobile shell top offset inside same-origin app frames", () => {
    const iframe = document.createElement("iframe");
    document.body.append(iframe);

    expect(syncAppFrameShellLayout(iframe, true)).toBe(true);

    const root = iframe.contentDocument?.documentElement;
    expect(root?.getAttribute("data-maverick-shell-mobile-layout")).toBe("true");
    expect(root?.style.getPropertyValue("--maverick-shell-mobile-status-bar-height")).toBe("env(safe-area-inset-top, 0px)");
    expect(root?.style.getPropertyValue("--maverick-shell-mobile-header-height")).toBe("2.75rem");
    expect(root?.style.getPropertyValue("--maverick-shell-mobile-content-top-offset")).toBe(
      "calc(env(safe-area-inset-top, 0px) + 2.75rem)",
    );

    expect(syncAppFrameShellLayout(iframe, false)).toBe(true);
    expect(root?.hasAttribute("data-maverick-shell-mobile-layout")).toBe(false);
    expect(root?.style.getPropertyValue("--maverick-shell-mobile-content-top-offset")).toBe("");

    iframe.remove();
  });
});
