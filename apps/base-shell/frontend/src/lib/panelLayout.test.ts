import { describe, expect, it } from "vitest";
import { resolvePanelLayout } from "./panelLayout";

describe("shared panel budget", () => {
  it.each([979, 1024, 1100, 1280, 1440, 1920])("protects workspace width at %i px with both panels requested", (viewportWidth) => {
    const result = resolvePanelLayout({ viewportWidth, rootFontSize: 16, railWidthRem: 3.35, sidebarFixed: true, chatFixed: true, sidebarWidth: 560, chatWidth: 720 });
    const used = (3.35 + 2.14) * 16 + (result.fixedSidebar ? result.sidebarWidth : 0) + (result.fixedChat ? result.chatWidth + 24 : 0);
    expect(viewportWidth - used).toBeGreaterThanOrEqual(560);
    if (result.fixedSidebar) expect(result.sidebarWidth).toBeGreaterThanOrEqual(288);
    if (result.fixedChat) expect(result.chatWidth).toBeGreaterThanOrEqual(360);
  });
  it("restores preferred widths when the viewport grows", () => {
    const preferences = { rootFontSize: 16, railWidthRem: 3.35, sidebarFixed: true, chatFixed: true, sidebarWidth: 320, chatWidth: 420 };
    expect(resolvePanelLayout({ ...preferences, viewportWidth: 1024 })).toMatchObject({ fixedSidebar: true, fixedChat: false });
    expect(resolvePanelLayout({ ...preferences, viewportWidth: 1440 })).toMatchObject({ fixedSidebar: true, fixedChat: true, sidebarWidth: 320, chatWidth: 420 });
  });
});
