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

describe("AppFrameHost app-scoped runtime remount", () => {
  it("remounts only the owner app after a sidecar runtime change", () => {
    const source = readFileSync(resolve(currentDir, "AppFrameHost.tsx"), "utf8");
    expect(source).toContain('"maverick.app.runtime-changed"');
    expect(source).toContain("[eventMountKey]");
    expect(source).toContain("event.owner_app_id");
  });
});

describe("AppFrameHost Storage file-cache boundary", () => {
  it("routes Storage messages through a disposable parent-owned broker", () => {
    const source = readFileSync(resolve(currentDir, "AppFrameHost.tsx"), "utf8");

    expect(source).toContain("new StorageFileCacheBroker");
    expect(source).toContain("fileCacheBrokerRef.current?.handleWindowMessage");
    expect(source).toContain("frameRefs.current.storage?.contentWindow");
    expect(source).toContain("broker.dispose()");
  });
});
