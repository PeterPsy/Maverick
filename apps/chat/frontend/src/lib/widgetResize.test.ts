import { describe, expect, it } from "vitest";
import { boundedWidgetHeightPx, STRUCTURED_WIDGET_MAX_HEIGHT_PX, STRUCTURED_WIDGET_MIN_HEIGHT_PX } from "./widgetResize";

describe("boundedWidgetHeightPx", () => {
  it("accepts px heights and rounds up fractional values", () => {
    expect(boundedWidgetHeightPx("241.2px")).toBe(242);
  });

  it("clamps very small and very large heights", () => {
    expect(STRUCTURED_WIDGET_MAX_HEIGHT_PX).toBe(1040);
    expect(boundedWidgetHeightPx("12px")).toBe(STRUCTURED_WIDGET_MIN_HEIGHT_PX);
    expect(boundedWidgetHeightPx("99999px")).toBe(STRUCTURED_WIDGET_MAX_HEIGHT_PX);
  });

  it("rejects non-pixel or non-string values", () => {
    expect(boundedWidgetHeightPx("80vh")).toBeNull();
    expect(boundedWidgetHeightPx("calc(100vh + 1px)")).toBeNull();
    expect(boundedWidgetHeightPx(320)).toBeNull();
  });
});
