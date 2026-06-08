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
