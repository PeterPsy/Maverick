/**
 * @vitest-environment happy-dom
 */
import { describe, expect, it } from "vitest";
import {
  applyShellThemeToDocument,
  createShellThemeState,
  normalizeShellThemeMode,
  resolveShellEffectiveTheme,
  shellThemeSearchParams,
} from "./theme";

describe("shell theme state", () => {
  it("normalizes unknown persisted values back to dark", () => {
    expect(normalizeShellThemeMode("light")).toBe("light");
    expect(normalizeShellThemeMode("system")).toBe("system");
    expect(normalizeShellThemeMode("sepia")).toBe("dark");
  });

  it("resolves system mode to the current effective scheme", () => {
    expect(resolveShellEffectiveTheme("system", "light")).toBe("light");
    expect(resolveShellEffectiveTheme("system", "dark")).toBe("dark");
    expect(resolveShellEffectiveTheme("light", "dark")).toBe("light");
  });

  it("serializes both preference and effective theme for iframe bootstrap", () => {
    expect(shellThemeSearchParams(createShellThemeState("system", "light"))).toEqual({
      loopino_color_scheme: "light",
      loopino_theme: "light",
      loopino_theme_mode: "system",
    });
  });

  it("applies Loopino and generic theme attributes to the root element", () => {
    applyShellThemeToDocument(createShellThemeState("light", "dark"));

    expect(document.documentElement.dataset.loopinoTheme).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.style.colorScheme).toBe("light");
  });
});
