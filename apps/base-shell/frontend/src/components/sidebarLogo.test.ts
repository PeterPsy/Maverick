import { describe, expect, it } from "vitest";
import { createShellThemeState } from "../theme";
import { SIDEBAR_LOGO_DARK_SRC, SIDEBAR_LOGO_LIGHT_SRC, sidebarLogoSrc } from "./sidebarLogo";

describe("sidebar logo asset selection", () => {
  it("uses the dark logo for dark effective theme", () => {
    expect(sidebarLogoSrc(createShellThemeState("dark"))).toBe(SIDEBAR_LOGO_DARK_SRC);
  });

  it("uses the black logo for light effective theme", () => {
    expect(sidebarLogoSrc(createShellThemeState("light"))).toBe(SIDEBAR_LOGO_LIGHT_SRC);
  });
});
