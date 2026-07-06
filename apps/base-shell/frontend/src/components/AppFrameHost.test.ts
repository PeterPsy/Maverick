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

  it("accepts mounted app workspace focus requests", () => {
    const frameHostSource = readFileSync(resolve(currentDir, "AppFrameHost.tsx"), "utf8");
    const appShellSource = readFileSync(resolve(currentDir, "../AppShell.tsx"), "utf8");
    const layoutSource = readFileSync(resolve(currentDir, "../styles/layout.css"), "utf8");

    expect(frameHostSource).toContain("maverick.shell.workspace-focus");
    expect(frameHostSource).toContain("onWorkspaceFocusChange");
    expect(appShellSource).toContain("is-workspace-focus");
    expect(layoutSource).toContain(".bs-shell.is-workspace-focus:not(.is-mobile-layout) .bs-workspace-view-shell");
    expect(layoutSource).toContain("margin-left: 0");
  });
});
