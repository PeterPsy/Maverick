/**
 * @vitest-environment happy-dom
 */
import { describe, expect, it } from "vitest";
import { applyLoopinoTheme, normalizeLoopinoTheme, themeFromMessage } from "./shellTheme";

describe("chat shell theme bridge", () => {
  it("accepts shell theme change messages", () => {
    expect(themeFromMessage({
      type: "loopino.shell.theme-changed",
      theme: { color_scheme: "light", effective: "light", mode: "system" },
    })).toEqual({
      color_scheme: "light",
      effective: "light",
      mode: "system",
    });
  });

  it("accepts navigation theme payloads", () => {
    expect(themeFromMessage({
      type: "loopino.app.navigate",
      theme: { color_scheme: "light", effective: "light", mode: "light" },
    })).toEqual({
      color_scheme: "light",
      effective: "light",
      mode: "light",
    });
  });

  it("accepts widget context theme payloads", () => {
    expect(themeFromMessage({
      type: "loopino.widget.context-changed",
      context: { content: { shell_theme: { color_scheme: "light", effective: "light", mode: "light" } } },
    })).toEqual({
      color_scheme: "light",
      effective: "light",
      mode: "light",
    });
  });

  it("ignores theme payloads on unrelated same-origin messages", () => {
    expect(themeFromMessage({
      type: "loopino.chat.active-thread-changed",
      theme: { color_scheme: "light", effective: "light", mode: "light" },
    })).toBeNull();
    expect(themeFromMessage({
      type: "loopino.app.data-changed",
      context: { content: { shell_theme: { color_scheme: "light", effective: "light", mode: "light" } } },
    })).toBeNull();
  });

  it("ignores unsupported theme values", () => {
    expect(normalizeLoopinoTheme({ effective: "sepia", mode: "light" })).toBeNull();
  });

  it("applies both Loopino and generic data attributes", () => {
    applyLoopinoTheme({ color_scheme: "light", effective: "light", mode: "light" });

    expect(document.documentElement.dataset.loopinoTheme).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.style.colorScheme).toBe("light");
  });
});
