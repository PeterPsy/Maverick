import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const currentDir = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(currentDir, "..");

function readSource(path: string) {
  return readFileSync(resolve(frontendRoot, path), "utf8");
}

describe("base shell iframe fullscreen policy", () => {
  it("allows mounted app and widget frames to request browser fullscreen", () => {
    const appFrameHost = readSource("src/components/AppFrameHost.tsx");
    const widgetSlot = readSource("src/components/WidgetSlot.tsx");

    expect(appFrameHost).toContain('allow="fullscreen"');
    expect(appFrameHost).toContain("allowFullScreen");
    expect(widgetSlot).toContain('allow="fullscreen"');
    expect(widgetSlot).toContain("allowFullScreen");
  });
});
