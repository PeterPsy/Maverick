import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const currentDir = dirname(fileURLToPath(import.meta.url));

describe("WidgetHostFrame", () => {
  it("disables native iframe scrolling so widgets own their scroll surfaces", () => {
    const source = readFileSync(resolve(currentDir, "WidgetHostFrame.tsx"), "utf8");

    expect(source).toContain('scrolling="no"');
  });

  it("allows widget previews to request browser fullscreen", () => {
    const source = readFileSync(resolve(currentDir, "WidgetHostFrame.tsx"), "utf8");

    expect(source).toContain('allow="fullscreen"');
    expect(source).toContain("allowFullScreen");
  });

  it("forwards nested widget open-app messages to the shell app host", () => {
    const source = readFileSync(resolve(currentDir, "WidgetHostFrame.tsx"), "utf8");

    expect(source).toContain('"maverick.widget.open-app"');
    expect(source).toContain("openAppParamsInShell(payload.app_id");
    expect(source).toContain("event.source !== frameRef.current?.contentWindow");
  });
});
