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
  it("allows mounted app frames to request browser fullscreen and microphone access", () => {
    const appFrameHost = readSource("src/components/AppFrameHost.tsx");
    const widgetSlot = readSource("src/components/WidgetSlot.tsx");

    expect(appFrameHost).toContain('allow="fullscreen; microphone"');
    expect(appFrameHost).toContain("allowFullScreen");
    expect(widgetSlot).toContain('widget.owner_app_id === "chat" ? "fullscreen; microphone" : "fullscreen"');
    expect(widgetSlot).toContain("allow={widgetAllowPolicy}");
    expect(widgetSlot).toContain("allowFullScreen");
  });
});
