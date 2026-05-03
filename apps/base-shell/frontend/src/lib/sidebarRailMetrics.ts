import type { CSSProperties } from "react";

const PREFERRED_ICON_SIZE_REM = 3;
const MIN_ICON_SIZE_REM = 2.05;
const RAIL_WIDTH_EXTRA_REM = 0.95;
const RAIL_MAX_HEIGHT_REM = 38;
const RAIL_VIEWPORT_MARGIN_REM = 2;
const RAIL_ITEM_GAP_REM = 0.32;
const RAIL_INTERACTIVE_PADDING_REM = 0.42 * 2;

export type SidebarRailMetricsInput = {
  itemCount: number;
  rootFontSizePx?: number | null;
  viewportHeightPx?: number | null;
};

export function calculateSidebarRailMetrics({
  itemCount,
  rootFontSizePx,
  viewportHeightPx,
}: SidebarRailMetricsInput): CSSProperties {
  const normalizedItemCount = Math.max(1, Math.floor(itemCount));
  const viewportHeightRem = viewportHeightPx && rootFontSizePx ? viewportHeightPx / rootFontSizePx : null;
  const iconSize = viewportHeightRem
    ? fitIconSizeToViewport(normalizedItemCount, viewportHeightRem)
    : PREFERRED_ICON_SIZE_REM;
  const railWidth = iconSize + RAIL_WIDTH_EXTRA_REM;
  const overflowY = requiresOverflowAtMinimum(normalizedItemCount, viewportHeightRem) ? "auto" : "visible";

  return {
    "--bs-sidebar-icon-size": formatRem(iconSize),
    "--bs-sidebar-rail-width": formatRem(railWidth),
    "--bs-sidebar-rail-apps-overflow-y": overflowY,
  } as CSSProperties;
}

function fitIconSizeToViewport(itemCount: number, viewportHeightRem: number): number {
  const availableRailHeight = Math.max(0, Math.min(RAIL_MAX_HEIGHT_REM, viewportHeightRem - RAIL_VIEWPORT_MARGIN_REM));
  const gapHeight = Math.max(0, itemCount - 1) * RAIL_ITEM_GAP_REM;
  const fitSize = (availableRailHeight - RAIL_INTERACTIVE_PADDING_REM - gapHeight) / itemCount;

  return Math.max(MIN_ICON_SIZE_REM, Math.min(PREFERRED_ICON_SIZE_REM, fitSize));
}

function requiresOverflowAtMinimum(itemCount: number, viewportHeightRem: number | null): boolean {
  if (!viewportHeightRem) {
    return false;
  }
  const availableRailHeight = Math.max(0, Math.min(RAIL_MAX_HEIGHT_REM, viewportHeightRem - RAIL_VIEWPORT_MARGIN_REM));
  const minimumContentHeight =
    itemCount * MIN_ICON_SIZE_REM + Math.max(0, itemCount - 1) * RAIL_ITEM_GAP_REM + RAIL_INTERACTIVE_PADDING_REM;

  return minimumContentHeight > availableRailHeight;
}

function formatRem(value: number): string {
  return `${Math.round(value * 1000) / 1000}rem`;
}
