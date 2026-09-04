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

    expect(source).toContain("useLayoutEffect");
    expect(source).toMatch(/useLayoutEffect\(\(\) => \{[\s\S]*?new StorageFileCacheBroker[\s\S]*?broker\.dispose\(\)/u);
    expect(source).toContain("new StorageFileCacheBroker");
    expect(source).toContain("fileCacheBrokerRef.current?.handleWindowMessage");
    expect(source).toContain("frameRefs.current.storage ?? null");
    expect(source).toContain("isMaverickFrameMessage");
    expect(source).toContain("broker.dispose()");
  });
});

describe("AppFrameHost structured data-cache boundary", () => {
  it("routes all owner-registered app and widget frames through one disposable shell broker", () => {
    const source = readFileSync(resolve(currentDir, "../usePwaDataCacheBrokerHost.ts"), "utf8");

    expect(source).toContain("new PwaDataCacheBroker");
    expect(source).toContain("app.data_cache_enabled");
    expect(source).toContain("broker.handleWindowMessage(event, enabledAppIdsRef.current)");
    expect(source).toContain("broker.handleDataChangedMessage(event)");
    expect(source).toContain("broker.dispose()");
  });

  it("clears authenticated shell UI through the shared authorization channel", () => {
    const source = readFileSync(resolve(currentDir, "../AppShell.tsx"), "utf8");

    expect(source).toContain("usePwaDataCacheBrokerHost");
    expect(source).toContain("subscribeShellAuthorizationRevocation(handleShellAuthorizationFailure)");
    expect(source).toContain("beginShellSessionTransition");
    expect(source).toContain("publishAnonymousShellState");
    expect(source).toContain("setSession(anonymousSession)");
  });

  it("uses the owner-verified broker as the only structured-cache invalidation path", () => {
    const source = readFileSync(resolve(currentDir, "../AppShell.tsx"), "utf8");

    expect(source).toContain("isMaverickOwnerMessage(event, payload.owner_app_id, frameScope)");
    expect(source).not.toContain("shellCacheLifecycle.handleDataChanged(");
  });
});
