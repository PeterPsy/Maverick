import { describe, expect, it } from "vitest";
import { floatingWidgetSize, type FloatingWidgetSizing } from "./floatingLayout";

const sizing: FloatingWidgetSizing = {
  rootFontSizePx: 16,
};

describe("floating chat widget layout", () => {
  it("keeps a single expanded chat at the same visible width as stacked expanded chats", () => {
    expect(floatingWidgetSize([{ isCollapsed: false }], sizing).width).toBe("432px");
    expect(floatingWidgetSize([{ isCollapsed: false }, { isCollapsed: false }], sizing).width).toBe("812px");
  });

  it("uses the compact launcher size when all windows are collapsed", () => {
    expect(floatingWidgetSize([{ isCollapsed: true }], sizing)).toEqual({
      height: "48px",
      width: "48px",
    });
  });

  it("keeps expanded height in px without reading the current iframe viewport", () => {
    expect(floatingWidgetSize([{ isCollapsed: false }], sizing).height).toBe("608px");
  });
});
