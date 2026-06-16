/**
 * @vitest-environment happy-dom
 */
import { describe, expect, it } from "vitest";
import { applyMaverickTheme, normalizeMaverickTheme, themeFromMessage } from "./shellTheme";

describe("chat shell theme bridge", () => {
  it("accepts shell theme change messages", () => {
    expect(themeFromMessage({
      type: "maverick.shell.theme-changed",
      theme: { color_scheme: "light", effective: "light", mode: "system" },
    })).toEqual({
      color_scheme: "light",
      effective: "light",
      mode: "system",
    });
  });

  it("accepts widget context theme payloads", () => {
    expect(themeFromMessage({
      type: "maverick.widget.context-changed",
      context: { content: { shell_theme: { color_scheme: "light", effective: "light", mode: "light" } } },
    })).toEqual({
      color_scheme: "light",
      effective: "light",
      mode: "light",
    });
  });

  it("ignores unsupported theme values", () => {
    expect(normalizeMaverickTheme({ effective: "sepia", mode: "light" })).toBeNull();
  });

  it("applies both Maverick and generic data attributes", () => {
    applyMaverickTheme({ color_scheme: "light", effective: "light", mode: "light" });

    expect(document.documentElement.dataset.maverickTheme).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.style.colorScheme).toBe("light");
  });
});
