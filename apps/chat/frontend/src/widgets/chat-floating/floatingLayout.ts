const EXPANDED_HEIGHT = "min(38rem, calc(100dvh - 2rem))";
const EXPANDED_WIDTH_REM = 25;
const COLLAPSED_WIDTH_REM = 3;
const WINDOW_GAP_REM = 0.75;
const SINGLE_EXPANDED_FRAME_INSET_REM = 2;

export type FloatingWindowLayoutItem = {
  isCollapsed: boolean;
};

export function floatingWidgetSize(windows: FloatingWindowLayoutItem[]) {
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
  const width = `min(calc(${widthRem}rem), calc(100vw - 2rem))`;
  return {
    height: expandedCount > 0 ? EXPANDED_HEIGHT : "3rem",
    width,
  };
}
