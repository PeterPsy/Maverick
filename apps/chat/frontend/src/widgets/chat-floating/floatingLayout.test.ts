import { describe, expect, it } from "vitest";
import { floatingWidgetSize } from "./floatingLayout";

describe("floating chat widget layout", () => {
  it("keeps a single expanded chat at the same visible width as stacked expanded chats", () => {
    expect(floatingWidgetSize([{ isCollapsed: false }]).width).toBe("min(calc(27rem), calc(100vw - 2rem))");
    expect(floatingWidgetSize([{ isCollapsed: false }, { isCollapsed: false }]).width).toBe(
      "min(calc(50.75rem), calc(100vw - 2rem))",
    );
  });

  it("uses the compact launcher size when all windows are collapsed", () => {
    expect(floatingWidgetSize([{ isCollapsed: true }])).toEqual({
      height: "3rem",
      width: "min(calc(3rem), calc(100vw - 2rem))",
    });
  });
});
