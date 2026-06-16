import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const currentDir = dirname(fileURLToPath(import.meta.url));

describe("AppFrameHost shell theme bridge", () => {
  it("bootstraps iframe URLs and sends live shell theme messages", () => {
    const source = readFileSync(resolve(currentDir, "AppFrameHost.tsx"), "utf8");

    expect(source).toContain("urlWithShellThemeSearchParams");
    expect(source).toContain("postMaverickShellTheme");
    expect(source).toContain('theme: shellTheme');
  });
});
