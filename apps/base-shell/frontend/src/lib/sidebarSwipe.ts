export type SidebarSwipePoint = {
  x: number;
  y: number;
};

export type SidebarSwipeViewport = {
  width: number;
  height: number;
};

const OPEN_EDGE_MIN_PX = 28;
const OPEN_EDGE_MAX_PX = 64;
const OPEN_EDGE_WIDTH_RATIO = 0.16;
const MIN_HORIZONTAL_DISTANCE = 72;
const MAX_VERTICAL_DRIFT = 48;
const HORIZONTAL_INTENT_MIN_DISTANCE = 12;

export function sidebarOpenSwipeEdgeWidth(viewport: SidebarSwipeViewport): number {
  if (viewport.width <= 0) {
    return 0;
  }
  return Math.min(OPEN_EDGE_MAX_PX, Math.max(OPEN_EDGE_MIN_PX, viewport.width * OPEN_EDGE_WIDTH_RATIO));
}

export function startsInSidebarOpenSwipeZone(point: SidebarSwipePoint, viewport: SidebarSwipeViewport): boolean {
  if (viewport.width <= 0 || viewport.height <= 0) {
    return false;
  }
  return point.x >= 0 && point.x <= sidebarOpenSwipeEdgeWidth(viewport) && point.y >= 0 && point.y <= viewport.height;
}

export function isSidebarOpenSwipe(start: SidebarSwipePoint, end: SidebarSwipePoint, viewport: SidebarSwipeViewport): boolean {
  if (!startsInSidebarOpenSwipeZone(start, viewport)) {
    return false;
  }
  const deltaX = end.x - start.x;
  const deltaY = Math.abs(end.y - start.y);
  return deltaX >= MIN_HORIZONTAL_DISTANCE && deltaY <= MAX_VERTICAL_DRIFT;
}

export function isSidebarCloseSwipe(start: SidebarSwipePoint, end: SidebarSwipePoint): boolean {
  const deltaX = end.x - start.x;
  const deltaY = Math.abs(end.y - start.y);
  return deltaX <= -MIN_HORIZONTAL_DISTANCE && deltaY <= MAX_VERTICAL_DRIFT;
}

export function isHorizontalIntent(start: SidebarSwipePoint, current: SidebarSwipePoint): boolean {
  const deltaX = Math.abs(current.x - start.x);
  const deltaY = Math.abs(current.y - start.y);
  return deltaX > HORIZONTAL_INTENT_MIN_DISTANCE && deltaX > deltaY;
}
