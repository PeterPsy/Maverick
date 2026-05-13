const EXPANDED_WIDTH_REM = 25;
const COLLAPSED_WIDTH_REM = 3;
const WINDOW_GAP_REM = 0.75;
const SINGLE_EXPANDED_FRAME_INSET_REM = 2;
const EXPANDED_MAX_HEIGHT_REM = 38;
const DEFAULT_ROOT_FONT_SIZE_PX = 16;

export type FloatingWindowLayoutItem = {
  isCollapsed: boolean;
};

export type FloatingWidgetSizing = {
  rootFontSizePx: number;
};

export function floatingWidgetSize(windows: FloatingWindowLayoutItem[], sizing = currentFloatingWidgetSizing()) {
  const rootFontSizePx = finitePositiveNumber(sizing.rootFontSizePx, DEFAULT_ROOT_FONT_SIZE_PX);

  if (windows.length === 0) {
    return {
      height: "0px",
      width: "0px",
    };
  }
  const expandedCount = windows.filter((windowItem) => !windowItem.isCollapsed).length;
  const collapsedCount = windows.length - expandedCount;
  const gapCount = Math.max(0, windows.length - 1);
  // The shell reserves 2rem inside its iframe. A lone expanded chat needs that frame
  // space included, otherwise it renders narrower than the same chat in a stack.
  const singleExpandedFrameInset = expandedCount === 1 && collapsedCount === 0 ? SINGLE_EXPANDED_FRAME_INSET_REM : 0;
  const widthRem =
    expandedCount * EXPANDED_WIDTH_REM +
    collapsedCount * COLLAPSED_WIDTH_REM +
    gapCount * WINDOW_GAP_REM +
    singleExpandedFrameInset;
  const width = px(widthRem * rootFontSizePx);
  const height = px(expandedCount > 0 ? EXPANDED_MAX_HEIGHT_REM * rootFontSizePx : COLLAPSED_WIDTH_REM * rootFontSizePx);
  return {
    height,
    width,
  };
}

function currentFloatingWidgetSizing(): FloatingWidgetSizing {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return {
      rootFontSizePx: DEFAULT_ROOT_FONT_SIZE_PX,
    };
  }
  const rootFontSizePx = Number.parseFloat(window.getComputedStyle(document.documentElement).fontSize);
  return {
    rootFontSizePx: finitePositiveNumber(rootFontSizePx, DEFAULT_ROOT_FONT_SIZE_PX),
  };
}

function finitePositiveNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : fallback;
}

function px(value: number): string {
  return `${Math.max(0, Math.ceil(value))}px`;
}
