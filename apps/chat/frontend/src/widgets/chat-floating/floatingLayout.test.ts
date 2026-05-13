import { describe, expect, it } from "vitest";
import {
  floatingWidgetSize,
  horizontalDragScrollLeft,
  isHorizontalDragIntent,
  isVerticalDragIntent,
  type FloatingWidgetSizing,
} from "./floatingLayout";

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

  it("detects horizontal stack drags without stealing vertical transcript scrolls", () => {
    expect(isHorizontalDragIntent(18, 4)).toBe(true);
    expect(isHorizontalDragIntent(4, 18)).toBe(false);
    expect(isHorizontalDragIntent(4, 1)).toBe(false);
    expect(isVerticalDragIntent(4, 18)).toBe(true);
    expect(isVerticalDragIntent(18, 4)).toBe(false);
  });

  it("moves the scroll position with the pointer drag direction", () => {
    expect(horizontalDragScrollLeft(0, 120, 160)).toBe(-40);
    expect(horizontalDragScrollLeft(24, 160, 120)).toBe(64);
  });
});
