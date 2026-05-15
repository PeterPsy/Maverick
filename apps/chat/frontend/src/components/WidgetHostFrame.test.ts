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
});
