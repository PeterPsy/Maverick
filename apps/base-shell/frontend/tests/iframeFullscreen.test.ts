import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const currentDir = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(currentDir, "..");

function readSource(path: string) {
  return readFileSync(resolve(frontendRoot, path), "utf8");
}

describe("base shell iframe browser feature policy", () => {
  it("applies the app-owned browser feature policy to mounted app and widget frames", () => {
    const appFrameHost = readSource("src/components/AppFrameHost.tsx");
    const widgetSlot = readSource("src/components/WidgetSlot.tsx");

    expect(appFrameHost).toContain("allow={appFrameBrowserFeaturePolicy(app.public_app_id || app.app_id)}");
    expect(appFrameHost).toContain("allowFullScreen");
    expect(widgetSlot).toContain("widgetFrameBrowserFeaturePolicy(widget.owner_app_id)");
    expect(widgetSlot).toContain("allow={widgetAllowPolicy}");
    expect(widgetSlot).toContain("allowFullScreen");
  });
});
