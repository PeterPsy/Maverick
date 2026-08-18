import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const currentDir = dirname(fileURLToPath(import.meta.url));

describe("WidgetSlot compact resize", () => {
  it("allows app-owned footer widgets to request a bounded compact height", () => {
    const source = readFileSync(resolve(currentDir, "WidgetSlot.tsx"), "utf8");

    expect(source).toContain("COMPACT_SLOT_DEFAULT_HEIGHT");
    expect(source).toContain("compactWidgetHeightFromMessage");
    expect(source).toContain("setCompactSlotHeight(nextCompactHeight)");
  });
});

describe("WidgetSlot shell theme bridge", () => {
  it("sends shell theme through both widget context and theme messages", () => {
    const source = readFileSync(resolve(currentDir, "WidgetSlot.tsx"), "utf8");

    expect(source).toContain("postMaverickShellTheme");
    expect(source).toContain("shell_theme: shellTheme");
    expect(source).toContain("urlWithShellThemeSearchParams");
  });
});

describe("WidgetSlot app-scoped runtime remount", () => {
  it("remounts only widgets owned by the changed app", () => {
    const source = readFileSync(resolve(currentDir, "WidgetSlot.tsx"), "utf8");
    expect(source).toContain('"maverick.app.runtime-changed"');
    expect(source).toContain("payload.owner_app_id === widget?.owner_app_id");
  });
});

describe("Sidebar widget frame persistence", () => {
  it("keeps visited app widgets mounted and only hides inactive frames", () => {
    const source = readFileSync(resolve(currentDir, "Sidebar.tsx"), "utf8");
    expect(source).toContain("mountedWidgetAppIds");
    expect(source).toContain("renderedWidgetAppIds.map");
    expect(source).toContain('data-active={appId === activeAppId}');
    expect(source).toContain("preferredOwnerAppId={appId}");
  });

  it("accepts navigation and sidebar commands only from the owning widget frame", () => {
    const source = readFileSync(resolve(currentDir, "WidgetSlot.tsx"), "utf8");
    expect(source).toContain("isActiveWidgetCommand(event, widgetFrameRef.current, isActive)");
  });
});
